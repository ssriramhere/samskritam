"""Grade every results file and write web/data/leaderboard.json."""
import datetime
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import grade  # noqa: E402

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
    rows.append({"model": model, "overall": s["overall"]["acc"],
                 "tasks": {k: v["acc"] for k, v in s["by_task"].items()}})
    with open(path.replace(".jsonl", ".graded.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False)
rows.sort(key=lambda r: -r["overall"])
out = {"benchmark": "samskritam-bench v0", "items": len(items),
       "updated": datetime.date.today().isoformat(), "rows": rows}
with open(os.path.join(ROOT, "web/data/leaderboard.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
for r in rows:
    print(f"{r['overall']:.1%}  {r['model']}  {r['tasks']}")
