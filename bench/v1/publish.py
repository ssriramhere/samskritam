"""Publish v1's scores to the site: web/data/bench-v1.json (shown on /bench).

    python bench/v1/publish.py
    git add web/data/bench-v1.json && git commit -m "v1 scores" && git push

Scores come from your runs (bench/results/*.v1.jsonl), graded against the
current keys in bench/private/v1.jsonl, so corrections from the answer-key
review count once you've pulled them (bench/review_admin.py pull) and
regenerated the questions (bench/v1/generate.py). Only scores are published:
the questions and answers stay private. The memorisation probe's results
(bench/results/*.memory-probe.jsonl) are included when they are there.
"""
import collections
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402

NAMES = {"anthropic/claude-opus-5.5": "Claude Opus 5.5", "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
         "google/gemini-4-argon": "Gemini 4 Argon", "google/gemini-3.8-flash": "Gemini 3.8 Flash",
         "openai/gpt-6-sol": "GPT-6 Sol", "sarvam-105b": "Sarvam-105B (reasoning off)"}
TASKS = ["padapatha", "parse", "scan", "generate"]
V1_TEXTS = ["Kathāsaritsāgara", "Bṛhatkathāślokasaṃgraha", "Bhāratamañjarī", "Skandapurāṇa (Revākhaṇḍa)",
            "Kālikāpurāṇa", "Liṅgapurāṇa", "Harivaṃśa", "Rasaratnākara", "Kokilasaṃdeśa", "Haṃsadūta", "Narmamālā"]


def latest(path):
    out = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or out.get(r["id"], {}).get("output") is None:
            out[r["id"]] = r
    return out


def model_of(path, recs):
    m = next((r.get("model") for r in recs.values() if r.get("model")), None)
    if not m:
        m = os.path.basename(path).split(".")[0].split("__")[-1].replace("_", "/", 1)
    return m


def main():
    items = grade.load_items(os.path.join(ROOT, "bench/private/v1.jsonl"))
    live = {i: it for i, it in items.items() if not it.get("meta", {}).get("dropped")}
    n_task = collections.Counter(it["task"] for it in live.values())
    rows = []
    for path in sorted(glob.glob(os.path.join(ROOT, "bench/results/*.v1.jsonl"))):
        recs = latest(path)
        model = model_of(path, recs)
        right, seen = collections.Counter(), collections.Counter()
        for iid, it in live.items():
            r = recs.get(iid)
            seen[it["task"]] += 1
            if r and r.get("output") is not None and grade.grade_item(it, r["output"])["correct"]:
                right[it["task"]] += 1
        if sum(1 for i in live if i in recs) < len(live):
            print(f"skip {os.path.basename(path)}: not every question answered")
            continue
        rows.append({"id": model, "model": NAMES.get(model, model),
                     "overall": round(sum(right.values()) / len(live), 4),
                     "tasks": {t: round(right[t] / seen[t], 4) for t in TASKS if seen[t]}})
    rows.sort(key=lambda r: -r["overall"])

    # memorisation probe: share of verses each model recited near-verbatim, per text
    probe = {"texts": [], "models": []}
    pitems_path = os.path.join(ROOT, "bench/probe/memory-probe.jsonl")
    pfiles = sorted(glob.glob(os.path.join(ROOT, "bench/results/*.memory-probe.jsonl")))
    if pfiles and os.path.exists(pitems_path):
        pitems = grade.load_items(pitems_path)
        table = collections.defaultdict(dict)
        for path in pfiles:
            recs = latest(path)
            name = NAMES.get(model_of(path, recs), model_of(path, recs))
            per = collections.defaultdict(list)
            for iid, r in recs.items():
                if iid in pitems and r.get("output") is not None:
                    per[pitems[iid]["meta"]["text"]].append(grade.grade_item(pitems[iid], r["output"])["correct"])
            if sum(len(v) for v in per.values()) < len(pitems):
                print(f"probe: {name} answered {sum(len(v) for v in per.values())} of {len(pitems)}; its column is partial")
            probe["models"].append(name)
            for text, v in per.items():
                table[text][name] = round(sum(v) / len(v), 3)
        group = {it["meta"]["text"]: it["meta"]["group"] for it in pitems.values()}
        probe["texts"] = sorted(({"text": t, "control": group[t] == "control", "in_v1": t in V1_TEXTS, "recited": table[t]}
                                 for t in table), key=lambda x: -max(x["recited"].values()))

    reviews_path = os.path.join(ROOT, "bench/private/reviews.json")
    reviewed = corrected = 0
    if os.path.exists(reviews_path):
        for iid, r in json.load(open(reviews_path, encoding="utf-8")).items():
            if iid in items:
                reviewed += 1
        corrected = sum(1 for it in items.values()
                        if str(it.get("meta", {}).get("gold_source", "")).startswith("corrected in review")
                        or it.get("meta", {}).get("dropped"))
    out = {"benchmark": "samskritam-bench v1", "status": "preview", "updated": datetime.date.today().isoformat(),
           "items": len(live), "tasks": dict(n_task), "texts": V1_TEXTS, "rows": rows, "probe": probe,
           "review": {"reviewed": reviewed, "changed": corrected},
           "notes": {"sarvam-105b": "Run through Sarvam's own API with reasoning off, as in v0."}}
    dest = os.path.join(ROOT, "web/data/bench-v1.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    for r in rows:
        print(f"{100 * r['overall']:5.1f}%  {r['model']:<30} " + "  ".join(f"{t} {100 * v:.0f}" for t, v in r["tasks"].items()))
    print(f"-> {dest}")


if __name__ == "__main__":
    main()
