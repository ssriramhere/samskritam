"""Trace how the words of each Library verse join, using Vidyut's sandhi table.

    python pipeline/build_sandhi.py

Writes
  web/data/<slug>/<chapter>-sandhi.json   per verse: the printed chunks that contain joins,
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

TEXTS = [("gita", "gita.json"), ("meghaduta", "meghaduta.json"), ("mahabharata", "mahabharata.json"),
         ("kumarasambhava", "kumarasambhava.json"), ("rtusamhara", "rtusamhara.json"), ("ramayana", "ramayana.json"),
         ("kathopanisad", "kathopanisad.json"), ("astavakragita", "astavakragita.json")]


def iast(slp: str) -> str:
    return transliterate(slp, Scheme.Slp1, Scheme.Iast)


def dev(s: str) -> str:
    return transliterate(s, Scheme.Iast, Scheme.Devanagari)


trace, render = sandhi.trace, sandhi.render


def pick_examples(cands, k=3):
    """Three examples from different places, preferring the Meghadūta and the
    later Gītā: the first examples found all come from the battlefield verses of
    Gītā chapter 1, which made the citation prompts read like a list of war
    words (and some were blocked by a content filter)."""
    def rank(x):
        slug, vid = x[3].split()
        ch = int(vid.split(".")[0])
        return (0 if slug == "meghaduta" else 2 if ch == 1 else 1, len(x[2]))
    out, seen = [], set()
    for x in sorted(cands, key=rank):
        place = x[3].rsplit(".", 1)[0]
        if place in seen:
            continue
        out.append(x)
        seen.add(place)
        if len(out) == k:
            break
    for x in sorted(cands, key=rank):  # fewer than k distinct places
        if len(out) == k:
            break
        if x not in out:
            out.append(x)
    return out


def main():
    types = defaultdict(lambda: {"n": 0, "all": []})
    for slug, src in TEXTS:
        if not os.path.exists(os.path.join(ROOT, "data/build", src)):
            continue
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
        # one file per chapter, next to the chapter's verses (web/data/<slug>/<chapter>-sandhi.json)
        by_ch = defaultdict(dict)
        for vid, rec in out.items():
            by_ch[vid.rsplit(".", 1)[0]][vid] = rec
        tdir = os.path.join(ROOT, "web/data", slug)
        os.makedirs(tdir, exist_ok=True)
        for f in os.listdir(tdir):
            if f.endswith("-sandhi.json"):
                os.remove(os.path.join(tdir, f))
        for ch, recs in by_ch.items():
            json.dump(recs, open(os.path.join(tdir, f"{ch}-sandhi.json"), "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
        old = os.path.join(ROOT, f"web/data/{slug}-sandhi.json")
        if os.path.exists(old):
            os.remove(old)
        print(f"{slug}: {lines[1]}/{lines[0]} half-lines fully traced, {lines[2]} partly")
    for t in types.values():
        t["ex"] = pick_examples(t.pop("all"))
    json.dump(dict(sorted(types.items(), key=lambda kv: -kv[1]["n"])),
              open(os.path.join(ROOT, "data/build/sandhi-types.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sutras = {}
    with open(os.path.join(DATA, "prakriya", "sutrapatha.tsv"), encoding="utf-8") as f:
        next(f)
        for line in f:
            code, text = line.rstrip("\n").split("\t")
            # jihvāmūlīya and upadhmānīya come out of the transliteration as ≍
            sutras[code] = iast(text).replace("≍k", "ẖk").replace("≍p", "ḫp")
    json.dump(sutras, open(os.path.join(ROOT, "web/data/sutras.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print(f"{len(types)} junction types, {sum(t['n'] for t in types.values())} joins; {len(sutras)} sūtras")


if __name__ == "__main__":
    main()
