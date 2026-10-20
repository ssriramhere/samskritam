"""Grade every results file and write web/data/leaderboard.json."""
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import grade  # noqa: E402

# Display names for the site; the id column keeps the exact model string.
NAMES = {"anthropic/claude-opus-5.5": "Claude Opus 5.5",
         "anthropic/claude-sonnet-5.5": "Claude Sonnet 5.5",
         "google/gemini-4-argon": "Gemini 4 Argon",
         "google/gemini-3.8-flash": "Gemini 3.8 Flash",
         "openai/gpt-6-sol": "GPT-6 Sol",
         "sarvam-105b": "Sarvam-105B (reasoning off)"}

# Runs of one model with different settings, told apart by results file name
# (bench/run.py --tag).
FILE_NAMES = {"sarvam__sarvam-105b.reasoning-low": "Sarvam-105B (reasoning on, low effort)"}

# Shown under the table, for runs that differ from the default setup.
NOTES = {"sarvam-105b": "Sarvam-105B ran through Sarvam's own API with reasoning turned off. With reasoning on, it used its whole 8,192-token budget before answering most questions. In a 10-question test with reasoning on (low effort, 32,000-token budget), it ran out on 5, got 2 right, and used about 20,000 tokens for each answer it finished; with reasoning off it also got 2 of those 10 right. Sanskrit is not among the languages Sarvam lists for this model."}

items = grade.load_items(os.path.join(ROOT, "bench/data/v0.jsonl"))
rows = []
for path in sorted(glob.glob(os.path.join(ROOT, "bench/results/*.jsonl"))):
    latest = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or r["id"] not in latest:
            latest[r["id"]] = r
    results = [r for r in latest.values() if r["id"] in items]
    answered = sum(r.get("output") is not None for r in results)
    if answered < len(items):
        print(f"skip {os.path.basename(path)}: {answered}/{len(items)} answered")
        continue
    s = grade.score(items, results)
    model = next((r.get("model") for r in results if r.get("model")), os.path.basename(path))
    stem = os.path.basename(path)[:-len(".jsonl")]
    rows.append({"model": FILE_NAMES.get(stem) or NAMES.get(model, model), "id": model, "overall": s["overall"]["acc"],
                 "tasks": {k: v["acc"] for k, v in s["by_task"].items()},
                 **({"note": NOTES[model]} if model in NOTES else {})})
    with open(path.replace(".jsonl", ".graded.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
rows.sort(key=lambda r: -r["overall"])
out = {"benchmark": "samskritam-bench v0", "items": len(items),
       "updated": datetime.date.today().isoformat(), "rows": rows}
with open(os.path.join(ROOT, "web/data/leaderboard.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
for r in rows:
    print(f"{r['overall']:.1%}  {r['model']}  {r['tasks']}")
