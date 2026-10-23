"""Generate the Samskritam benchmark v1 question pool.

v1 is built to stay below the ceiling for frontier models, after the v1 pilot
(bench/generate_v1.py) showed single-step questions on a famous text are
saturated. Every question is a whole unit the model must produce itself:

  padapatha  split a whole verse into its words (pausa forms); one wrong
             split fails the verse
             key: the corpus split, kept only where Vidyut's sandhi table
             rejoins it into exactly the printed verse; compounds may be
             written whole or with hyphens between members
  parse      lemma and grammar of every inflected word of a verse (the words
             are listed); one wrong word fails the verse
             key: the corpus annotation, kept only where Vidyut confirms every
             word and the corpus split rebuilds the printed verse
  scan       scan every line of a verse into heavy and light syllables and
             name the meter
             key: Vidyut's prosody module, only verses whose meter it
             identifies by rule
  generate   produce a verb form that rarely or never occurs in texts:
             desiderative, causative or intensive roots, precative,
             periphrastic future, conditional, passive
             key: every form Vidyut derives

Texts come from the Digital Corpus of Sanskrit; choose ones the memorisation
probe (bench/probe/) shows models can't recite.

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/OliverHellwig/sanskrit data/dcs-repo
    export BENCH_SECRET=...      # also seeds the sampling, so the pool can't be regenerated without it
    python bench/v1/generate.py                  # the probe-chosen texts (TEXTS below)
    -> bench/private/v1.jsonl (private: it contains the test questions)
"""
import argparse
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "bench"))
from vidyut.prakriya import Lakara, Pada, Prayoga, Purusha, Sanadi, Vacana  # noqa: E402

from engine import dcs, meter, sandhi, verify  # noqa: E402
from engine.verify import to_slp1  # noqa: E402
from generate import (FORMAT_GITA, LAKARA_NAME, PURUSHA_NAME, UD_CASE, UD_GEN, UD_NUM, UD_TM,  # noqa: E402
                      VACANA_NAME, clean_root, curated_roots, derive_forms, root_label)
from generate_v1 import all_joins  # noqa: E402  (the pilot's sandhi joiner)

REPO = os.path.join(ROOT, "data/dcs-repo")
# Chosen by the memorisation probe (bench/probe/, 23 Oct 2026): texts whose verses
# Claude Opus 5.5, the strongest reciter, completed near-verbatim at most 10% of
# the time (mean similarity 0.43 or less; an unrelated line scores about 0.3).
# Left out for being recited: the Nalopākhyāna (87%), Saundarānanda (70%),
# Kirātārjunīya (57%), Matsya Purāṇa and Aṣṭāṅgahṛdaya (50%), Kūrma Purāṇa (37%),
# Haribhaktivilāsa (17%), Garuḍa Purāṇa (13%).
TEXTS = ["Kathāsaritsāgara", "Bṛhatkathāślokasaṃgraha", "Bhāratamañjarī", "Skandapurāṇa (Revākhaṇḍa)",
         "Kālikāpurāṇa", "Liṅgapurāṇa", "Harivaṃśa", "Rasaratnākara", "Kokilasaṃdeśa", "Haṃsadūta", "Narmamālā"]
OUT = os.path.join(ROOT, "bench/private/v1.jsonl")
FILES_PER_TEXT = 10

FORMAT_PADA = ('Answer with JSON only: {"words": ["<word 1 in IAST>", "<word 2>", ...]} '
               "listing every word of the verse in order.")
FORMAT_PARSE = ('Answer with JSON only: {"words": [{"word": "<the word as listed>", "lemma": "<dictionary form>", '
                '"pos": "<noun|pronoun|adjective|verb>", "case": "<nom|acc|ins|dat|abl|gen|loc|voc or null>", '
                '"number": "<sg|du|pl>", "gender": "<m|f|n or null>", '
                '"tense_mood": "<present|imperative|optative|imperfect|aorist|perfect|future|injunctive or null>", '
                '"person": "<1|2|3 or null>", "voice": "<active|passive or null>"}, ...]} '
                "with one entry per listed word, in the same order.")
FORMAT_SCAN = ('Answer with JSON only: {"lines": ["<one character per syllable of line 1: G guru, L laghu>", '
               '"<line 2>", ...], "meter": "<name of the meter>"}')
FORMAT_FORM = 'Answer with JSON only: {"form": "<word in IAST>"}. Use IAST with diacritics.'


# ---- corpus -----------------------------------------------------------------

def git(*args, binary=False):
    r = subprocess.run(["git", "-C", REPO, "-c", "core.quotepath=off", *args], capture_output=True,
                       check=True, text=not binary)
    return r.stdout


def text_files(text):
    names = git("ls-tree", "--name-only", "HEAD", f"dcs/data/conllu/files/{text}/").splitlines()
    return sorted(n for n in names if n.endswith(".conllu"))


def read_file(path):
    blob = git("show", f"HEAD:{path}", binary=True)
    with tempfile.NamedTemporaryFile("wb", suffix=".conllu", delete=False) as tmp:
        tmp.write(blob)
    try:
        return dcs.read(tmp.name)
    except ValueError:
        return []  # malformed verse numbering
    finally:
        os.unlink(tmp.name)


def verses(text, rng):
    """Verses from a sample of the text's chapters: {text, ref, lines, halves}."""
    out = []
    files = text_files(text)
    for f in rng.sample(files, min(FILES_PER_TEXT, len(files))):
        chapter = os.path.basename(f).split("-", 2)[-1].rsplit("-", 1)[0]
        by = defaultdict(list)
        for h in read_file(f):
            if "counter" in h and h["groups"]:
                by[h["counter"]].append(h)
        for n, halves in by.items():
            halves.sort(key=lambda h: h.get("sub", 1))
            toks = [t for h in halves for g in h["groups"] for t in g["tokens"]]
            if len(halves) < 2 or any(t["lemma"] == "vac" for t in toks if t["upos"] == "VERB") and len(toks) <= 4:
                continue
            out.append({"text": text, "ref": f"{chapter}, verse {n}", "lines": [h["text"].strip() for h in halves],
                        "halves": halves})
    return out


def where(v):
    return f"the {v['text']} ({v['ref']})"


# ---- padapāṭha ----------------------------------------------------------------

PAUSA = {"sa": "saḥ", "eṣa": "eṣaḥ"}


# The corpus gives the enclitic pronouns me, te, naḥ, vaḥ, mā, tvā their full
# forms (mama, tava...); the verse has the enclitic, so use what's printed.
ENCLITIC = {"me": "me", "te": "te", "mā": "mā", "tvā": "tvā", "naḥ": "naḥ", "no": "naḥ", "vaḥ": "vaḥ", "vo": "vaḥ",
            "nau": "nau", "vām": "vām"}


def pausa(t):
    if t["lemma"] in ("mad", "tvad", "asmad", "yuṣmad") and t.get("surface") in ENCLITIC:
        return ENCLITIC[t["surface"]]
    return PAUSA.get(t["form"], t["form"]) if t["lemma"] in ("tad", "etad") else t["form"]


def pada_key(halves):
    """Words of the verse in order. A simple word is a string; a compound is
    {"members": [...], "accept": [every joined spelling]}. None if Vidyut's
    sandhi table can't rebuild a line from the corpus split."""
    words = []
    for h in halves:
        forms, groups = [], []
        for gi, g in enumerate(h["groups"]):
            for t in g["tokens"]:
                forms.append(pausa(t))
                groups.append(gi)
        if sandhi.explain_line(forms, groups, h["text"]) is None:
            return None
        members = []
        for g in h["groups"]:
            for t in g["tokens"]:
                if t["upos"] == "PUNCT" or not t["form"].strip():
                    continue
                if t["feats"].get("Case") == "Cpd":
                    members.append(t["form"])
                    continue
                if members:
                    ms = members + [t["form"]]
                    words.append({"members": ms, "accept": sorted(verify.to_iast(f) for f in all_joins(ms))})
                    members = []
                else:
                    words.append(pausa(t))
        if members:  # a compound left open at the line end: not a clean key
            return None
    return words


def gen_padapatha(rng, pool, n):
    items = []
    for v in pool:
        if len(items) >= n:
            break
        key = pada_key(v["halves"])
        if not key or len(key) < 5:
            continue
        items.append({"task": "padapatha",
                      "prompt": (f"Give the padapāṭha of this verse from {where(v)}:\n  " + "\n  ".join(v["lines"]) +
                                 "\nUndo all sandhi and give every word as it would stand alone (pausa form: final "
                                 "visarga, e.g. rāmaḥ, tat). Write each compound as one word; you may separate its "
                                 f"members with hyphens. {FORMAT_PADA}"),
                      "accept": [key],
                      "meta": {"text": v["text"], "ref": v["ref"], "words": len(key),
                               "gold_source": "DCS split that Vidyut's sandhi table rejoins into the printed verse"}})
    return items


# ---- parse --------------------------------------------------------------------

def parse_key(t):
    f = t["feats"]
    if t["upos"] not in ("NOUN", "PRON", "ADJ", "VERB") or f.get("VerbForm") or f.get("Case") == "Cpd":
        return None
    ans = {"lemma": t["lemma"], "pos": {"NOUN": "noun", "PRON": "pronoun", "ADJ": "adjective", "VERB": "verb"}[t["upos"]],
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


def gen_parse(rng, pool, n):
    items = []
    for v in pool:
        if len(items) >= n:
            break
        if pada_key(v["halves"]) is None:
            continue  # the corpus split doesn't rebuild the printed verse: its word forms can't be trusted
        words, keys, skip = [], [], False
        for h in v["halves"]:
            for g in h["groups"]:
                for t in g["tokens"]:
                    k = parse_key(t)
                    if not k:
                        continue
                    if verify.check(t)["status"] != "agree":
                        skip = True  # Vidyut doesn't confirm a word: no clean key for the verse
                    words.append(pausa(t))
                    keys.append(k)
        if skip or not 4 <= len(keys) <= 9:
            continue
        listing = "\n".join(f"  {i + 1}. {w}" for i, w in enumerate(words))
        items.append({"task": "parse",
                      "prompt": (f"In this verse from {where(v)}:\n  " + "\n  ".join(v["lines"]) +
                                 f"\ngive the lemma and grammar, in this context, of each of these words "
                                 f"(as they stand before sandhi):\n{listing}\n{FORMAT_PARSE}"),
                      "accept": [keys],
                      "meta": {"text": v["text"], "ref": v["ref"], "words": words,
                               "gold_source": "DCS annotation of every word, each confirmed by Vidyut"}})
    return items


# ---- scan ---------------------------------------------------------------------

def gen_scan(rng, pool, n):
    sloka, other = [], []
    for v in pool:
        try:
            m = meter.identify(v["lines"])
            weights = [meter.weights(line) for line in v["lines"]]
        except BaseException as e:  # Vidyut panics on a few malformed lines
            if isinstance(e, KeyboardInterrupt):
                raise
            continue
        if m.get("check") != "rule" or m.get("variant") in ("one pāda irregular",) or m["name"] == "unidentified":
            continue
        lines = ["".join(x[1] for x in w) for w in weights]
        if any(not l or len(l) % 2 for l in lines):
            continue
        anceps = [[len(l) // 2 - 1, len(l) - 1] for l in lines]
        it = {"task": "scan",
              "prompt": (f"Scan this verse from {where(v)}:\n  " + "\n  ".join(v["lines"]) +
                         "\nGive the weight of every syllable, line by line (a long vowel, anusvāra, visarga, or a "
                         "following conjunct makes a syllable guru), and name the meter. " + FORMAT_SCAN),
              "accept": [{"lines": lines, "meter": m["name"], "variant": m.get("variant")}],
              "meta": {"text": v["text"], "ref": v["ref"], "anceps": anceps,
                       "gold_source": "Vidyut's prosody module; the last syllable of each pāda is not graded"}}
        (sloka if m["name"] == "anuṣṭubh" else other).append(it)
    rng.shuffle(sloka)
    rng.shuffle(other)
    take_other = min(len(other), n // 2)
    return other[:take_other] + sloka[:n - take_other]


# ---- generate -----------------------------------------------------------------

SANADI = {Sanadi.san: ("desiderative", "san"), Sanadi.Ric: ("causative", "ṇic"), Sanadi.yaN: ("intensive", "yaṅ")}
RARE_LAKARAS = {Lakara.AshirLin: ("āśīrliṅ", "precative"), Lakara.Lut: ("luṭ", "periphrastic future"),
                Lakara.Lrn: ("lṛṅ", "conditional"), Lakara.Lun: ("luṅ", "aorist"), Lakara.Lit: ("liṭ", "perfect")}


def gen_generate(rng, n):
    roots, items, seen = curated_roots(), [], set()
    tries = 0
    while len(items) < n and tries < n * 30:
        tries += 1
        de, meaning = rng.choice(roots)
        kind = rng.choice(["sanadi", "sanadi", "rare", "passive"])
        san = rng.choice(list(SANADI)) if kind == "sanadi" else None
        lak = rng.choice(list(RARE_LAKARAS)) if kind != "sanadi" else rng.choice(
            [Lakara.Lat, Lakara.Lan, Lakara.VidhiLin, Lakara.Lrt, *RARE_LAKARAS])
        prayoga = Prayoga.Karmani if kind == "passive" else Prayoga.Kartari
        pur, vac = rng.choice(list(PURUSHA_NAME)), rng.choice(list(VACANA_NAME))
        key = (de.code, san, lak, prayoga, pur, vac)
        if key in seen:
            continue
        seen.add(key)
        dhatu = de.dhatu.with_sanadi([san]) if san else de.dhatu
        forms = derive_forms(Pada.Tinanta(dhatu=dhatu, prayoga=prayoga, lakara=lak, purusha=pur, vacana=vac))
        if not forms:
            continue
        ln = LAKARA_NAME.get(lak) or RARE_LAKARAS[lak]
        spec = (f"{ln[0]} ({ln[1]}), {PURUSHA_NAME[pur][0]}-puruṣa ({PURUSHA_NAME[pur][1]} person), "
                f"{VACANA_NAME[vac][0]}vacana ({VACANA_NAME[vac][1]}), "
                + ("karmaṇi (passive)" if prayoga == Prayoga.Karmani else "kartari (active)"))
        what = f"the {SANADI[san][0]} ({SANADI[san][1]}) of {root_label(de, meaning)}" if san else root_label(de, meaning)
        items.append({"task": "generate",
                      "prompt": (f"Give the Sanskrit verb form of {what} in {spec}. If both parasmaipada and "
                                 f"ātmanepada endings are possible, either is accepted. {FORMAT_FORM}"),
                      "accept": forms,
                      "meta": {"root": clean_root(de.dhatu.aupadeshika), "code": de.code,
                               "sanadi": SANADI[san][1] if san else None, "lakara": lak.name,
                               "prayoga": prayoga.name, "purusha": pur.name, "vacana": vac.name,
                               "gold_source": "Vidyut's derivation; every form it allows is accepted"}})
    return items


# ---- main ---------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", default=",".join(TEXTS), help="comma-separated DCS text names")
    ap.add_argument("--sizes", default="padapatha=90,parse=90,scan=70,generate=90")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    secret = os.environ.get("BENCH_SECRET")
    if not secret:
        print("BENCH_SECRET is not set: sampling uses a public seed, so anyone could regenerate this pool.")
    seed = int(hashlib.sha256(("v1|" + (secret or "public")).encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    sizes = dict((k, int(x)) for k, x in (p.split("=") for p in a.sizes.split(",")))
    texts = [t.strip() for t in a.texts.split(",") if t.strip()]
    if not os.path.isdir(REPO):
        sys.exit(f"No corpus clone at {REPO}. See the top of this file for the git clone command.")

    pool = []
    for t in texts:
        vs = verses(t, rng)
        print(f"{t}: {len(vs)} verses sampled")
        pool += vs
    rng.shuffle(pool)
    # Spread each task across the texts: interleave so no text dominates.
    by_text = defaultdict(list)
    for v in pool:
        by_text[v["text"]].append(v)
    mixed = [v for group in zip(*[by_text[t] for t in texts if by_text[t]]) for v in group]
    mixed += [v for v in pool if v not in mixed]

    used = set()
    def fresh():
        return [v for v in mixed if id(v) not in used]
    items = []
    for task, fn in (("padapatha", gen_padapatha), ("parse", gen_parse), ("scan", gen_scan)):
        got = fn(rng, fresh(), sizes[task])
        refs = {(i["meta"]["text"], i["meta"]["ref"]) for i in got}
        used |= {id(v) for v in mixed if (v["text"], v["ref"]) in refs}  # a verse is used by one task only
        items += got
    items += gen_generate(rng, sizes["generate"])
    counts = Counter()
    for it in items:
        it["id"] = f"v1-{it['task']}-{counts[it['task']]:04d}"
        counts[it["task"]] += 1
    # Decisions from the answer-key review (samskritam.ai/review), applied last
    from review_decisions import fixed_accept, settled
    applied, decisions = Counter(), settled(quiet=True)
    for it in items:
        d = decisions.get(it["id"])
        if not d:
            continue
        it["meta"]["reviewed"] = f"{d['by']}: {d['decision']}"
        applied[d["decision"]] += 1
        if d["decision"] == "ambiguous":
            it["meta"]["dropped"] = f"Ambiguous in review ({d['by']})" + (f": {d['note']}" if d.get("note") else "")
        elif d["decision"] == "wrong" and d.get("fix"):
            it["accept"] = fixed_accept(it["task"], d["fix"])
            it["meta"]["gold_source"] = f"corrected in review ({d['by']})" + (f": {d['note']}" if d.get("note") else "")
    if applied:
        print("reviews applied:", dict(applied))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(dict(counts), "->", a.out)
    by = Counter((it["task"], it["meta"].get("text", "—")) for it in items)
    for t in texts:
        print(f"  {t}: " + ", ".join(f"{k} {by[(k, t)]}" for k in ("padapatha", "parse", "scan") if by[(k, t)]))


if __name__ == "__main__":
    main()
