"""Reader for Digital Corpus of Sanskrit CoNLL-U files (CC BY 4.0)."""
from __future__ import annotations


def parse_feats(s: str) -> dict:
    if not s or s == "_":
        return {}
    return dict(kv.split("=", 1) for kv in s.split("|") if "=" in kv)


def read(path: str) -> list[dict]:
    """Return half-verse records: {counter, sub, text, groups}.
    Each group is one surface (sandhied) chunk with its analysed tokens."""
    out, cur, group_span = [], None, None
    for raw in open(path, encoding="utf-8"):
        # Some files spell vocalic ḷ (kḷp) with a stray halfwidth character.
        line = raw.rstrip("\n").replace("\uffb1", "ḷ")
        if line.startswith("# text = "):
            cur = {"text": line[9:], "groups": []}
            out.append(cur)
        elif line.startswith("# sent_counter"):
            cur["counter"] = int(line.split("=")[1])
        elif line.startswith("# sent_subcounter"):
            v = line.split("=")[1].strip()
            if v.isdigit():  # a few files leave it empty
                cur["sub"] = int(v)
        elif not line or line.startswith("#"):
            continue
        else:
            c = line.split("\t")
            if "-" in c[0]:
                a, b = map(int, c[0].split("-"))
                group_span = (a, b)
                cur["groups"].append({"surface": c[1], "tokens": []})
                continue
            idx = int(c[0])
            misc = parse_feats(c[9])
            tok = {"form": misc.get("Unsandhied", c[1]), "surface": c[1],
                   "lemma": c[2], "upos": c[3], "feats": parse_feats(c[5]),
                   "lemma_id": misc.get("LemmaId")}
            if group_span and group_span[0] <= idx <= group_span[1]:
                cur["groups"][-1]["tokens"].append(tok)
                if idx == group_span[1]:
                    group_span = None
            else:
                cur["groups"].append({"surface": c[1], "tokens": [tok]})
    return out
