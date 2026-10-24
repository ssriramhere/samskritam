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

from vidyut.lipi import Scheme, transliterate

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


def iast(slp: str) -> str:
    return transliterate(slp, Scheme.Slp1, Scheme.Iast)


def dev(s: str) -> str:
    return transliterate(s, Scheme.Iast, Scheme.Devanagari)


def trace(words, groups, line):
    """Joins for a printed line, falling back to one printed chunk at a time
    when the whole line can't be traced (cross-space joins are then lost)."""
    r = explain_line(words, groups, line)
    if r is not None:
        return [(words, groups, line, r)], True
    out, complete = [], True
    toks = line.split()
    by_group = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    for g, idx in by_group.items():
        if len(idx) < 2 or g >= len(toks):
            continue
        ws = [words[i] for i in idx]
        r = explain_line(ws, [0] * len(ws), toks[g])
        if r is None:
            complete = False
            continue
        out.append((ws, [0] * len(ws), toks[g], r))
    return out, complete


def render(words, groups, line, joins, types=None, ref=""):
    """Chunks of the printed line that contain joins, with highlights."""
    slp_line = to_slp1(line)
    # map positions in the cleaned line (no spaces or avagraha) to the printed line
    pos = [i for i, c in enumerate(slp_line) if c not in SKIP]
    mark = [False] * len(slp_line)
    for j in joins:
        for p in range(j["at"], j["at"] + max(j["len"], 1)):
            if p < len(pos):
                mark[pos[p]] = True
    # printed chunks with their character spans
    spans, start = [], 0
    for tok in slp_line.split(" "):
        spans.append((start, start + len(tok)))
        start += len(tok) + 1
    chunks, covered = {}, {}
    for j in joins:
        p = pos[min(j["at"], len(pos) - 1)]
        ci = next(i for i, (a, b) in enumerate(spans) if a <= p <= b)
        ci = covered.get(ci, ci)  # already shown as the second half of a join across a space
        if ci not in chunks:
            if j["across"] and ci + 1 < len(spans):
                covered[ci + 1] = ci
            a, b = spans[ci]
            end = spans[ci + 1][1] if j["across"] and ci + 1 < len(spans) else b
            segs, cur, on = [], "", None
            for k in range(a, end):
                if on is None or mark[k] == on:
                    cur += slp_line[k]
                else:
                    segs.append([iast(cur), int(on)])
                    cur = slp_line[k]
                on = mark[k]
            segs.append([iast(cur), int(bool(on))])
            text = iast(slp_line[a:end])
            chunks[ci] = {"s": text, "d": dev(text), "h": segs, "j": []}
        left, right = words[j["left"]], words[j["right"]]
        fa, ib, res = j["key"].split("|")
        lw = to_slp1(left)
        base = next((v for v in _finals(lw) if v.endswith(fa)), lw)
        joined = base[:-len(fa)] + (res if j["across"] else _clean(res)) + to_slp1(right)[1:]
        jn = iast(joined)
        chunks[ci]["j"].append({"a": left, "b": right, "r": jn, "ad": dev(left), "bd": dev(right),
                                "rd": dev(jn), "k": j["key"], "x": int(j["across"])})
        if types is not None:
            t = types[j["key"]]
            t["n"] += 1
            if len(t["all"]) < 400 and [left, right, jn] not in [x[:3] for x in t["all"]]:
                t["all"].append([left, right, jn, ref])
    return [chunks[k] for k in sorted(chunks)]
