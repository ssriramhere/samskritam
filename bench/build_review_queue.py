"""Build the answer-key review queue for samskritam.ai/review.

    python bench/build_review_queue.py      # -> bench/private/review-queue.json
    python bench/review_admin.py upload     # sends it to the site (invite-only)

Each question becomes a record the review page can show without knowing the
benchmark's internals: the question, the verse, the answer key in a readable
shape, where the key came from, any hand correction, and every model's answer.

Sets
  v0       the published benchmark (bench/data/v0.jsonl), with the published
           model answers (bench/results-v0/)
  v1-dev   bench/data/v1-dev.jsonl, if calibration has written it
  v1-test  bench/private/v1-test.jsonl (private: the queue file stays in
           bench/private/ and only invited reviewers see it on the site)
Questions dropped by hand review are included too, so the drop itself can be
reviewed: v1's, and v0's removed questions (bench/data/v0-removed.jsonl).

Tags (one per question, first that applies)
  fix      the key was corrected or the question dropped by hand
  missed   at least half the models disagreed with the key
  some     at least one model disagreed
  sample   a fixed random sample of the rest; model answers are hidden from
           the reviewer until they decide
  ok       every model agreed with the key
"""
import glob
import json
import os
import random
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402
from vidyut.lipi import Scheme, transliterate  # noqa: E402

from engine import meter  # noqa: E402

OUT = os.path.join(ROOT, "bench/private/review-queue.json")
SUTRAS = json.load(open(os.path.join(ROOT, "web/data/sutras.json"), encoding="utf-8"))
NAMES = {"anthropic/claude-opus-5.5": "Claude Opus 5.5", "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
         "google/gemini-4-argon": "Gemini 4 Argon", "google/gemini-3.8-flash": "Gemini 3.8 Flash",
         "openai/gpt-6-sol": "GPT-6 Sol", "sarvam-105b": "Sarvam-105B"}
FIELDS = {"context": ["lemma", "pos", "case", "number", "gender", "tense_mood", "person", "voice"],
          "gita": ["lemma", "pos", "case", "number", "gender", "tense_mood", "person", "voice"],
          "analyze": ["lakara", "purusha", "vacana"]}
KIND = {"context": "fields", "gita": "fields", "analyze": "fields", "tinanta": "forms", "subanta": "forms",
        "join": "forms", "split": "words", "rule": "sutras", "meter": "syllables"}
SAMPLE_PER_SET = {"v0": 50, "v1-dev": 25, "v1-test": 25}


def dev(iast):
    return transliterate(iast, Scheme.Iast, Scheme.Devanagari)


def model_name(path, rec):
    m = rec.get("model")
    if not m:  # provider__vendor_model[.set].jsonl
        m = re.sub(r"(\.v\d[\w-]*)?\.jsonl$", "", os.path.basename(path)).split("__")[-1].replace("_", "/", 1)
    return NAMES.get(m, m)


def answers(paths, items):
    """id -> [{name, answer, ok}] from results files (last answer per question)."""
    out = {}
    for path in paths:
        latest = {}
        for r in map(json.loads, open(path, encoding="utf-8")):
            if r.get("output") is not None or latest.get(r["id"], {}).get("output") is None:
                latest[r["id"]] = r
        for iid, r in latest.items():
            if iid not in items:
                continue
            if r.get("output") is None:
                shown, ok = "(no answer: " + str(r.get("error", ""))[:80] + ")", False
            else:
                got = grade.extract_json(r["output"])
                shown = json.dumps(got, ensure_ascii=False) if got is not None else r["output"][:300]
                ok = grade.grade_item(items[iid], r["output"])["correct"]
            out.setdefault(iid, []).append({"name": model_name(path, r), "answer": shown, "ok": ok})
    return out


def lines_after(prompt, start, stop):
    """The indented verse lines between a lead-in and the instruction."""
    body = prompt.split(start, 1)[1] if start in prompt else prompt
    body = body.split(stop, 1)[0]
    return [l.strip() for l in body.split("\n") if l.startswith("  ") and l.strip()]


_GITA = {}


def gita_lines():
    if not _GITA:
        d = json.load(open(os.path.join(ROOT, "data/build/gita.json"), encoding="utf-8"))
        for c in d["chapters"]:
            for v in c["verses"]:
                for h in v.get("halves", []):
                    _GITA[h["text"].strip()] = v["id"]
    return _GITA


def record(it, set_name, models, fixes):
    task, meta, key = it["task"], it.get("meta", {}), it["accept"]
    r = {"id": it["id"], "set": set_name, "task": task, "kind": KIND[task],
         "question": it["prompt"].split("Answer with JSON")[0].strip(), "models": models}
    verse = []
    if task in ("context", "gita"):
        verse = lines_after(it["prompt"], ":\n", "\nanalyse")
        r["title"] = f"Grammar of {meta.get('form')} in this verse"
        r["mark"] = meta.get("form")
        r["key"] = {f: key[0].get(f) for f in FIELDS[task] if f in key[0]}
        r["also"] = [{f: k.get(f) for f in FIELDS[task] if f in k} for k in key[1:]]
        r["source"] = meta.get("gold_source", "")
    elif task == "analyze":
        r["title"] = f"Identify the verb form {meta.get('form')}"
        r["key"] = {f: key[0].get(f) for f in FIELDS[task]}
        r["also"] = [{f: k.get(f) for f in FIELDS[task]} for k in key[1:]]
        r["source"] = "Vidyut's derivation of every form of the root"
    elif task in ("tinanta", "subanta"):
        r["title"] = "Form the word" if task == "tinanta" else "Decline the stem"
        r["key"] = key
        r["source"] = "Vidyut's derivation; every form it allows is accepted"
    elif task == "join":
        r["title"] = "Join these words"
        r["words"] = meta.get("words", [])
        r["key"] = key
        r["source"] = "Vidyut's sandhi table; every output it allows is accepted (the printed form among them)"
        verse = []
    elif task == "split":
        verse = lines_after(it["prompt"], ":\n", "\nundo")
        r["title"] = f"Split {meta.get('surface')}"
        r["mark"] = meta.get("surface")
        r["key"] = key[0]
        r["source"] = meta.get("gold_source", "")
    elif task == "rule":
        m = re.search(r"'(.+?)' and '(.+?)' join as '(.+?)'", it["prompt"])
        r["title"] = "Which sūtras produce this join?"
        r["words"] = [m.group(1), m.group(2)] if m else []
        r["joined"] = m.group(3) if m else ""
        r["key"] = [[c, SUTRAS.get(c, "")] for c in key[0]]
        r["source"] = f"Core sūtras of the rule family “{meta.get('family')}” (pipeline/check_sandhi_cites.py); extra sūtras are allowed"
    elif task == "meter":
        verse = lines_after(it["prompt"], ":\n", "\nApply")
        line = verse[0] if verse else ""
        w = meter.weights(line)
        anc = set(meta.get("anceps", []))
        pattern = key[0]
        sylls = [transliterate(s, Scheme.Slp1, Scheme.Iast) for s, _ in w]
        if len(sylls) != len(pattern):
            sylls = [""] * len(pattern)
        r["title"] = "Scan this half-verse"
        r["key"] = [[s, g, int(i in anc)] for i, (s, g) in enumerate(zip(sylls, pattern))]
        r["source"] = "Vidyut's prosody module; pāda-final syllables are not graded" + \
            (f" · {meta.get('meter')}{', ' + meta['variant'] if meta.get('variant') else ''}" if meta.get("meter") else "")
    if verse:
        r["verse"] = {"iast": verse, "dev": [dev(l) for l in verse]}
    if r.get("mark"):
        r["markDev"] = dev(r["mark"])
    if r["kind"] in ("forms", "words"):
        r["keyDev"] = [dev(x) for x in r["key"]]
    if r.get("words"):
        r["wordsDev"] = [dev(x) for x in r["words"]]
    if r.get("joined"):
        r["joinedDev"] = dev(r["joined"])
    if set_name.startswith("v1") and meta.get("verse"):
        r["ref"] = "Mahābhārata " + str(meta["verse"])
    elif task == "meter" and meta.get("verse"):
        r["ref"] = "Bhagavad Gītā " + str(meta["verse"])
    elif task == "gita" and verse:
        # v0's Gītā questions store only the verse number; find the chapter from the line.
        vid = gita_lines().get(verse[0])
        r["ref"] = "Bhagavad Gītā " + (vid or str(meta.get("verse", "")))
    fix = fixes.get(it["id"])
    if meta.get("dropped"):
        r["fix"] = {"what": "dropped", "why": meta["dropped"]}
    elif str(meta.get("gold_source", "")).startswith("hand-corrected"):
        r["fix"] = {"what": "corrected", "why": meta["gold_source"].split(": ", 1)[-1]}
        r["source"] = "Digital Corpus of Sanskrit annotation, replaced by hand (see below)"
    elif task == "rule" and "8.3.34" in key[0] and "8.2.66" not in key[0]:
        r["fix"] = {"what": "relaxed", "why": "The question starts from the visarga form, so 8.2.66 (s → ru) is no longer required."}
    return r


def tag(r):
    if r.get("fix"):
        return "fix"
    wrong = sum(not m["ok"] for m in r["models"])
    if r["models"] and wrong * 2 >= len(r["models"]):
        return "missed"
    if wrong:
        return "some"
    return "ok"


def main():
    queue = []
    v0 = grade.load_items(os.path.join(ROOT, "bench/data/v0.jsonl"))
    v0_ans = answers(sorted(glob.glob(os.path.join(ROOT, "bench/results-v0/*.jsonl"))), v0)
    queue += [record(it, "v0", v0_ans.get(i, []), {}) for i, it in v0.items()]
    # v0's removed questions, so each removal can be confirmed or overturned. The
    # published answers don't cover them; your own v0 runs in bench/results/ do.
    removed = grade.load_items(os.path.join(ROOT, "bench/data/v0-removed.jsonl"))
    raw = [f for f in glob.glob(os.path.join(ROOT, "bench/results/*.jsonl")) if not re.search(r"\.v\d", f)]
    rm_ans = answers(sorted(raw), removed)
    for i, it in removed.items():
        r = record(it, "v0", rm_ans.get(i, []), {})
        r["fix"] = {"what": "dropped", "why": it["meta"]["removed"] + " (removed from v0 before publishing)"}
        queue.append(r)

    pool_path = os.path.join(ROOT, "bench/private/v1-pool.jsonl")
    if os.path.exists(pool_path):
        pool = grade.load_items(pool_path)
        sets = {}
        for name, path in (("v1-dev", "bench/data/v1-dev.jsonl"), ("v1-test", "bench/private/v1-test.jsonl")):
            if os.path.exists(os.path.join(ROOT, path)):
                for i in grade.load_items(os.path.join(ROOT, path)):
                    sets[i] = name
        # hand-fixed or dropped questions are reviewed even when calibration left them out
        for i, it in pool.items():
            m = it.get("meta", {})
            relaxed = it["task"] == "rule" and "8.3.34" in it["accept"][0]
            if i not in sets and (m.get("dropped") or relaxed or str(m.get("gold_source", "")).startswith("hand")):
                sets[i] = "v1-test"
        v1_ans = answers(sorted(glob.glob(os.path.join(ROOT, "bench/results/*.v1-pool.jsonl"))), pool)
        queue += [record(pool[i], s, v1_ans.get(i, []), {}) for i, s in sets.items()]

    rng = random.Random(108)
    for r in queue:
        r["tag"] = tag(r)
    for s, n in SAMPLE_PER_SET.items():
        ok = [r for r in queue if r["set"] == s and r["tag"] == "ok"]
        for r in rng.sample(ok, min(n, len(ok))):
            r["tag"] = "sample"
    sets, tags = ["v1-test", "v1-dev", "v0"], ["fix", "missed", "some", "sample", "ok"]
    queue.sort(key=lambda r: (tags.index(r["tag"]), sets.index(r["set"]), r["id"]))
    for n, r in enumerate(queue):
        r["order"] = n
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False)
    from collections import Counter
    c = Counter((r["set"], r["tag"]) for r in queue)
    for s in ("v0", "v1-dev", "v1-test"):
        print(s, {t: c[(s, t)] for t in ("fix", "missed", "some", "sample", "ok") if c[(s, t)]})
    print(f"{len(queue)} questions, {os.path.getsize(OUT) // 1024} KB -> {OUT}")


if __name__ == "__main__":
    main()
