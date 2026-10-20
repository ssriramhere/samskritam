"""Explain how the words of a printed line join, using Vidyut's sandhi table.

Given the scholars' word split of a line (pausa forms) and the printed line,
find the sequence of junctions that turns the words into the printed text.
Each junction is described by (final, initial, result) from Vidyut's
rules.csv, in SLP1. Words that meet without change are not junctions.

    joins = explain_line(words, group_index, printed_line)
"""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from functools import lru_cache

from .verify import DATA, to_slp1

SKIP = set(" '-")


@lru_cache(maxsize=1)
def rules():
    table = defaultdict(list)
    with open(os.path.join(DATA, "sandhi", "rules.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["second"]:
                table[(r["first"], r["second"])].append(r["result"])
    return table


def _finals(w: str):
    """Underlying finals a pausa form may stand for: -ḥ is s or r, -ṃ is m."""
    out = [w]
    if w.endswith("H"):
        out += [w[:-1] + "s", w[:-1] + "r"]
    if w.endswith("M"):
        out.append(w[:-1] + "m")
    # Some annotations cite a final voiced or palatal stop (kaścid, ced,
    # tvac); before a pause it is the voiceless stop (kaścit, cet, tvak).
    pausa = {"d": "t", "g": "k", "b": "p", "q": "w", "j": "k", "c": "k", "D": "t", "G": "k", "B": "p"}
    if w[-1:] in pausa:
        out.append(w[:-1] + pausa[w[-1]])
    return out


def _clean(s: str) -> str:
    return "".join(c for c in s if c not in SKIP)


def explain_line(words: list[str], groups: list[int], line: str):
    """words: pausa forms (IAST); groups: printed-chunk index of each word;
    line: printed line (IAST). Returns a list of joins, or None if no
    sequence of table rules reproduces the line."""
    w = [to_slp1(x) for x in words]
    target = _clean(to_slp1(line))
    R = rules()

    def options(acc, nxt):
        yield acc + nxt, None
        for a in _finals(acc)[1:]:
            if a[-1] not in "sr":
                yield a + nxt, None  # pausa form of an annotated final (ced -> cet), no join
        for a in _finals(acc):
            for k in (2, 1):
                fa, ib = a[-k:], nxt[:1]
                for out in R.get((fa, ib), []):
                    yield a[:-k] + _clean(out) + nxt[1:], (fa, ib, out, len(a) - k)

    best = None

    def rec(i, acc, joins):
        nonlocal best
        if best is not None:
            return
        if i == len(w):
            if acc == target or (acc[:-1] == target[:-1] and len(acc) == len(target)):
                best = joins
            return
        for j, rule in options(acc, w[i]):
            if not target.startswith(j[:max(0, len(j) - 2)]):
                continue
            rec(i + 1, j, joins + ([(i, rule)] if rule else []))

    rec(1, w[0], [])
    if best is None:
        return None
    out = []
    for i, (fa, ib, res, at) in best:
        out.append({"left": i - 1, "right": i, "key": f"{fa}|{ib}|{res}",
                    "across": groups[i - 1] != groups[i], "at": at, "len": len(_clean(res))})
    return out
