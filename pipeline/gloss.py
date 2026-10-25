"""AI word glosses for the texts in the Library: a short English meaning for
every word of a verse, in context. Standard library only.

Each verse is sent with its word-by-word analysis (the corpus's lemma and
grammar), so the gloss follows the same parsing. The site labels the glosses
as the model's, not checked.

    export OPENROUTER_API_KEY=...
    python pipeline/gloss.py gita --limit 20          # try a few first
    python pipeline/gloss.py ramayana --part 2        # one kāṇḍa at a time

Writes web/data/<slug>/<chapter>-glosses.json: {"model": ..., "g": {verse id:
[gloss of each word, in the order of the verse's words]}}. Re-running resumes.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from translate import TITLES  # noqa: E402

PROMPT = """Give a short English meaning for each word of this verse from {title} ({ref}), as it is used here.

Verse (IAST):
{text}

Words, in order (word before sandhi, lemma, grammar):
{words}

For each numbered word, give its meaning in this verse in one to four English words,
following the grammar given (for a compound member, the meaning of the member).
No explanations. Answer with JSON only: {{"glosses": ["<meaning of word 1>", "<word 2>", ...]}}
with exactly {n} entries."""


def prompt_for(slug, v):
    words = "\n".join(f"{i + 1}. {w['f']} ({w['l']}): {w['en']}" for i, w in enumerate(v["w"]))
    return PROMPT.format(title=TITLES.get(slug, slug), ref=v["id"], text="\n".join(v["iast"]),
                         words=words, n=len(v["w"]))


def ask(model, prompt, n):
    body = {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "HTTP-Referer": "https://samskritam.ai", "X-Title": "Samskritam.ai glosses"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    text = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    out = json.loads(m.group())["glosses"] if m else None
    if not isinstance(out, list) or len(out) != n:
        raise RuntimeError(f"expected {n} glosses, got {len(out) if isinstance(out, list) else 'none'}")
    return [str(x).strip()[:60] for x in out]


def save(tdir, out):
    by_ch = {}
    for vid, g in out["g"].items():
        by_ch.setdefault(vid.rsplit(".", 1)[0], {})[vid] = g
    for ch, part in by_ch.items():
        path = os.path.join(tdir, f"{ch}-glosses.json")
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump({"model": out["model"], "g": part}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(path + ".part", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--model", default="google/gemini-3.8-flash")
    ap.add_argument("--rpm", type=float, default=18)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="first N verses, for a test")
    ap.add_argument("--part", default=None, help="only verses under this part, e.g. 2 for the Ayodhyākāṇḍa")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY first.")
    for slug in a.slugs:
        tdir = os.path.join(ROOT, "web/data", slug)
        tindex = json.load(open(os.path.join(tdir, "index.json"), encoding="utf-8"))
        verses = [v for c in tindex["chapters"]
                  for v in json.load(open(os.path.join(tdir, f"{c['id']}.json"), encoding="utf-8"))["verses"]]
        for v in verses:  # large texts keep grammar labels in index.json
            for w in v["w"]:
                if "lb" in w:
                    w["sa"], w["en"] = tindex["labels"][w["lb"]]
        out = {"model": a.model, "g": {}}
        for c in tindex["chapters"]:
            f = os.path.join(tdir, f"{c['id']}-glosses.json")
            if os.path.exists(f):
                old = json.load(open(f, encoding="utf-8"))
                if old.get("model") == a.model:
                    out["g"].update(old["g"])
        todo = [v for v in verses if v["w"] and v["id"] not in out["g"]
                and (a.part is None or v["id"].startswith(a.part + "."))][:a.limit]
        print(f"{slug}: {len(todo)} to gloss, {len(out['g'])} done, model {a.model}")
        lock, pace_lock, next_slot, errors = threading.Lock(), threading.Lock(), [time.monotonic()], []

        def pace():
            with pace_lock:
                gap = next_slot[0] - time.monotonic()
                next_slot[0] = max(next_slot[0], time.monotonic()) + 60 / a.rpm
            if gap > 0:
                time.sleep(gap)

        def work(v):
            p = prompt_for(slug, v)
            for attempt in range(5):
                pace()
                try:
                    g = ask(a.model, p, len(v["w"]))
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503) and attempt < 4:
                        time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))
                        continue
                    errors.append((v["id"], repr(e)))
                    return
                except Exception as e:
                    if attempt < 4:
                        continue
                    errors.append((v["id"], repr(e)))
                    return
            with lock:
                out["g"][v["id"]] = g
                if len(out["g"]) % 10 == 0:
                    save(tdir, out)
                    print(f"  {len(out['g'])}/{len(verses)}")

        ex = ThreadPoolExecutor(a.workers)
        futures = [ex.submit(work, v) for v in todo]
        try:
            while wait(futures, timeout=1).not_done:
                pass
        except KeyboardInterrupt:
            with lock:
                save(tdir, out)
            print(f"\nStopped. {len(out['g'])}/{len(verses)} saved; run the same command to continue.")
            os._exit(1)
        ex.shutdown()
        save(tdir, out)
        print(f"{slug}: {len(out['g'])}/{len(verses)} glossed -> {tdir}")
        for vid, err in errors:
            print("  failed", vid, err, "(re-run to retry)")


if __name__ == "__main__":
    main()
