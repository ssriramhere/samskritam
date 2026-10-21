"""Generate the v1 candidate pool from the Mahābhārata (for now the
Nalopākhyāna, critical edition 3.50-78), harder than v0 and less likely to be
memorised.

Five tasks, each with an answer key fixed by two independent sources or by
rule:

  context  grammar of a word inside a verse (lemma, case or tense, number...)
           key: the Digital Corpus of Sanskrit annotation, kept only where
           Vidyut confirms the rules allow it. Weighted toward what models get
           wrong: past tenses, optatives and imperatives, duals, oblique cases.
  split    undo the sandhi of a printed chunk into its words
           key: the corpus split, kept only where Vidyut's sandhi table
           rejoins those words into exactly the printed text
  join     the reverse: join the words into the printed form
           key: every output Vidyut's sandhi table allows (the printed form
           among them, as a check)
  rule     name the sūtras that produce a join
           key: the core sūtras of the join's rule family
           (pipeline/check_sandhi_cites.py), which two AI models' independent
           citations also agreed with for all 277 junction types
  meter    scan an anuṣṭubh half-verse from a verse with a vipulā pāda,
           where scanning by the common pattern fails
           key: Vidyut's prosody module; pāda-final syllables are not graded

    python bench/generate_v1.py            # -> bench/private/v1-pool.jsonl

The pool is calibrated by bench/calibrate_v1.py (drop what every pilot model
gets right) and split into a public dev set and a private test set. The pool
stays in bench/private/ (not committed): it contains the test items.
"""
import argparse
import itertools
import json
import os
import random
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
sys.path.insert(0, os.path.join(ROOT, "bench"))
from vidyut.lipi import Scheme, transliterate  # noqa: E402

from engine import meter, sandhi  # noqa: E402
from engine.verify import to_slp1  # noqa: E402
from check_sandhi_cites import family  # noqa: E402
from generate import FORMAT_GITA, FORMAT_METER, UD_CASE, UD_GEN, UD_NUM, UD_TM  # noqa: E402

SOURCE = "data/build/mahabharata.json"
TITLE = "the Mahābhārata (critical edition"
FORMAT_SPLIT = ('Answer with JSON only: {"words": ["<word 1 in IAST>", "<word 2>", ...]}')
FORMAT_JOIN = 'Answer with JSON only: {"form": "<the joined text in IAST>"}'
FORMAT_RULE = ('Answer with JSON only: {"sutras": ["<adhyāya.pāda.sūtra>", ...]}, '
               'listing the sūtras in the order they apply.')


def iast(slp):
    return transliterate(slp, Scheme.Slp1, Scheme.Iast)


def verses():
    d = json.load(open(os.path.join(ROOT, SOURCE), encoding="utf-8"))
    for c in d["chapters"]:
        for v in c["verses"]:
            yield v


def where(vid):
    return f"{TITLE}, {vid})"


# ---- context ---------------------------------------------------------------

def context_key(t):
    """v0's Gītā answer format, or None for words it can't express."""
    f = t["feats"]
    if t["upos"] not in ("NOUN", "PRON", "ADJ", "VERB") or f.get("VerbForm") or f.get("Case") == "Cpd":
        return None
    ans = {"lemma": t["lemma"], "pos": {"NOUN": "noun", "PRON": "pronoun", "ADJ": "adjective",
                                         "VERB": "verb"}[t["upos"]],
           "number": UD_NUM.get(f.get("Number"))}
    if not ans["number"]:
        return None
    if t["upos"] == "VERB":
        tm = UD_TM.get((f.get("Tense", "Pres"), f.get("Mood", "Ind")))
        if not tm or not f.get("Person"):
            return None
        ans.update(tense_mood=tm, person=f["Person"], voice="passive" if f.get("Voice") == "Pass" else "active")
    else:
        if f.get("Case") not in UD_CASE:
            return None
        ans.update(case=UD_CASE[f["Case"]], gender=UD_GEN.get(f.get("Gender")))
    return ans


def stratum(ans):
    if ans["pos"] == "verb":
        return "verb-other" if ans["tense_mood"] == "present" else "verb-hard"
    if ans["number"] == "du":
        return "dual"
    if ans["case"] in ("abl", "dat", "voc", "loc", "gen", "ins"):
        return "oblique"
    return "nominal-other"


def gen_context(rng, n):
    quota = {"verb-hard": .35, "dual": .15, "oblique": .30, "verb-other": .10, "nominal-other": .10}
    pools = defaultdict(list)
    for v in verses():
        for h in v["halves"]:
            for g in h["groups"]:
                for t in g["tokens"]:
                    if t["status"] != "agree":
                        continue
                    ans = context_key(t)
                    if ans:
                        pools[stratum(ans)].append((v, g, t, ans))
    items, seen = [], set()
    for s, share in quota.items():
        pool = pools[s][:]
        rng.shuffle(pool)
        k = 0
        for v, g, t, ans in pool:
            if k >= round(n * share):
                break
            key = (t["form"], t["lemma"], json.dumps(ans, sort_keys=True))
            if key in seen:
                continue
            seen.add(key)
            k += 1
            text = "\n  ".join(v["lines"])
            items.append({
                "task": "context",
                "prompt": (f"In this verse of {where(v['id'])}:\n  {text}\n"
                           f"analyse the word '{t['form']}' (as it stands before sandhi), which occurs in "
                           f"'{g['surface']}'. Give its lemma and grammar in this context. {FORMAT_GITA}"),
                "accept": [ans],
                "meta": {"verse": v["id"], "form": t["form"], "stratum": s,
                         "gold_source": "DCS annotation confirmed by Vidyut"}})
    return items


# ---- split and join --------------------------------------------------------

def traced_groups(compounds=False):
    """Printed chunks of two or more words whose half-line Vidyut's sandhi
    table rejoins exactly. Without compounds=True, chunks containing compound
    members are left out (splitting those would also test where to split a
    compound, which has no single right answer)."""
    out = []
    for v in verses():
        for h in v["halves"]:
            words, gidx = [], []
            for n, g in enumerate(h["groups"]):
                for t in g["tokens"]:
                    words.append(t["form"])
                    gidx.append(n)
            if len(words) < 2 or sandhi.explain_line(words, gidx, h["text"]) is None:
                continue
            for g in h["groups"]:
                toks = g["tokens"]
                if len(toks) < 2 or (not compounds and any(t["feats"].get("Case") == "Cpd" for t in toks)):
                    continue
                r = sandhi.explain_line([t["form"] for t in toks], [0] * len(toks), g["surface"])
                if r:  # at least one real join inside the chunk
                    out.append((v, h, g, r))
    return out


def all_joins(words, r_visarga=True):
    """Every form Vidyut's sandhi table allows when joining these words in one
    printed chunk (optional rules give several), in SLP1 without spaces.
    r_visarga=False treats every final -ḥ as -s (it is -r only in a few words
    such as punar, antar)."""
    R = sandhi.rules()
    forms = {to_slp1(words[0])}
    for w in words[1:]:
        nxt = to_slp1(w)
        new = set()
        for acc in forms:
            ruled = False
            for a in sandhi._finals(acc):
                if not r_visarga and acc.endswith("H") and a.endswith("r"):
                    continue
                for k in (2, 1):
                    for res in R.get((a[-k:], nxt[:1]), []):
                        new.add(a[:-k] + sandhi._clean(res) + nxt[1:])
                        if res.replace(" ", "") == "cC" and nxt[:1] == "S":
                            # 8.4.63 śaś cho 'ṭi is optional: t + ś may also print as cś
                            new.add(a[:-k] + "cS" + nxt[1:])
                        ruled = True
            if not ruled:
                # No rule for any spelling of this final: the sounds meet unchanged.
                # (Checked across all spellings, so tāḥ + tu can't come out as tāḥtu.)
                new.add(acc + nxt)
        forms = new
    return {sandhi._clean(f) for f in forms}


def gen_split_join(rng, n_split, n_join):
    pool = traced_groups()
    rng.shuffle(pool)
    split, join, seen = [], [], set()
    for v, h, g, r in pool:
        if len(split) >= n_split:
            break
        if g["surface"] in seen:
            continue
        seen.add(g["surface"])
        words = [t["form"] for t in g["tokens"]]
        split.append({
            "task": "split",
            "prompt": (f"In this line of {where(v['id'])}:\n  {h['text']}\n"
                       f"undo the sandhi in '{g['surface']}' and give the separate words it is made of, "
                       f"in order. Give each word as it would stand alone (pausa form: final visarga, "
                       f"e.g. adhikāraḥ, tat). {FORMAT_SPLIT}"),
            "accept": [words],
            "meta": {"verse": v["id"], "surface": g["surface"], "joins": [j["key"] for j in r],
                     "gold_source": "DCS split rejoined exactly by Vidyut's sandhi rules"}})
    # Joining also uses chunks with compound members: the sandhi is the same.
    pool = [x for x in traced_groups(compounds=True) if x[2]["surface"] not in seen]
    rng.shuffle(pool)
    for v, h, g, r in pool:
        if len(join) >= n_join:
            break
        if g["surface"] in seen:
            continue
        seen.add(g["surface"])
        words = [t["form"] for t in g["tokens"]]
        printed = sandhi._clean(to_slp1(g["surface"]))
        forms = all_joins(words, r_visarga=False)
        if printed not in forms:  # a final -ḥ that stands for -r
            forms = all_joins(words)
        if printed not in forms:
            continue  # the table can't produce the printed form: no clean key
        join.append({
            "task": "join",
            "prompt": (f"Join these words from {where(v['id'])} into one printed chunk, applying "
                       f"sandhi as a classical text would print them:\n  "
                       f"{' + '.join(words)}\n{FORMAT_JOIN}"),
            "accept": sorted(iast(f) for f in forms),
            "meta": {"verse": v["id"], "printed": g["surface"], "words": words,
                     "gold_source": "Vidyut's sandhi table; the printed form is among the answers"}})
    return split, join


# ---- rule -------------------------------------------------------------------

def gen_rule(rng, n):
    examples = defaultdict(list)
    for v in verses():
        for h in v["halves"]:
            words, gidx = [], []
            for k, g in enumerate(h["groups"]):
                for t in g["tokens"]:
                    words.append(t["form"])
                    gidx.append(k)
            r = sandhi.explain_line(words, gidx, h["text"]) if len(words) > 1 else None
            for j in r or []:
                fa, ib, res = j["key"].split("|")
                left = to_slp1(words[j["left"]])
                base = next((x for x in sandhi._finals(left) if x.endswith(fa)), left)
                joined = base[:-len(fa)] + (res if j["across"] else sandhi._clean(res)) + to_slp1(words[j["right"]])[1:]
                examples[j["key"]].append((v["id"], words[j["left"]], words[j["right"]], iast(joined)))
    items = []
    keys = [k for k in examples if family(k)[0]]
    rng.shuffle(keys)
    # one item per junction type, most varied families first
    by_family = defaultdict(list)
    for k in keys:
        by_family[family(k)[0]].append(k)
    order = [k for group in itertools.zip_longest(*[ks[:8] for ks in by_family.values()]) for k in group if k]
    for k in order[:n]:
        vid, a, b, j = rng.choice(examples[k])
        fam, need = family(k)
        items.append({
            "task": "rule",
            "prompt": (f"In {where(vid)}, '{a}' and '{b}' join as '{j}'. Which sūtras of Pāṇini's "
                       f"Aṣṭādhyāyī produce this join? {FORMAT_RULE}"),
            "accept": [sorted(need)],
            "meta": {"verse": vid, "junction": k, "family": fam,
                     "gold_source": "core sūtras of the rule family; extra sūtras are allowed"}})
    return items


# ---- meter ------------------------------------------------------------------

def gen_meter(rng, n):
    pool = []
    for v in verses():
        m = v["meter"]
        if m.get("name") == "anuṣṭubh" and m.get("variant") == "vipulā":
            for line in v["lines"]:
                w = "".join(x[1] for x in meter.weights(line))
                if len(w) == 16:
                    pool.append((v["id"], line, w, m["variant"]))
    rng.shuffle(pool)
    items = []
    for vid, line, w, var in pool[:n]:
        items.append({
            "task": "meter",
            "prompt": (f"Scan this half-verse from {where(vid)} into syllable weights:\n  {line}\n"
                       f"Apply the standard rules of Sanskrit prosody (long vowel, anusvāra, visarga, or a "
                       f"following conjunct makes a syllable guru). {FORMAT_METER}"),
            "accept": [w],
            "meta": {"verse": vid, "meter": "anuṣṭubh", "variant": var,
                     "anceps": [7, 15]}})
    return items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1008)
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/private/v1-pool.jsonl"))
    ap.add_argument("--sizes", default="context=500,split=300,join=300,rule=200,meter=150")
    a = ap.parse_args()
    sizes = dict((k, int(x)) for k, x in (p.split("=") for p in a.sizes.split(",")))
    rng = random.Random(a.seed)
    split, join = gen_split_join(rng, sizes["split"], sizes["join"])
    items = gen_context(rng, sizes["context"]) + split + join + gen_rule(rng, sizes["rule"]) + gen_meter(rng, sizes["meter"])
    counts = Counter()
    for it in items:
        it["id"] = f"v1-{it['task']}-{counts[it['task']]:04d}"
        counts[it["task"]] += 1
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(dict(counts), "->", a.out)


if __name__ == "__main__":
    main()
