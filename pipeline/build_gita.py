"""Build the verified Bhagavad Gītā dataset.

Sources
  - Word analyses: Digital Corpus of Sanskrit (O. Hellwig), CC BY 4.0.
    Follows the critical-edition text; numbering is mapped to the common
    (vulgate) numbering, which differs only in chapter 13.
  - Verification, derivations, meter weights: Vidyut (Ambuda project).

Output: data/build/gita.json and data/build/derivations.json
"""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import dcs, labels, meter, verify  # noqa: E402

VULGATE_COUNTS = [47, 72, 43, 42, 29, 47, 30, 28, 34, 42, 55, 20, 35, 27, 20,
                  24, 28, 78]


def vulgate_number(ch: int, ce: int) -> int:
    # The critical edition omits the vulgate's 13.1 (arjuna uvāca, prakṛtiṃ
    # puruṣaṃ caiva ...), so CE 13.n is vulgate 13.(n+1).
    return ce + 1 if ch == 13 else ce


# DCS carries these verses in a separate treebank layer without verse
# numbers, with the text already split into words. Map them by opening words
# to (verse, position); position orders halves within the verse.
UNNUMBERED = {
    1: [("dharma kṣetre", 1, 1)],
    2: [("tam tathā", 1, 1), ("kutas tvā", 2, 1), ("klaibyam", 3, 1),
        ("na etat tvayi", 3, 2), ("kṣudram", 3, 3), ("katham bhīṣmam", 4, 1),
        ("evam uktvā hṛṣīkeśam", 9, 1), ("tam uvāca", 10, 1),
        ("gatāsūn", 11, 3), ("na jāyate", 20, 1), ("ajaḥ nityaḥ", 20, 2),
        ("katham sa puruṣaḥ", 21, 2), ("vāsāṃsi", 22, 1),
        ("na enam chindanti", 23, 0.1), ("na enam dahati", 23, 0.2),
        ("prajahāti", 55, 1)],
}


def place_unnumbered(ch: int, text: str):
    for prefix, verse, pos in UNNUMBERED.get(ch, []):
        if text.startswith(prefix):
            return verse, pos
    return None


def speaker_of(half: dict):
    toks = [t for g in half["groups"] for t in g["tokens"]]
    if toks and toks[-1]["lemma"] == "vac" and len(toks) <= 4:
        return half["text"]
    return None


_TEXT = None


def recited_lines(vid: str) -> list[str]:
    """Sandhied verse text (public domain) as half-verse lines in IAST."""
    global _TEXT
    if _TEXT is None:
        with open(os.path.join(ROOT, "data/sources/gita-sanskrit-text.json"),
                  encoding="utf-8") as f:
            _TEXT = json.load(f)
    from vidyut.lipi import Scheme, transliterate
    lines = [transliterate(x, Scheme.Devanagari, Scheme.Iast) for x in _TEXT[vid]]
    if len(lines) == 4:  # triṣṭubh printed one pāda per line
        lines = [lines[0] + " " + lines[1], lines[2] + " " + lines[3]]
    return lines


def deriv_key(view: dict) -> str:
    return str(view["raw"])


def main():
    chapters, derivations, stats = [], {}, Counter()
    for path in sorted(glob.glob(os.path.join(ROOT, "data/sources/dcs-gita/*.conllu"))):
        ch = int(os.path.basename(path)[6:8])
        verses = defaultdict(lambda: {"halves": [], "speaker": None, "layer": "dcs"})
        pending_speaker = None
        for half in dcs.read(path):
            spk = speaker_of(half)
            if "counter" in half:
                counter, pos = half["counter"], half.get("sub", 1)
            else:
                placed = place_unnumbered(ch, half["text"])
                if spk:
                    pending_speaker = spk  # applies to the next placed verse
                    continue
                if not placed:
                    print("WARN unplaced:", ch, half["text"][:60])
                    continue
                counter, pos = placed
                verses[counter]["layer"] = "dcs-treebank"
            v = verses[counter]
            if spk:
                v["speaker"] = spk
                continue
            if pending_speaker and not v["speaker"]:
                v["speaker"] = pending_speaker
            pending_speaker = None
            groups = []
            for g in half["groups"]:
                toks = []
                for t in g["tokens"]:
                    r = verify.check(t)
                    stats[r["status"]] += 1
                    tok = {"form": t["form"], "lemma": t["lemma"], "upos": t["upos"],
                           "feats": t["feats"],
                           "label": labels.describe(t["upos"], t["feats"]),
                           "status": r["status"]}
                    if r["status"] == "form-known":
                        tok["engine_alternatives"] = r["alternatives"]
                    if r["status"] == "agree":
                        ev = r["entry"]
                        if ev["kind"] == "tinanta" or ev.get("krdanta"):
                            k = deriv_key(ev)
                            if k not in derivations:
                                d = verify.derivation(ev)
                                derivations[k] = d[0] if d and "steps" in d[0] else None
                            if derivations[k]:
                                tok["derivation"] = k
                    toks.append(tok)
                groups.append({"surface": g["surface"], "tokens": toks})
            v["halves"].append({"pos": pos, "text": half["text"], "groups": groups})

        out = []
        for ce in sorted(verses):
            v = verses[ce]
            if not v["halves"]:
                continue
            v["halves"].sort(key=lambda h: h["pos"])
            vid = f"{ch}.{vulgate_number(ch, ce)}"
            if v["layer"] == "dcs":
                lines = [h["text"] for h in v["halves"]]
            else:  # treebank text is pre-split; display the recited text
                lines = recited_lines(vid)
            m = meter.identify(lines)
            stats["meter:" + m["name"]] += 1
            out.append({"id": vid, "ch": ch, "v": vulgate_number(ch, ce),
                        "ce": ce, "speaker": v["speaker"], "lines": lines,
                        "halves": v["halves"], "meter": m, "layer": v["layer"]})
        if ch == 13:  # vulgate 13.1 is absent from the critical edition
            lines = recited_lines("13.1")
            out.insert(0, {"id": "13.1", "ch": 13, "v": 1, "ce": None,
                           "speaker": "arjuna uvāca", "lines": lines,
                           "halves": [], "meter": meter.identify(lines),
                           "layer": "text-only",
                           "note": "Not in the critical edition; no word analysis yet."})
        present = {x["v"] for x in out}
        missing = [n for n in range(1, VULGATE_COUNTS[ch - 1] + 1) if n not in present]
        chapters.append({"ch": ch, "verses": out, "missing": missing})

    # Re-key derivations to short ids to keep the JSON small.
    ids = {k: f"d{i}" for i, k in enumerate(k for k, v in derivations.items() if v)}
    for c in chapters:
        for v in c["verses"]:
            for h in v["halves"]:
                for g in h["groups"]:
                    for t in g["tokens"]:
                        if "derivation" in t:
                            t["derivation"] = ids[t["derivation"]]
    deriv_out = {ids[k]: v for k, v in derivations.items() if v}

    os.makedirs(os.path.join(ROOT, "data/build"), exist_ok=True)
    meta = {"title": "Bhagavad Gītā", "sources": {
        "analysis": "Digital Corpus of Sanskrit, Oliver Hellwig, CC BY 4.0, "
                    "github.com/OliverHellwig/sanskrit",
        "engine": "Vidyut 0.4.0 (Ambuda), github.com/ambuda-org/vidyut"},
        "stats": dict(stats)}
    with open(os.path.join(ROOT, "data/build/gita.json"), "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "chapters": chapters}, f, ensure_ascii=False)
    with open(os.path.join(ROOT, "data/build/derivations.json"), "w", encoding="utf-8") as f:
        json.dump(deriv_out, f, ensure_ascii=False)
    print(json.dumps(meta["stats"], ensure_ascii=False, indent=1))
    print("verses:", sum(len(c["verses"]) for c in chapters),
          "missing:", {c["ch"]: c["missing"] for c in chapters if c["missing"]},
          "derivations:", len(deriv_out))


if __name__ == "__main__":
    main()
