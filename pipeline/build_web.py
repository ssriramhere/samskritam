"""Compact the Gītā dataset for the website: adds Devanagari, drops fields
the page does not use, and splits derivations into their own file."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.lipi import Scheme, transliterate  # noqa: E402

from engine import meter  # noqa: E402


def dev(s: str) -> str:
    return transliterate(s, Scheme.Iast, Scheme.Devanagari)


def main():
    src = json.load(open(os.path.join(ROOT, "data/build/gita.json"), encoding="utf-8"))
    out_dir = os.path.join(ROOT, "web/data")
    os.makedirs(out_dir, exist_ok=True)
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
            scan = None
            if m.get("padas"):
                scan = [p["weights"] for p in m["padas"]]
            else:
                scan = ["".join(x[1] for x in meter.weights(l)) for l in v["lines"]]
            verses.append({"id": v["id"], "ce": v["ce"], "sp": v["speaker"],
                           "iast": v["lines"], "dev": [dev(l) for l in v["lines"]],
                           "m": [m["name"], m.get("variant")], "scan": scan,
                           "layer": v["layer"], "w": words,
                           **({"note": v["note"]} if v.get("note") else {})})
    stats = src["meta"]["stats"]
    meta = {"sources": src["meta"]["sources"],
            "agree": stats["agree"], "checkable": stats["agree"] + stats["form-known"] + stats["unknown"],
            "notChecked": stats["not-checked"]}
    json.dump({"meta": meta, "verses": verses},
              open(os.path.join(out_dir, "gita.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    der = json.load(open(os.path.join(ROOT, "data/build/derivations.json"), encoding="utf-8"))
    slim = {k: {"f": v["form"], "s": [[st["sutra"], st["text"], st["result"]] for st in v["steps"]]}
            for k, v in der.items()}
    json.dump(slim, open(os.path.join(out_dir, "derivations.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    for f in ("gita.json", "derivations.json"):
        print(f, os.path.getsize(os.path.join(out_dir, f)) // 1024, "KB")


if __name__ == "__main__":
    main()
