"""Every v1 question some model got wrong, with the key and each model's answer,
to tell real mistakes from grading or key problems.

    python bench/v1/mistakes.py bench/results/*.v1.jsonl
    -> bench/private/v1-mistakes.txt   (private: it shows test answers)

Grouped by task; for each question, what was wrong in each model's answer:
for padapāṭha, the first word where the answer and the key part ways; for
parse, the words and fields that differ; for scan, the lines and the meter name.
"""
import collections
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402

items = grade.load_items(os.path.join(ROOT, "bench/private/v1.jsonl"))
answers = collections.defaultdict(dict)
for path in sys.argv[1:]:
    name = os.path.basename(path).split(".v1.jsonl")[0].split("__")[-1]
    latest = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or latest.get(r["id"], {}).get("output") is None:
            latest[r["id"]] = r
    for iid, r in latest.items():
        if iid in items:
            answers[iid][name] = r.get("output")


def flat_key(w):
    return w if isinstance(w, str) else "-".join(w["members"])


def where_pada(key, got):
    """First position where the answer's words leave the key."""
    for i in range(min(len(key), len(got)) + 1):
        if not grade._pada_ok(key[i:], got[i:]):
            k = [flat_key(w) for w in key[i:i + 3]]
            return f"from word {i + 1}: key {' '.join(k)} | answer {' '.join(got[i:i + 3])}"
    return "?"


out = []
for task in ("padapatha", "parse", "scan", "generate"):
    out.append(f"\n{'=' * 20} {task} {'=' * 20}")
    for iid, it in items.items():
        if it["task"] != task:
            continue
        wrong = {m: o for m, o in answers[iid].items() if not grade.grade_item(it, o)["correct"]}
        if not wrong:
            continue
        out.append(f"\n## {iid}  ({len(wrong)} of {len(answers[iid])} wrong)  {it['meta'].get('text', '')} {it['meta'].get('ref', '')}")
        q = it["prompt"].split("Answer with JSON")[0].strip()
        out.append(q[:900])
        if task == "padapatha":
            out.append("KEY: " + " ".join(flat_key(w) for w in it["accept"][0]))
        elif task == "parse":
            for w, k in zip(it["meta"]["words"], it["accept"][0]):
                out.append(f"KEY {w}: " + " ".join(f"{f}={v}" for f, v in k.items()))
        elif task == "scan":
            k = it["accept"][0]
            out.append(f"KEY meter={k['meter']} ({k.get('variant')}) lines={' / '.join(k['lines'])} anceps={it['meta'].get('anceps')}")
        else:
            out.append("KEY: " + " / ".join(it["accept"]))
        for m, o in wrong.items():
            ans = grade.extract_json(o or "", nested=task == "parse") or {}
            if task == "padapatha":
                got = [w for w in ans.get("words", []) if isinstance(w, str)]
                detail = where_pada(it["accept"][0], [w.strip() for w in got])
            elif task == "parse":
                got = ans.get("words") if isinstance(ans.get("words"), list) else []
                bad = []
                for i, (w, k) in enumerate(zip(it["meta"]["words"], it["accept"][0])):
                    a = got[i] if i < len(got) and isinstance(got[i], dict) else {}
                    if not grade._parse_word_ok(a, k):
                        diff = [f"{f}: {a.get(f)}≠{k.get(f)}" for f in ("lemma", "pos", "case", "number", "gender", "tense_mood", "person", "voice")
                                if k.get(f) is not None and str(a.get(f)).lower() != str(k.get(f)).lower()]
                        bad.append(f"{w} ({', '.join(diff) or 'allowances'})")
                detail = "; ".join(bad) + (f" [answer has {len(got)} words]" if len(got) != len(it["accept"][0]) else "")
            elif task == "scan":
                g = grade.grade_item(it, o)
                lines = ans.get("lines") if isinstance(ans.get("lines"), list) else []
                detail = (f"meter={ans.get('meter')!r} ({'ok' if g.get('meter') else 'WRONG'}); lines "
                          f"{'ok' if g.get('lines') else 'WRONG'}: {' / '.join(re.sub(r'[^GL]', '', str(l).upper()) for l in lines)}")
            else:
                detail = str(ans.get("form"))
            out.append(f"  {m}: {detail}")

path = os.path.join(ROOT, "bench/private/v1-mistakes.txt")
with open(path, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print(f"-> {path}")
