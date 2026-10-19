"""Write the published copy of each model's answers: one line per question in
the current set, with the final answer, the grade, and nothing else.

    python bench/publish_results.py

Reads bench/results/*.jsonl (raw runs, including retries) and writes
bench/results-v0/<model>.jsonl and web/data/results-v0/<model>.jsonl.
"""
import glob
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
import grade  # noqa: E402

items = grade.load_items(os.path.join(ROOT, "bench/data/v0.jsonl"))
out_dir = os.path.join(ROOT, "bench/results-v0")
web_dir = os.path.join(ROOT, "web/data/results-v0")
os.makedirs(out_dir, exist_ok=True)
os.makedirs(web_dir, exist_ok=True)
index = []
for path in sorted(glob.glob(os.path.join(ROOT, "bench/results/*.jsonl"))):
    latest = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or r["id"] not in latest:
            latest[r["id"]] = r
    rows = []
    for iid, it in items.items():
        r = latest.get(iid)
        if not r or r.get("output") is None:
            print(f"skip {os.path.basename(path)}: {iid} unanswered")
            rows = None
            break
        g = grade.grade_item(it, r["output"])
        rows.append({"id": iid, "task": it["task"], "model": r.get("model"),
                     "provider": r.get("provider"), "output": r["output"],
                     "correct": bool(g["correct"])})
    if rows is None:
        continue
    name = os.path.basename(path)
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    shutil.copyfile(os.path.join(out_dir, name), os.path.join(web_dir, name))
    index.append({"model": rows[0]["model"], "file": name,
                  "correct": sum(r["correct"] for r in rows), "n": len(rows)})
    print(name, index[-1]["correct"], "/", len(rows))
json.dump(index, open(os.path.join(web_dir, "index.json"), "w"), indent=1)
