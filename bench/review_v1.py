"""List the v1 questions some pilot model got wrong, with the key and every
model's answer, for checking keys by hand.

    python bench/review_v1.py bench/results/*.v1-pool.jsonl
    -> bench/private/v1-review-answers.tsv   (private: it shows test answers)

Rows where every model is wrong come first: those are the likeliest bad keys.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402

items = grade.load_items(os.path.join(ROOT, "bench/private/v1-pool.jsonl"))
models, answers = [], {}
for path in sys.argv[1:]:
    name = os.path.basename(path).split(".v1-pool")[0].split("__")[-1]
    models.append(name)
    latest = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or latest.get(r["id"], {}).get("output") is None:
            latest[r["id"]] = r
    for iid, r in latest.items():
        if iid in items:
            ok = r.get("output") is not None and grade.grade_item(items[iid], r["output"])["correct"]
            got = grade.extract_json(r.get("output") or "") if r.get("output") else None
            answers.setdefault(iid, {})[name] = (ok, json.dumps(got, ensure_ascii=False) if got is not None
                                                 else (r.get("error") or r.get("output") or "")[:200])

rows = []
for iid, by in answers.items():
    wrong = sum(not by.get(m, (False,))[0] for m in models)
    if wrong:
        it = items[iid]
        q = it["prompt"].split("Answer with JSON")[0].replace("\n", " ").strip()[:400]
        rows.append((-wrong, iid, it["task"], q, json.dumps(it["accept"], ensure_ascii=False),
                     [("OK " if by[m][0] else "XX ") + by[m][1].replace("\t", " ").replace("\n", " ")
                      if m in by else "" for m in models]))
rows.sort()
out = os.path.join(ROOT, "bench/private/v1-review-answers.tsv")
with open(out, "w", encoding="utf-8") as f:
    f.write("\t".join(["wrong", "id", "task", "question", "key"] + models) + "\n")
    for w, iid, task, q, key, ans in rows:
        f.write("\t".join([str(-w), iid, task, q, key] + ans) + "\n")
print(f"{len(rows)} questions with at least one wrong answer "
      f"({sum(1 for r in rows if -r[0] == len(models))} wrong for every model) -> {out}")
