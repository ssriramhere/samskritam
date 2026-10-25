"""Compact the built datasets for the website, one file per chapter.

For each text, in web/data/<slug>/:
  index.json              chapters, labels and search files
  <chapter>.json          verses and word analyses, with Devanagari added
  <chapter>-derivations.json   the derivations those verses use
  search[-<part>].json    per verse: id, first line, word forms, lemmas and
                          Devanagari forms, for search
                          (one file per parvan for texts with two levels)
Also web/data/texts.json, the list of texts the reader offers. Chapter ids are
"2" (Gītā chapter 2) or "3.50" (Mahābhārata, parvan 3, adhyāya 50); verse ids
add the verse number: "2.47", "3.50.1".
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

DERIV_SHARD = 200      # derivations per shard file
SHARD_ABOVE = 5000     # texts with more verses than this use shards

# slug, built dataset, built derivations, default verse, chapter label, how to name a verse
TEXTS = [
    ("gita", "gita.json", "derivations.json", "2.47", "Chapter", "id"),
    ("meghaduta", "meghaduta.json", "meghaduta-derivations.json", "1.1", None, "named"),
    ("mahabharata", "mahabharata.json", "mahabharata-derivations.json", "3.50.1", None, "id"),
    ("kumarasambhava", "kumarasambhava.json", "kumarasambhava-derivations.json", "1.1", None, "id"),
    ("rtusamhara", "rtusamhara.json", "rtusamhara-derivations.json", "1.1", None, "id"),
    ("ramayana", "ramayana.json", "ramayana-derivations.json", "1.2.14", None, "id"),
    ("kathopanisad", "kathopanisad.json", "kathopanisad-derivations.json", "1.1.1", None, "id"),
    ("astavakragita", "astavakragita.json", "astavakragita-derivations.json", "1.1", None, "id"),
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


def fold(x: str) -> str:
    """Lower case without diacritics, as the reader's search does."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", x) if not unicodedata.combining(c)).lower()


def chapter_of(vid: str) -> str:
    return vid.rsplit(".", 1)[0]


def dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def main():
    import shutil
    out_dir = os.path.join(ROOT, "web/data")
    index = []
    for slug, data_file, deriv_file, default, ch_label, ref_style in TEXTS:
        src_path = os.path.join(ROOT, "data/build", data_file)
        if not os.path.exists(src_path):
            print("skip", slug, "(not built)")
            continue
        src = json.load(open(src_path, encoding="utf-8"))
        verses = compact(src)
        st = src["meta"]["stats"]
        checkable = st["agree"] + st["form-known"] + st["unknown"]
        meta = src["meta"]
        levels = meta.get("levels") or [ch_label or meta.get("part_label") or "Part"]
        der = json.load(open(os.path.join(ROOT, "data/build", deriv_file), encoding="utf-8"))

        def dev_step(slp):
            return transliterate(slp.replace("\\", "").replace("^", ""), Scheme.Slp1, Scheme.Devanagari)
        slim = {k: {"f": v["form"], "s": [[s["sutra"], s["text"], s["result"], dev_step(s["result_slp"])]
                                          for s in v["steps"]]}
                for k, v in der.items()}

        # Large texts keep each derivation once, in shards by id, loaded when a word is
        # opened; per-chapter files repeat common derivations in every chapter.
        shard = DERIV_SHARD if len(verses) > SHARD_ABOVE else None
        tdir = os.path.join(out_dir, slug)
        import shutil
        if os.path.isdir(os.path.join(tdir, "d")):
            shutil.rmtree(os.path.join(tdir, "d"))
        if os.path.isdir(tdir):  # rebuild from scratch, but keep files made by other steps
            for f in os.listdir(tdir):
                if not f.endswith(("-translations.json", "-sandhi.json", "-glosses.json")):
                    os.remove(os.path.join(tdir, f))
        os.makedirs(tdir, exist_ok=True)
        by_ch = {}
        for v in verses:
            by_ch.setdefault(chapter_of(v["id"]), []).append(v)
        names = {str(c["ch"]): c.get("name") for c in src["chapters"]}
        chapters, search = [], {}
        # Large texts also store each word's grammar labels once, in index.json,
        # and refer to them by number ("lb"); the page and translate.py expand them.
        label_ids = {}
        for ch, vs in by_ch.items():
            if shard:
                vs = [{**v, "w": [{**{k: x for k, x in w.items() if k not in ("sa", "en")},
                                   "lb": label_ids.setdefault((w["sa"], w["en"]), len(label_ids))}
                                  for w in v["w"]]} for v in vs]
            dump({"verses": vs}, os.path.join(tdir, f"{ch}.json"))
            if not shard:
                used = {w["x"] for v in vs for w in v["w"] if w.get("x")}
                dump({k: slim[k] for k in sorted(used) if k in slim}, os.path.join(tdir, f"{ch}-derivations.json"))
            label = ch.split(".")[-1] if len(levels) == 2 else (names.get(ch) or ch)
            chapters.append({"id": ch, "label": label, "n": len(vs)})
            part = ch.split(".")[0] if len(levels) == 2 else ""
            for v in vs:
                search.setdefault(part, []).append([
                    v["id"], v["dev"][0] if v["dev"] else "",
                    " ".join(w["f"] for w in v["w"]), " ".join(w["l"] for w in v["w"]),
                    " ".join(w["d"] for w in v["w"])])
        files = []
        for part, rows in search.items():
            name = f"search-{part}.json" if part else "search.json"
            dump(rows, os.path.join(tdir, name))
            files.append({"file": name, "part": part})
        tindex = {"slug": slug, "levels": levels, "chapters": chapters, "search": files}
        if shard:
            tindex["labels"] = [list(k) for k in label_ids]
            os.makedirs(os.path.join(tdir, "d"), exist_ok=True)
            shards = {}
            for k in slim:
                shards.setdefault(int(k[1:]) // shard, {})[k] = slim[k]
            for n, part in shards.items():
                dump(part, os.path.join(tdir, "d", f"{n}.json"))
            tindex["dshard"] = shard
        if len(levels) == 2:
            tindex["parts"] = {p: meta["parvans"][p] for p in sorted({c["id"].split(".")[0] for c in chapters}, key=int)}
        dump(tindex, os.path.join(tdir, "index.json"))

        # One-off move of translations from the old one-file layout.
        old_tr = os.path.join(out_dir, f"{slug}-translations.json")
        if os.path.exists(old_tr):
            tr = json.load(open(old_tr, encoding="utf-8"))
            for ch in by_ch:
                part = {k: v for k, v in tr["t"].items() if chapter_of(k) == ch}
                if part:
                    dump({"model": tr["model"], "t": part}, os.path.join(tdir, f"{ch}-translations.json"))
            os.remove(old_tr)
        for old in (f"{slug}.json", f"{slug}-derivations.json"):
            if os.path.exists(os.path.join(out_dir, old)):
                os.remove(os.path.join(out_dir, old))

        index.append({
            "slug": slug, "title": meta["title"], "author": meta.get("author"),
            "levels": levels, "refStyle": ref_style, "default": default, "note": meta.get("note"),
            "verses": len(verses), "agree": st["agree"], "checkable": checkable,
            "notChecked": st["not-checked"], "derivations": len(slim)})
        size = sum(os.path.getsize(os.path.join(tdir, f)) for f in os.listdir(tdir))
        print(f"{slug}: {len(verses)} verses in {len(chapters)} chapter files, {size // 1024} KB")
    dump(index, os.path.join(out_dir, "texts.json"))
    shutil.copyfile(os.path.join(ROOT, "bench/data/v0.jsonl"), os.path.join(out_dir, "bench-v0.jsonl"))


if __name__ == "__main__":
    main()
