"""AI English translations for the texts in the reader. Standard library only.

Each verse is sent with its word-by-word analysis (the scholarly annotation the
reader shows), so the translation follows the same parsing. The output is
labelled on the site as the model's translation, not checked.

    export OPENROUTER_API_KEY=...
    python pipeline/translate.py mahabharata               # default model
    python pipeline/translate.py gita --model google/gemini-4-argon --limit 5
    python pipeline/translate.py ramayana --part 2        # one kāṇḍa (or parvan) at a time

Writes web/data/<slug>/<chapter>-translations.json. Re-running resumes: verses already
translated by the same model are skipped.
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
TITLES = {"gita": "the Bhagavad Gītā", "meghaduta": "Kālidāsa's Meghadūta",
          "mahabharata": "the Mahābhārata (critical edition)",
          "kumarasambhava": "Kālidāsa's Kumārasaṃbhava", "rtusamhara": "the Ṛtusaṃhāra",
          "ramayana": "Vālmīki's Rāmāyaṇa", "kathopanisad": "the Kaṭha Upaniṣad",
          "astavakragita": "the Aṣṭāvakragītā"}

PROMPT = """Translate this verse from {title} ({ref}) into English.

{speaker}Verse (IAST):
{text}

Word-by-word analysis (word before sandhi, lemma, grammar):
{words}

Write a faithful, readable English translation in one to three sentences.
Follow the grammar given above. Keep names in their Sanskrit form with
diacritics (Arjuna, Kṛṣṇa, Yakṣa). No commentary, notes or brackets.
Answer with JSON only: {{"translation": "..."}}"""


def prompt_for(slug, v, labels):
    ch, n = v["id"].rsplit(".", 1)
    ref = f"{labels[ch]} {n}" if slug == "meghaduta" else v["id"]
    words = "\n".join(f"- {w['f']} ({w['l']}): {w['en']}" for w in v["w"]) or "(none)"
    speaker = f"Speaker: {v['sp']}\n" if v.get("sp") else ""
    return PROMPT.format(title=TITLES.get(slug, slug), ref=ref, speaker=speaker,
                         text="\n".join(v["iast"]), words=words)


def ask(model, prompt):
    body = {"model": model, "max_tokens": 4000,
            "messages": [{"role": "user", "content": prompt}]}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "HTTP-Referer": "https://samskritam.ai", "X-Title": "Samskritam.ai translations"})
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"] or ""
    text = re.sub(r"```(?:json)?", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    out = (json.loads(m.group())["translation"] if m else "").strip()
    if not out:
        raise RuntimeError("empty translation")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="+")
    ap.add_argument("--model", default="anthropic/claude-opus-5.5")
    ap.add_argument("--rpm", type=float, default=18, help="requests per minute (OpenRouter new accounts: 20)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="first N verses, for a test")
    ap.add_argument("--part", default=None, help="only verses under this part, e.g. 2 for the Rāmāyaṇa's Ayodhyākāṇḍa")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY first.")
    outcome = []  # so a shell loop can tell a finished run from a stopped one
    for slug in a.slugs:
        tdir = os.path.join(ROOT, "web/data", slug)
        tindex = json.load(open(os.path.join(tdir, "index.json"), encoding="utf-8"))
        labels = {c["id"]: c["label"] for c in tindex["chapters"]}
        verses = [v for c in tindex["chapters"]
                  for v in json.load(open(os.path.join(tdir, f"{c['id']}.json"), encoding="utf-8"))["verses"]]
        for v in verses:  # large texts keep grammar labels in index.json
            for w in v["w"]:
                if "lb" in w:
                    w["sa"], w["en"] = tindex["labels"][w["lb"]]
        out_path = tdir  # one <chapter>-translations.json per chapter
        out = {"model": a.model, "t": {}}
        for c in tindex["chapters"]:
            f = os.path.join(tdir, f"{c['id']}-translations.json")
            if os.path.exists(f):
                old = json.load(open(f, encoding="utf-8"))
                if old.get("model") == a.model:
                    out["t"].update(old["t"])
        todo = [v for v in verses if v["id"] not in out["t"]
                and (a.part is None or v["id"].startswith(a.part + "."))][:a.limit]
        print(f"{slug}: {len(todo)} to translate, {len(out['t'])} done, model {a.model}")
        lock, pace_lock, next_slot, errors, stop = threading.Lock(), threading.Lock(), [time.monotonic()], [], []

        def pace():
            with pace_lock:
                wait = next_slot[0] - time.monotonic()
                next_slot[0] = max(next_slot[0], time.monotonic()) + 60 / a.rpm
            if wait > 0:
                time.sleep(wait)

        def work(v):
            if stop:
                return
            p = prompt_for(slug, v, labels)
            for attempt in range(5):
                pace()
                try:
                    tr = ask(a.model, p)
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503) and attempt < 4:
                        time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))
                        continue
                    try:
                        detail = e.read().decode("utf-8", "replace")[:300]
                    except Exception:
                        detail = ""
                    errors.append((v["id"], f"HTTP {e.code} {detail}"))
                    if e.code in (401, 402, 403) and not stop:
                        # Key, credits or budget: every later request would fail the same way.
                        stop.append(f"HTTP {e.code} from OpenRouter: {detail}")
                        print(f"\nStopping: {stop[0]}\nCheck the key's credit and spending limit at "
                              "openrouter.ai/settings/keys, then run the same command to continue.")
                    return
                except Exception as e:
                    if attempt < 4:
                        continue
                    errors.append((v["id"], repr(e)))
                    return
            with lock:
                out["t"][v["id"]] = tr
                n = len(out["t"])
                if n % 10 == 0 or n == len(verses):
                    save(out_path, out)
                    print(f"  {n}/{len(verses)}")

        ex = ThreadPoolExecutor(a.workers)
        futures = [ex.submit(work, v) for v in todo]
        try:
            # Wait in short steps: a plain blocking wait ignores Ctrl+C on Windows.
            while wait(futures, timeout=1).not_done:
                pass
        except KeyboardInterrupt:
            with lock:
                save(out_path, out)
            print(f"\nStopped. {len(out['t'])}/{len(verses)} saved; run the same command to continue.")
            os._exit(1)  # don't wait for requests still in flight
        ex.shutdown()
        save(out_path, out)
        print(f"{slug}: {len(out['t'])}/{len(verses)} translated -> {out_path}")
        shown = errors if not stop else errors[:3]
        for vid, err in shown:
            print("  failed", vid, err, "(re-run to retry)")
        if stop:
            print(f"  stopped early; {len(errors)} requests failed. Run the same command to continue.")
        outcome.append("stopped" if stop else "failed" if errors else "ok")
        if stop:
            break
    if "stopped" in outcome:
        sys.exit(2)
    if "failed" in outcome:
        sys.exit(1)


def save(tdir, out):
    """Write one <chapter>-translations.json per chapter that has translations."""
    by_ch = {}
    for vid, t in out["t"].items():
        by_ch.setdefault(vid.rsplit(".", 1)[0], {})[vid] = t
    for ch, part in by_ch.items():
        path = os.path.join(tdir, f"{ch}-translations.json")
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump({"model": out["model"], "t": part}, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(path + ".part", path)


if __name__ == "__main__":
    main()
