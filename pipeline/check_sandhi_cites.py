"""Check the AI's sandhi citations against the textbook rule family of each join.

Each junction type (final|initial|result, SLP1) is classified into a family,
and each family names the sūtras any correct derivation must cite. A citation
agrees when it cites all of them (it may cite more). Families are the standard
external-sandhi rules of the Aṣṭādhyāyī; where Pāṇini allows options, only the
rule that yields the printed form is required.

    python pipeline/check_sandhi_cites.py [web/data/sandhi-rules.json]
"""
import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOWELS = set("aAiIuUfFxXeEoO")
VOICED = set("gGjJqQdDbBNYRnmyrlvh")
SAVARNA = {"a": "a", "A": "a", "i": "i", "I": "i", "u": "u", "U": "u", "f": "f", "F": "f", "x": "x", "X": "x"}


def family(key):
    """(family name, required sūtras) for a junction type, or (None, None)."""
    fa, ib, res = key.split("|")
    f, r = fa[-1], res.replace(" ", "")
    if f == "m" and r.startswith("M"):
        return "m before a consonant becomes anusvāra", {"8.3.23"}
    if f in VOWELS and ib in VOWELS:
        if f in SAVARNA and SAVARNA.get(ib) == SAVARNA[f]:
            return "like vowels merge long", {"6.1.101"}
        if f in "aA" and ib in "iIuUfFxX":
            return "a/ā + i/u/ṛ: guṇa", {"6.1.87"}
        if f in "aA" and ib in "eEoO":
            return "a/ā + e/ai/o/au: vṛddhi", {"6.1.88"}
        if f in "iIuUfFxX":
            return "i/u/ṛ before an unlike vowel: yaṇ", {"6.1.77"}
        if f in "eo" and ib == "a" and "'" in res:
            return "e/o + a: pūrvarūpa (avagraha)", {"6.1.109"}
        if f in "eEoO":
            return "e/ai/o/au before a vowel: ay/āy/av/āv", {"6.1.78"}
    if f == "s":
        v = fa[:-1]
        if v == "a" and r.startswith("o"):
            return ("-as + a: o and avagraha", {"8.2.66", "6.1.113", "6.1.87", "6.1.109"}) if ib == "a" \
                else ("-as + voiced consonant: o", {"8.2.66", "6.1.114", "6.1.87"})
        if v == "a" and ib in VOWELS:
            return "-as + other vowel: y, then dropped", {"8.2.66", "8.3.17", "8.3.19"}
        if ib == "r" and "r" not in r.replace(" ", "")[:-1]:
            return "s/r before r: first r dropped (vowel lengthened)", {"8.3.14"}
        if v == "A" and (ib in VOWELS or ib in VOICED):
            return "-ās + voiced: y, then dropped", {"8.2.66", "8.3.17"}
        if v and v not in "aA" and (ib in VOWELS or ib in VOICED) and "r" in r:
            if ib == "r":
                return "r + r: first r dropped, vowel lengthened", {"8.3.14"}
            return "-is/-us/... + voiced: r", {"8.2.66"}
        if ib in "tT":
            return "visarga before t/th: s", {"8.2.66", "8.3.34"}
        if ib in "cC":
            return "visarga before c/ch: ś", {"8.2.66", "8.3.34", "8.4.40"}
        if r.endswith("H" + ib) or "H" in r:
            return "visarga kept before k/p/sibilant", {"8.2.66", "8.3.15"}
    if f == "r" and ib in "tTcC":
        return "r before t/c: visarga, then s/ś", {"8.3.15", "8.3.34"} | ({"8.4.40"} if ib in "cC" else set())
    if f == "r" and "H" in r:
        return "r before a voiceless consonant: visarga", {"8.3.15"}
    if f in "tdkg":
        if ib in "cCjJ":
            return "dental before a palatal: palatal", {"8.4.40"}
        if ib == "S":
            return "t + ś: c ch", {"8.4.40", "8.4.63"}
        if ib == "l":
            return "t + l: l", {"8.4.60"}
        if ib in "nmNYR":
            return "stop before a nasal: nasal", {"8.4.45"}
        if ib == "h":
            return "stop + h", {"8.2.39", "8.4.62"}
        if ib in VOWELS or ib in VOICED:
            return "final stop before a voiced sound: voiced", {"8.2.39"}
    if f == "n":
        if ib in "tTcC":
            return "n before t/c: ṃs/ṃś", {"8.3.7"}
        if ib in VOWELS and r.startswith(fa[:-1] + "nn"):
            return "n after a short vowel, before a vowel: doubled", {"8.3.32"}
        if ib == "l":
            return "n + l: nasal l", {"8.4.60"}
        if ib in "jJS":
            return "n before a palatal: ñ", {"8.4.40"}
    if ib == "C" and "cC" in r:
        return "short vowel + ch: cch", {"6.1.73"}
    return None, None


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "web/data/sandhi-rules.json")
    rules = json.load(open(path, encoding="utf-8"))
    types = json.load(open(os.path.join(ROOT, "data/build/sandhi-types.json"), encoding="utf-8"))
    by = Counter()
    disagree, unclassified = [], []
    for key, c in rules["r"].items():
        model = c.get("m", rules["model"])
        fam, need = family(key)
        cited = {s[0] for s in c["s"]}
        if fam is None:
            unclassified.append((key, model, c))
            by[(model, "unclassified")] += 1
        elif need <= cited:
            by[(model, "agree")] += 1
        else:
            disagree.append((key, model, fam, need - cited, c))
            by[(model, "disagree")] += 1
    joins = {k: types.get(k, {}).get("n", 0) for k in rules["r"]}
    print("By model:")
    for m in sorted({m for m, _ in by}):
        print(f"  {m}: agree {by[(m, 'agree')]}, disagree {by[(m, 'disagree')]}, unclassified {by[(m, 'unclassified')]}")
    total = sum(joins.values())
    bad = sum(joins[k] for k, *_ in disagree)
    print(f"Joins in the texts covered by disagreeing citations: {bad} of {total}")
    print(f"\nDisagree ({len(disagree)}), most frequent first:")
    for key, model, fam, missing, c in sorted(disagree, key=lambda x: -joins[x[0]]):
        print(f"  {key}  [{joins[key]} joins, {model.split('/')[-1]}]  family: {fam}; missing {sorted(missing)}")
        print(f"      cited: {' → '.join(s[0] for s in c['s'])}   why: {c['why'][:110]}")
    print(f"\nUnclassified ({len(unclassified)}):")
    for key, model, c in unclassified:
        print(f"  {key}  [{joins[key]} joins, {model.split('/')[-1]}]  cited: {' → '.join(s[0] for s in c['s'])}")


if __name__ == "__main__":
    main()
