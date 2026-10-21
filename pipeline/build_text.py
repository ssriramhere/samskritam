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
    # The critical edition of the Mahābhārata, one CoNLL-U file per adhyāya
    # (data/sources/dcs-mahabharata/mbh-<parvan>-<adhyāya>.conllu). For now
    # the Nalopākhyāna, Āraṇyakaparvan 3.50-78; add files to grow it.
    "mahabharata": {
        "title": "Mahābhārata",
        "author": "Vyāsa (critical edition)",
        "source_dir": "data/sources/dcs-mahabharata",
        "levels": ["Parvan", "Adhyāya"],
        "parvans": {1: "Ādiparvan", 2: "Sabhāparvan", 3: "Āraṇyakaparvan", 4: "Virāṭaparvan",
                    5: "Udyogaparvan", 6: "Bhīṣmaparvan", 7: "Droṇaparvan", 8: "Karṇaparvan",
                    9: "Śalyaparvan", 10: "Sauptikaparvan", 11: "Strīparvan", 12: "Śāntiparvan",
                    13: "Anuśāsanaparvan", 14: "Āśvamedhikaparvan", 15: "Āśramavāsikaparvan",
                    16: "Mausalaparvan", 17: "Mahāprasthānikaparvan", 18: "Svargārohaṇaparvan"},
        "speakers": True,
        "prose": False,
        "note": "So far the Nalopākhyāna (Āraṇyakaparvan, adhyāyas 50–78), with more of the "
                "epic to follow. Numbering follows the critical edition.",
    },
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


def speaker_of(half: dict):
    """A short line like "bṛhadaśva uvāca" that introduces the speaker."""
    toks = [t for g in half["groups"] for t in g["tokens"]]
    if toks and toks[-1]["lemma"] == "vac" and len(toks) <= 4:
        return half["text"]
    return None


def chapter_ids(cfg, files):
    """Chapter id for each file: "1", "2", ... or, for texts with two levels
    (parvan and adhyāya), "3.50" from mbh-3-050.conllu."""
    if len(cfg.get("levels", [])) == 2:
        import re
        return [".".join(str(int(x)) for x in re.findall(r"(\d+)-(\d+)\.conllu$", f)[0]) for f in files]
    return [str(i) for i in range(1, len(files) + 1)]


def build(slug: str):
    cfg = TEXTS[slug]
    files = sorted(glob.glob(os.path.join(ROOT, cfg["source_dir"], "*.conllu")))
    ids = chapter_ids(cfg, files)
    order = sorted(range(len(files)), key=lambda i: [int(x) for x in ids[i].split(".")])
    chapters, derivations, stats = [], {}, Counter()
    for fi in order:
        path, ch_id = files[fi], ids[fi]
        verses, speakers, pending = defaultdict(list), {}, None
        for half in dcs.read(path):
            if "counter" not in half:
                print("WARN unnumbered:", ch_id, half["text"][:60])
                continue
            if cfg.get("speakers") and speaker_of(half):
                speakers.setdefault(half["counter"], half["text"])
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
            out.append({"id": f"{ch_id}.{n}", "ch": ch_id, "v": n, "ce": None,
                        "speaker": speakers.get(n), "lines": lines, "halves": halves,
                        "meter": m, "layer": "dcs"})
        if len(cfg.get("levels", [])) == 2:
            p, a = ch_id.split(".")
            name = f"{cfg['parvans'][int(p)]} {a}"
        else:
            name = cfg["parts"][int(ch_id) - 1]
        chapters.append({"ch": ch_id, "name": name, "verses": out, "missing": []})

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
            "part_label": cfg.get("part_label"), "levels": cfg.get("levels"),
            "parvans": {str(k): v for k, v in cfg.get("parvans", {}).items()}, "note": cfg["note"],
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
