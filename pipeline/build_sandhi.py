"""Trace how the words of each Library verse join, using Vidyut's sandhi table.

    python pipeline/build_sandhi.py

Writes
  web/data/<slug>-sandhi.json   per verse: the printed chunks that contain joins,
                                each join (left word + right word -> joined text)
                                and its junction type
  data/build/sandhi-types.json  each junction type with examples, the input
                                to pipeline/sandhi_cite.py (AI sūtra citations)
  web/data/sutras.json          sūtra number -> text (IAST), from Vidyut's
                                sūtrapāṭha, used to check and display citations
"""
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.lipi import Scheme, transliterate  # noqa: E402

from engine import sandhi  # noqa: E402
from engine.verify import DATA, to_slp1  # noqa: E402

TEXTS = [("gita", "gita.json"), ("meghaduta", "meghaduta.json")]


def iast(slp: str) -> str:
    return transliterate(slp, Scheme.Slp1, Scheme.Iast)


def dev(s: str) -> str:
    return transliterate(s, Scheme.Iast, Scheme.Devanagari)


def trace(words, groups, line):
    """Joins for a printed line, falling back to one printed chunk at a time
    when the whole line can't be traced (cross-space joins are then lost)."""
    r = sandhi.explain_line(words, groups, line)
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
        r = sandhi.explain_line(ws, [0] * len(ws), toks[g])
        if r is None:
            complete = False
            continue
        out.append((ws, [0] * len(ws), toks[g], r))
    return out, complete


def render(words, groups, line, joins, types, ref):
    """Chunks of the printed line that contain joins, with highlights."""
    slp_line = to_slp1(line)
    # map positions in the cleaned line (no spaces or avagraha) to the printed line
    pos = [i for i, c in enumerate(slp_line) if c not in sandhi.SKIP]
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
        base = next((v for v in sandhi._finals(lw) if v.endswith(fa)), lw)
        joined = base[:-len(fa)] + (res if j["across"] else sandhi._clean(res)) + to_slp1(right)[1:]
        jn = iast(joined)
        chunks[ci]["j"].append({"a": left, "b": right, "r": jn, "ad": dev(left), "bd": dev(right),
                                "rd": dev(jn), "k": j["key"], "x": int(j["across"])})
        t = types[j["key"]]
        t["n"] += 1
        if len(t["ex"]) < 3 and [left, right, jn] not in t["ex"]:
            t["ex"].append([left, right, jn, ref])
    return [chunks[k] for k in sorted(chunks)]


def main():
    types = defaultdict(lambda: {"n": 0, "ex": []})
    for slug, src in TEXTS:
        data = json.load(open(os.path.join(ROOT, "data/build", src), encoding="utf-8"))
        out, lines = {}, [0, 0, 0]
        for c in data["chapters"]:
            for v in c["verses"]:
                verse, partial = [], False
                for h in v["halves"]:
                    words, groups = [], []
                    for n, g in enumerate(h["groups"]):
                        for t in g["tokens"]:
                            words.append(t["form"])
                            groups.append(n)
                    if len(words) < 2:
                        continue
                    lines[0] += 1
                    parts, complete = trace(words, groups, h["text"])
                    lines[1 if complete else 2] += 1
                    partial |= not complete
                    for ws, gs, ln, js in parts:
                        verse += render(ws, gs, ln, js, types, f"{slug} {v['id']}")
                if verse or partial:
                    out[v["id"]] = {"c": verse, **({"p": 1} if partial else {})}
        json.dump(out, open(os.path.join(ROOT, f"web/data/{slug}-sandhi.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        print(f"{slug}: {lines[1]}/{lines[0]} half-lines fully traced, {lines[2]} partly")
    json.dump(dict(sorted(types.items(), key=lambda kv: -kv[1]["n"])),
              open(os.path.join(ROOT, "data/build/sandhi-types.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sutras = {}
    with open(os.path.join(DATA, "prakriya", "sutrapatha.tsv"), encoding="utf-8") as f:
        next(f)
        for line in f:
            code, text = line.rstrip("\n").split("\t")
            sutras[code] = iast(text)
    json.dump(sutras, open(os.path.join(ROOT, "web/data/sutras.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"{len(types)} junction types, {sum(t['n'] for t in types.values())} joins; {len(sutras)} sūtras")


if __name__ == "__main__":
    main()
