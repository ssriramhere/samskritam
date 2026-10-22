"""Settled decisions from the answer-key review (samskritam.ai/review).

Sources: bench/reviews/*.json (decisions on public questions, merged through
pull requests) and bench/private/reviews.json (everything, pulled by
bench/review_admin.py pull). A question is settled by the owner's ruling, or
by reviewers who agree with each other; otherwise its key stays as it is.
"""
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def records(private=True):
    recs = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "bench/reviews/*.json"))):
        r = json.load(open(f, encoding="utf-8"))
        recs[r["id"]] = r
    priv = os.path.join(ROOT, "bench/private/reviews.json")
    if private and os.path.exists(priv):
        for iid, r in json.load(open(priv, encoding="utf-8")).items():
            recs.setdefault(iid, r)
    return recs


def settle(rec):
    """The decision that counts for one question, or None if reviewers disagree."""
    ds = rec.get("decisions", [])
    owner = [d for d in ds if d.get("reviewer") == "owner"]
    if owner:
        return owner[-1]
    if ds and len({(d["decision"], json.dumps(d.get("fix"), sort_keys=True)) for d in ds}) == 1:
        return ds[-1]
    return None


def settled(private=True, quiet=False):
    out = {}
    for iid, r in records(private).items():
        d = settle(r)
        if d:
            out[iid] = d
        elif r.get("decisions") and not quiet:
            print(f"  review of {iid}: reviewers disagree and the owner hasn't ruled; key unchanged")
    return out


def fixed_accept(task, fix):
    """A reviewer's corrected answer in the item's 'accept' shape."""
    if task in ("context", "gita"):
        return [{k: v for k, v in fix.items() if v is not None}]
    if task == "analyze":
        return [fix]
    if task in ("split", "meter"):
        return [fix]
    if task == "rule":
        return [sorted(fix)]
    if task == "padapatha":  # hyphens mark a compound's members
        return [[w if "-" not in w else {"members": [m for m in w.split("-") if m], "accept": [w.replace("-", "")]}
                 for w in fix]]
    if task == "parse":
        return [[{k: v for k, v in row.items() if v is not None} for row in fix]]
    if task == "scan":
        return [{"lines": fix["lines"], "meter": fix["meter"], "variant": None}]
    return list(fix)  # tinanta, subanta, join, generate: every accepted form
