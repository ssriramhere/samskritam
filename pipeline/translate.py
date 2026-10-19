"""AI English translations for the texts in the reader. Standard library only.

Each verse is sent with its word-by-word analysis (the scholarly annotation the
reader shows), so the translation follows the same parsing. The output is
labelled on the site as the model's translation, not checked.

    export OPENROUTER_API_KEY=...
    python pipeline/translate.py gita meghaduta              # default model
    python pipeline/translate.py gita --model google/gemini-4-argon --limit 5

Writes web/data/<slug>-translations.json. Re-running resumes: verses already
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
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TITLES = {"gita": "the Bhagavad Gītā", "meghaduta": "Kālidāsa's Meghadūta"}

PROMPT = """Translate this verse from {title} ({ref}) into English.

{speaker}Verse (IAST):
{text}

Word-by-word analysis (word before sandhi, lemma, grammar):
{words}

Write a faithful, readable English translation in one to three sentences.
Follow the grammar given above. Keep names in their Sanskrit form with
diacritics (Arjuna, Kṛṣṇa, Yakṣa). No commentary, notes or brackets.
Answer with JSON only: {{"translation": "..."}}"""


def prompt_for(slug, v, part_names):
    ch, n = v["id"].split(".")
    ref = f"{ch}.{n}" if slug == "gita" else f"{part_names[int(ch) - 1]} {n}"
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
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY first.")
    texts = {t["slug"]: t for t in json.load(open(os.path.join(ROOT, "web/data/texts.json"), encoding="utf-8"))}

    for slug in a.slugs:
        verses = json.load(open(os.path.join(ROOT, f"web/data/{slug}.json"), encoding="utf-8"))["verses"]
        out_path = os.path.join(ROOT, f"web/data/{slug}-translations.json")
        out = {"model": a.model, "t": {}}
        if os.path.exists(out_path):
            old = json.load(open(out_path, encoding="utf-8"))
            if old.get("model") == a.model:
                out = old
        todo = [v for v in verses if v["id"] not in out["t"]][:a.limit]
        print(f"{slug}: {len(todo)} to translate, {len(out['t'])} done, model {a.model}")
        lock, pace_lock, next_slot, errors = threading.Lock(), threading.Lock(), [time.monotonic()], []

        def pace():
            with pace_lock:
                wait = next_slot[0] - time.monotonic()
                next_slot[0] = max(next_slot[0], time.monotonic()) + 60 / a.rpm
            if wait > 0:
                time.sleep(wait)

        def work(v):
            p = prompt_for(slug, v, texts[slug]["parts"])
            for attempt in range(5):
                pace()
                try:
                    tr = ask(a.model, p)
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
                out["t"][v["id"]] = tr
                n = len(out["t"])
                if n % 10 == 0 or n == len(verses):
                    save(out_path, out)
                    print(f"  {n}/{len(verses)}")

        with ThreadPoolExecutor(a.workers) as ex:
            list(ex.map(work, todo))
        save(out_path, out)
        print(f"{slug}: {len(out['t'])}/{len(verses)} translated -> {out_path}")
        for vid, err in errors:
            print("  failed", vid, err, "(re-run to retry)")


def save(path, out):
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".part", path)


if __name__ == "__main__":
    main()
