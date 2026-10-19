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
            for h in v["halves"]:
                for g in h["groups"]:
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
                        words.append(w)
            m = v["meter"]
            if m.get("padas"):
                scan = [p["weights"] for p in m["padas"]]
            elif m["name"] == "prose":
                scan = []
            else:
                scan = ["".join(x[1] for x in meter.weights(l)) for l in v["lines"]]
            verses.append({"id": v["id"], "ce": v["ce"], "sp": v["speaker"],
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
    old = os.path.join(out_dir, "derivations.json")
    if os.path.exists(old):
        os.remove(old)  # renamed to gita-derivations.json


if __name__ == "__main__":
    main()
