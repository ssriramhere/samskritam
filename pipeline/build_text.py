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
    # (data/sources/dcs-mahabharata/mbh-<parvan>-<adhyāya>.conllu, made from the DCS
    # files by pipeline/fetch_mahabharata.py; not in git). All eighteen parvans are
    # built; "publish" picks what goes on the site: whole parvans ("1") or a run
    # of adhyāyas ("3.50-78").
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
        "publish": ["1", "3.50-78"],
        "critical_edition": True,
        "note": "The critical edition, added one parvan at a time. So far: {parts}. "
                "Numbering follows the critical edition, as annotated in the Digital Corpus of Sanskrit.",
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
    "kumarasambhava": {
        "title": "Kumārasaṃbhava",
        "author": "Kālidāsa",
        "source_dir": "data/sources/dcs-kumarasambhava",
        "levels": ["Sarga"],
        "prose": False,
        "note": "Sargas 1–8, the part of the poem generally held to be Kālidāsa's. "
                "Verse numbers follow the Digital Corpus of Sanskrit.",
    },
    "rtusamhara": {
        "title": "Ṛtusaṃhāra",
        "author": "attributed to Kālidāsa",
        "source_dir": "data/sources/dcs-rtusamhara",
        "levels": ["Sarga"],
        "parts": ["1 · Grīṣma (summer)", "2 · Varṣā (rains)", "3 · Śarad (autumn)",
                  "4 · Hemanta (early winter)", "5 · Śiśira (late winter)", "6 · Vasanta (spring)"],
        "prose": False,
        "note": "One sarga for each of the six seasons. Verse numbers follow the Digital Corpus of Sanskrit.",
    },
    "ramayana": {
        "title": "Rāmāyaṇa",
        "author": "Vālmīki",
        "source_dir": "data/sources/dcs-ramayana",
        "levels": ["Kāṇḍa", "Sarga"],
        "parvans": {1: "Bālakāṇḍa", 2: "Ayodhyākāṇḍa", 3: "Araṇyakāṇḍa", 4: "Kiṣkindhākāṇḍa",
                    5: "Sundarakāṇḍa", 6: "Yuddhakāṇḍa", 7: "Uttarakāṇḍa"},
        "speakers": True,
        "prose": False,
        "note": "The critical edition, added one kāṇḍa at a time. So far: {parts}. "
                "Numbering follows the critical edition, as annotated in the Digital Corpus of Sanskrit.",
    },
    "kathopanisad": {
        "title": "Kaṭhopaniṣad",
        "author": None,
        "source_dir": "data/sources/dcs-kathopanisad",
        "levels": ["Adhyāya", "Vallī"],
        "parvans": {1: "Adhyāya 1", 2: "Adhyāya 2"},
        "speakers": True,
        "prose": False,
        "note": "Cited as adhyāya.vallī.verse. Vedic forms are common, and Pāṇini's rules as "
                "implemented cover them less fully than classical Sanskrit.",
    },
    "astavakragita": {
        "title": "Aṣṭāvakragītā",
        "author": None,
        "source_dir": "data/sources/dcs-astavakragita",
        "levels": ["Chapter"],
        "speakers": True,
        "prose": False,
        "note": "Janaka asks, Aṣṭāvakra teaches. Verse numbers follow the Digital Corpus of Sanskrit.",
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


# The DCS's Mahābhārata files also carry passages of the vulgate, numbered with the
# critical-edition verse they follow. Where the critical edition's own e-text is at
# hand (data/ce/MBh01.txt ..., BORI, Unicode Roman, one line per two pādas, e.g.
# "01001002a samāsīnān ..."), keep only corpus lines that are in it, number them as
# it does, and show any edition line the corpus lacks without word analysis.
CE_DIR = os.path.join(ROOT, "data/ce")
_ce_cache = {}


def _norm(s: str) -> str:
    import re
    s = s.lower().replace("ṁ", "m").replace("ṃ", "m").replace("’", "").replace("'", "")
    s = re.sub(r"[^a-zāīūṛṝḷḹṅñṭḍṇśṣḥ]", "", s)
    return s.replace("ttr", "tr")


def critical_edition(cfg, ch_id):
    """The edition's lines for one adhyāya: [(verse, pāda letter, text)], or None."""
    import re
    if not cfg.get("critical_edition") or "." not in ch_id:
        return None
    p, a = (int(x) for x in ch_id.split("."))
    if p not in _ce_cache:
        path = os.path.join(CE_DIR, f"MBh{p:02d}.txt")
        if not os.path.exists(path):
            _ce_cache[p] = None
        else:
            by = defaultdict(list)
            for line in open(path, encoding="utf-8"):
                m = re.match(r"(\d\d)(\d\d\d)(\d\d\d)(.) ?(.*)", line.rstrip("\n"))
                if m and not line.startswith("%"):
                    by[int(m[2])].append((int(m[3]), m[4], m[5].strip().replace("ṁ", "ṃ").replace("’", "'")))
            _ce_cache[p] = by
    return None if _ce_cache[p] is None else _ce_cache[p].get(a, [])


def align_to_ce(halves, ce_lines, stats, derivations, ch_id):
    import difflib
    text_lines = [(i, l) for i, l in enumerate(ce_lines) if l[1] != " "]
    by_norm = defaultdict(list)
    for i, l in text_lines:
        by_norm[_norm(l[2])].append(i)
    match, used = {}, set()
    for h in halves:
        if "counter" not in h or speaker_of(h):
            continue
        n = _norm(h["text"])
        hit = next((i for i in by_norm.get(n, []) if i not in used), None)
        if hit is None:
            best, hit = 0.0, None
            for i, l in text_lines:
                nn = _norm(l[2])
                if i in used or abs(len(n) - len(nn)) > 12:
                    continue
                r = difflib.SequenceMatcher(None, n, nn, autojunk=False).ratio()
                if r > best:
                    best, hit = r, i
            if best < 0.9:
                hit = None
        if hit is None:
            stats["ce:dropped"] += 1
            continue
        used.add(hit)
        match[hit] = h
    verses, speakers = defaultdict(list), {}
    for i, (v, q, text) in enumerate(ce_lines):
        if q == " ":
            speakers.setdefault(v, text)
            continue
        h = match.get(i)
        if h is not None:
            stats["ce:kept"] += 1
            verses[v].append({"pos": i, "text": h["text"], "ce": f"{v}{q.lower()}", "prose": q.isupper(),
                              "groups": analyse(h, stats, derivations)})
        else:
            stats["ce:not-in-corpus"] += 1
            verses[v].append({"pos": i, "text": text, "ce": f"{v}{q.lower()}", "prose": q.isupper(), "groups": [],
                              "unanalysed": True})
    return verses, speakers


def build(slug: str):
    cfg = TEXTS[slug]
    files = sorted(glob.glob(os.path.join(ROOT, cfg["source_dir"], "*.conllu")))
    ids = chapter_ids(cfg, files)
    order = sorted(range(len(files)), key=lambda i: [int(x) for x in ids[i].split(".")])
    chapters, derivations, stats = [], {}, Counter()
    for fi in order:
        path, ch_id = files[fi], ids[fi]
        verses, speakers, pending = defaultdict(list), {}, None
        ce_lines = critical_edition(cfg, ch_id)
        if ce_lines is not None:
            verses, speakers = align_to_ce(dcs.read(path), ce_lines, stats, derivations, ch_id)
        for half in (dcs.read(path) if ce_lines is None else []):
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
                 if cfg["prose"] or all(h.get("prose") for h in halves) else meter.identify(lines))
            stats["meter:" + m["name"] + (" / " + m["variant"] if m.get("variant") else "")] += 1
            missing = [h["ce"][-1] if h.get("prose") else h["ce"][-1] + chr(ord(h["ce"][-1]) + 1)
                       for h in halves if h.get("unanalysed")]
            note = None
            if missing:  # cited by pāda letters (verse) or line letter (prose)
                note = ("Not in the Digital Corpus of Sanskrit, so shown from the critical edition "
                        "without word analysis: " + ("line " if all(h.get("prose") for h in halves) else "pādas ")
                        + ", ".join(missing) + ".")
            out.append({"id": f"{ch_id}.{n}", "ch": ch_id, "v": n, "ce": None, **({"note": note} if note else {}),
                        "speaker": speakers.get(n), "lines": lines, "halves": halves,
                        "meter": m, "layer": "dcs"})
        if len(cfg.get("levels", [])) == 2:
            p, a = ch_id.split(".")
            name = f"{cfg['parvans'][int(p)]} {a}"
        elif cfg.get("parts"):
            name = cfg["parts"][int(ch_id) - 1]
        else:
            name = ch_id
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
            "parvans": {str(k): v for k, v in cfg.get("parvans", {}).items()},
            "publish": cfg.get("publish"), "note_template": cfg["note"],
            "note": cfg["note"].replace("{parts}", ", ".join(
                cfg["parvans"][p] for p in sorted({int(c["ch"].split(".")[0]) for c in chapters}))
                if "{parts}" in (cfg["note"] or "") else cfg["note"]),
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
