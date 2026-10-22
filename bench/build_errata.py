"""v0 errata: answer-key corrections from the review, and what they do to the scores.

    python bench/build_errata.py      # -> web/data/errata-v0.json (shown on /bench)

v0 stays as published: its questions, keys and leaderboard don't change. This
lists every settled review decision on a v0 question that changes something
(a corrected key, a dropped question, a removed question restored) and
re-grades each model's published answers with the corrected keys, so both
scores can be shown side by side. Only decisions merged into the repository
(bench/reviews/*.json) count here.

A restored question has no published answers (v0's removed questions were
taken out before the results were published); it is re-graded from your own
runs in bench/results/ when they are there, and listed as not re-graded
otherwise.
"""
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402
from review_decisions import fixed_accept, settled  # noqa: E402

OUT = os.path.join(ROOT, "web/data/errata-v0.json")


def show(task, accept):
    """A key as one line of text."""
    if task in ("gita", "analyze"):
        order = ["lemma", "pos", "case", "number", "gender", "tense_mood", "person", "voice",
                 "lakara", "purusha", "vacana"]
        return " / ".join(" · ".join(str(a[k]) for k in order if a.get(k) is not None) for a in accept)
    return " / ".join(str(a) for a in accept)


def latest(path):
    out = {}
    for r in map(json.loads, open(path, encoding="utf-8")):
        if r.get("output") is not None or out.get(r["id"], {}).get("output") is None:
            out[r["id"]] = r
    return out


def main():
    v0 = grade.load_items(os.path.join(ROOT, "bench/data/v0.jsonl"))
    removed = grade.load_items(os.path.join(ROOT, "bench/data/v0-removed.jsonl"))
    decisions = {i: d for i, d in settled(private=False).items() if i in v0 or i in removed}

    corrected, changes = dict(v0), []
    for iid, d in sorted(decisions.items()):
        it = v0.get(iid) or removed[iid]
        before = show(it["task"], it["accept"])
        change = None
        if iid in v0 and d["decision"] == "ambiguous":
            corrected.pop(iid)
            change, after = "dropped", "—"
        elif d["decision"] == "wrong" and d.get("fix"):
            new = dict(it, accept=fixed_accept(it["task"], d["fix"]))
            corrected[iid] = new
            change = "corrected" if iid in v0 else "restored with a corrected key"
            after = show(it["task"], new["accept"])
        elif iid in removed and d["decision"] == "right":
            corrected[iid] = it
            change, after = "restored", before
        if change:
            changes.append({"id": iid, "task": it["task"], "change": change, "before": before, "after": after,
                            "by": d["by"], "note": d.get("note") or "", "at": d["at"][:10],
                            "removed_because": it["meta"].get("removed")})

    lb = json.load(open(os.path.join(ROOT, "web/data/leaderboard.json"), encoding="utf-8"))
    published = {r["id"]: r for r in lb["rows"]}
    raw = {os.path.basename(f): f for f in glob.glob(os.path.join(ROOT, "bench/results/*.jsonl"))
           if not re.search(r"\.v\d", f)}
    scores, missing = [], {}
    for path in sorted(glob.glob(os.path.join(ROOT, "bench/results-v0/*.jsonl"))):
        ans = latest(path)
        if os.path.basename(path) in raw:  # answers to restored questions, from your own runs
            for iid, r in latest(raw[os.path.basename(path)]).items():
                if iid in removed and iid not in ans:
                    ans[iid] = r
        model = next((r.get("model") for r in ans.values() if r.get("model")), None)
        row = published.get(model) or published.get((model or "").split("/")[-1])
        if not row:
            continue
        right = n = 0
        for iid, it in corrected.items():
            r = ans.get(iid)
            if r is None:
                missing.setdefault(iid, []).append(row["model"])
                continue
            n += 1
            right += grade.grade_item(it, r.get("output"))["correct"]
        scores.append({"model": row["model"], "id": row["id"], "published": row["overall"],
                       "corrected": round(right / n, 4) if n else None, "n": n})
    for c in changes:
        if c["id"] in missing:
            c["not_regraded_for"] = missing[c["id"]]  # no answer from these models

    out = {"updated": datetime.date.today().isoformat(), "reviewed": len(decisions),
           "questions": len(corrected), "changes": changes, "scores": scores}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{len(decisions)} v0 questions reviewed, {len(changes)} changes -> {OUT}")
    for s in scores:
        print(f"  {s['model']:<32} published {100 * s['published']:.1f}%  corrected "
              f"{'' if s['corrected'] is None else f'{100 * s['corrected']:.1f}%'}")


if __name__ == "__main__":
    main()
