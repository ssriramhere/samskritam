"""Build a verified dataset for any text in the Digital Corpus of Sanskrit.

Each text is described by an entry in TEXTS: where its CoNLL-U files are,
what its parts are called, and how its verses are numbered. The Gītā keeps
its own builder (build_gita.py) because of its numbering fixes.

    python pipeline/build_text.py meghaduta

Output: data/build/<slug>.json and data/build/<slug>-derivations.json,
in the same shape as gita.json.
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import dcs, labels, meter, verify  # noqa: E402

TEXTS = {
    "meghaduta": {
        "title": "Meghadūta",
        "author": "Kālidāsa",
        "source_dir": "data/sources/dcs-meghaduta",
        "part_label": "Part",
        "parts": ["Pūrvamegha", "Uttaramegha"],
        "prose": False,
        "note": "Verse numbers follow the Digital Corpus of Sanskrit, counted "
                "separately in each part.",
    },
}


def analyse(half, stats, derivations):
    groups = []
    for g in half["groups"]:
        toks = []
        for t in g["tokens"]:
            r = verify.check(t)
            stats[r["status"]] += 1
            tok = {"form": t["form"], "lemma": t["lemma"], "upos": t["upos"],
                   "feats": t["feats"], "label": labels.describe(t["upos"], t["feats"]),
                   "status": r["status"]}
            if r["status"] == "form-known":
                tok["engine_alternatives"] = r["alternatives"]
            if r["status"] == "agree":
                ev = r["entry"]
                verbal = t["upos"] == "VERB" and (ev["kind"] == "tinanta" or ev.get("krdanta"))
                nominal = (t["upos"] in ("NOUN", "ADJ", "PRON", "NUM") and ev["kind"] == "subanta"
                           and not ev.get("krdanta") and not ev.get("avyaya"))
                if verbal or nominal:
                    k = str(ev["raw"]) + "|" + verify.canon(verify.to_slp1(t["form"]))
                    if k not in derivations:
                        d = verify.derivation(ev, t["form"])
                        derivations[k] = d[0] if d and "steps" in d[0] else None
                    if derivations[k]:
                        tok["derivation"] = k
            toks.append(tok)
        groups.append({"surface": g["surface"], "tokens": toks})
    return groups


def build(slug: str):
    cfg = TEXTS[slug]
    files = sorted(glob.glob(os.path.join(ROOT, cfg["source_dir"], "*.conllu")))
    chapters, derivations, stats = [], {}, Counter()
    for part_no, path in enumerate(files, 1):
        verses = defaultdict(list)
        for half in dcs.read(path):
            if "counter" not in half:
                print("WARN unnumbered:", part_no, half["text"][:60])
                continue
            verses[half["counter"]].append(
                {"pos": half.get("sub", 1), "text": half["text"],
                 "groups": analyse(half, stats, derivations)})
        out = []
        for n in sorted(verses):
            halves = sorted(verses[n], key=lambda h: h["pos"])
            lines = [h["text"] for h in halves]
            m = ({"name": "prose", "variant": None, "check": "none"}
                 if cfg["prose"] else meter.identify(lines))
            stats["meter:" + m["name"] + (" / " + m["variant"] if m.get("variant") else "")] += 1
            out.append({"id": f"{part_no}.{n}", "ch": part_no, "v": n, "ce": None,
                        "speaker": None, "lines": lines, "halves": halves,
                        "meter": m, "layer": "dcs"})
        chapters.append({"ch": part_no, "name": cfg["parts"][part_no - 1],
                         "verses": out, "missing": []})

    ids = {k: f"d{i}" for i, k in enumerate(k for k, v in derivations.items() if v)}
    for c in chapters:
        for v in c["verses"]:
            for h in v["halves"]:
                for g in h["groups"]:
                    for t in g["tokens"]:
                        if "derivation" in t:
                            t["derivation"] = ids[t["derivation"]]
    deriv_out = {ids[k]: v for k, v in derivations.items() if v}
    meta = {"title": cfg["title"], "author": cfg["author"],
            "part_label": cfg["part_label"], "note": cfg["note"],
            "sources": {"analysis": "Digital Corpus of Sanskrit, Oliver Hellwig, "
                                    "CC BY 4.0, github.com/OliverHellwig/sanskrit",
                        "engine": "Vidyut 0.4.0 (Ambuda), github.com/ambuda-org/vidyut"},
            "stats": dict(stats)}
    os.makedirs(os.path.join(ROOT, "data/build"), exist_ok=True)
    with open(os.path.join(ROOT, f"data/build/{slug}.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "chapters": chapters}, f, ensure_ascii=False)
    with open(os.path.join(ROOT, f"data/build/{slug}-derivations.json"), "w", encoding="utf-8") as f:
        json.dump(deriv_out, f, ensure_ascii=False)
    checkable = stats["agree"] + stats["form-known"] + stats["unknown"]
    print(json.dumps(dict(stats), ensure_ascii=False, indent=1))
    print(f"{cfg['title']}: {sum(len(c['verses']) for c in chapters)} verses, "
          f"agreement {stats['agree'] / checkable:.1%} of {checkable}, "
          f"{len(deriv_out)} derivations")


if __name__ == "__main__":
    for slug in sys.argv[1:] or TEXTS:
        build(slug)
