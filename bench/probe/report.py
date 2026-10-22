"""Memorisation probe report: how much of each text the models can recite.

    python bench/probe/report.py bench/results/*.memory-probe.jsonl

For each text and model: the share of verses whose second half the model
reproduced near-verbatim (similarity >= 0.9) and the mean similarity. A text
the models recite is a poor source of benchmark questions.
"""
import collections
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402

items = grade.load_items(os.path.join(ROOT, "bench/probe/memory-probe.jsonl"))
models, table = [], collections.defaultdict(dict)
for path in sys.argv[1:]:
    name = os.path.basename(path).split(".memory-probe")[0].split("__")[-1]
    models.append(name)
    latest = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or r["id"] not in latest:
            latest[r["id"]] = r
    per = collections.defaultdict(list)
    for iid, r in latest.items():
        if iid in items:
            g = grade.grade_item(items[iid], r.get("output")) if r.get("output") else {"correct": False, "similarity": 0}
            per[items[iid]["meta"]["text"]].append((g["correct"], g.get("similarity", 0)))
    for text, v in per.items():
        table[text][name] = (sum(c for c, _ in v) / len(v), sum(s for _, s in v) / len(v), len(v))

group = {it["meta"]["text"]: it["meta"]["group"] for it in items.values()}
order = sorted(table, key=lambda t: (group[t] != "control", -max(x[0] for x in table[t].values())))
w = max(len(t) for t in table) + 2
print("Recited = second half reproduced near-verbatim (similarity >= 0.9); sim = mean similarity.\n")
print(" " * w + "".join(f"{m[:24]:>28}" for m in models))
for t in order:
    cells = "".join(f"{(f'{100 * table[t][m][0]:.0f}% recited, sim {table[t][m][1]:.2f}' if m in table[t] else '—'):>28}" for m in models)
    print(f"{t:<{w}}{cells}   {'(control)' if group[t] == 'control' else ''}")
