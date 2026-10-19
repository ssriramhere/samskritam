"""Compact the built datasets for the website.

For each text: web/data/<slug>.json (verses and word analyses, with
Devanagari added) and web/data/<slug>-derivations.json. Also writes
web/data/texts.json, the list of texts the reader offers.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.lipi import Scheme, transliterate  # noqa: E402

from engine import meter  # noqa: E402
from engine.verify import to_slp1  # noqa: E402

VOWELS = set("aAiIuUfFxXeEoO")


def syllables(token: str) -> int:
    return sum(c in VOWELS for c in to_slp1(token))


def pada_breaks(lines: list, n: int):
    """Token index after which each pāda ends, per line, when every pāda
    boundary in the verse falls between words; otherwise None."""
    out = []
    for line in lines:
        cum, breaks = 0, []
        toks = line.split()
        for i, t in enumerate(toks[:-1]):
            cum += syllables(t)
            if cum % n == 0 and cum:
                breaks.append(i)
        if len(breaks) != max(1, round(sum(map(syllables, toks)) / n)) - 1:
            return None
        out.append(breaks)
    return out

# slug, built dataset, built derivations, default verse, chapter label
TEXTS = [
    ("gita", "gita.json", "derivations.json", "2.47", "Chapter"),
    ("meghaduta", "meghaduta.json", "meghaduta-derivations.json", "1.1", None),
]


def dev(s: str) -> str:
    return transliterate(s, Scheme.Iast, Scheme.Devanagari)


def compact(src: dict) -> list:
    verses = []
    for c in src["chapters"]:
        for v in c["verses"]:
            words = []
            lines_tokens = [line.split() for line in v["lines"]]
            aligned = v["layer"] == "dcs" and len(v["halves"]) == len(v["lines"])
            for li, h in enumerate(v["halves"]):
                toks, ti = (lines_tokens[li] if aligned else []), 0
                for g in h["groups"]:
                    # Map the analysed group to its word in the printed line.
                    key = None
                    if aligned:
                        j = ti
                        while j < len(toks) and toks[j] != g["surface"]:
                            j += 1
                        if j < len(toks):
                            key, ti = f"{li}.{j}", j + 1
                    for t in g["tokens"]:
                        w = {"f": t["form"], "d": dev(t["form"]), "l": t["lemma"],
                             "sa": t["label"]["sa"], "en": t["label"]["en"],
                             "s": t["status"]}
                        if t.get("derivation"):
                            w["x"] = t["derivation"]
                        if t.get("engine_alternatives"):
                            w["alt"] = t["engine_alternatives"][:4]
                        if len(g["tokens"]) > 1:
                            w["g"] = g["surface"]
                        if key:
                            w["k"] = key
                        words.append(w)
            m = v["meter"]
            if m.get("padas"):
                scan = [p["weights"] for p in m["padas"]]
            elif m["name"] == "prose":
                scan = []
            else:
                scan = ["".join(x[1] for x in meter.weights(l)) for l in v["lines"]]
            n = len(m["padas"][0]["syllables"]) if m.get("padas") else None
            extra = {"lt": [[[t, dev(t)] for t in toks] for toks in lines_tokens]}
            pb = pada_breaks(v["lines"], n) if n else None
            if pb:
                extra["pb"] = pb
            verses.append({"id": v["id"], "ce": v["ce"], "sp": v["speaker"], **extra,
                           "iast": v["lines"], "dev": [dev(l) for l in v["lines"]],
                           "m": [m["name"], m.get("variant")], "scan": scan,
                           "layer": v["layer"], "w": words,
                           **({"note": v["note"]} if v.get("note") else {})})
    return verses


def main():
    out_dir = os.path.join(ROOT, "web/data")
    os.makedirs(out_dir, exist_ok=True)
    index = []
    for slug, data_file, deriv_file, default, ch_label in TEXTS:
        src = json.load(open(os.path.join(ROOT, "data/build", data_file), encoding="utf-8"))
        verses = compact(src)
        st = src["meta"]["stats"]
        checkable = st["agree"] + st["form-known"] + st["unknown"]
        meta = src["meta"]
        der = json.load(open(os.path.join(ROOT, "data/build", deriv_file), encoding="utf-8"))
        slim = {k: {"f": v["form"], "s": [[s["sutra"], s["text"], s["result"]] for s in v["steps"]]}
                for k, v in der.items()}
        json.dump({"verses": verses},
                  open(os.path.join(out_dir, f"{slug}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        json.dump(slim, open(os.path.join(out_dir, f"{slug}-derivations.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        index.append({
            "slug": slug, "title": meta["title"], "author": meta.get("author"),
            "partLabel": ch_label or meta.get("part_label", "Part"),
            "parts": [c.get("name") or str(c["ch"]) for c in src["chapters"]],
            "default": default, "note": meta.get("note"),
            "verses": len(verses), "agree": st["agree"], "checkable": checkable,
            "notChecked": st["not-checked"], "derivations": len(slim)})
        print(slug, len(verses), "verses,",
              os.path.getsize(os.path.join(out_dir, f"{slug}.json")) // 1024, "KB")
    json.dump(index, open(os.path.join(out_dir, "texts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    import shutil
    shutil.copyfile(os.path.join(ROOT, "bench/data/v0.jsonl"), os.path.join(out_dir, "bench-v0.jsonl"))
    old = os.path.join(out_dir, "derivations.json")
    if os.path.exists(old):
        os.remove(old)  # renamed to gita-derivations.json


if __name__ == "__main__":
    main()
