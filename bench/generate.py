"""Generate benchmark items whose answers are fixed by rule or by two
independent sources, never by an LLM.

Tasks
  tinanta   produce a finite verb form           (answer: Vidyut derivation)
  subanta   produce a declined noun form         (answer: Vidyut derivation)
  analyze   identify lakāra/puruṣa/vacana         (answer: every analysis Vidyut admits)
  gita      lemma + grammar of a word in a verse  (answer: DCS annotation that Vidyut confirms)
  meter     scan a half-verse into guru/laghu     (answer: Vidyut weights, meter rule-checked)

Every item lists all acceptable answers, so ambiguity is the item's,
never the grader's.

    python bench/generate.py --seed 108 --out bench/data/v0.jsonl
"""
import argparse
import glob
import json
import os
import random
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.prakriya import (Lakara, Linga, Pada, Pratipadika, Prayoga,  # noqa: E402
                             Purusha, Vacana, Vibhakti)

from engine import dcs, labels, meter, verify  # noqa: E402

LAKARAS = [Lakara.Lat, Lakara.Lan, Lakara.Lot, Lakara.VidhiLin, Lakara.Lrt,
           Lakara.Lit, Lakara.Lun]
LAKARA_NAME = {Lakara.Lat: ("laṭ", "present"), Lakara.Lan: ("laṅ", "imperfect"),
               Lakara.Lot: ("loṭ", "imperative"),
               Lakara.VidhiLin: ("vidhiliṅ", "optative"),
               Lakara.Lrt: ("lṛṭ", "simple future"), Lakara.Lit: ("liṭ", "perfect"),
               Lakara.Lun: ("luṅ", "aorist")}
PURUSHA_NAME = {Purusha.Prathama: ("prathama", "3rd"),
                Purusha.Madhyama: ("madhyama", "2nd"),
                Purusha.Uttama: ("uttama", "1st")}
VACANA_NAME = {Vacana.Eka: ("eka", "singular"), Vacana.Dvi: ("dvi", "dual"),
               Vacana.Bahu: ("bahu", "plural")}
VIBHAKTI_NAME = {Vibhakti.Prathama: ("prathamā", "nominative"),
                 Vibhakti.Dvitiya: ("dvitīyā", "accusative"),
                 Vibhakti.Trtiya: ("tṛtīyā", "instrumental"),
                 Vibhakti.Caturthi: ("caturthī", "dative"),
                 Vibhakti.Panchami: ("pañcamī", "ablative"),
                 Vibhakti.Sasthi: ("ṣaṣṭhī", "genitive"),
                 Vibhakti.Saptami: ("saptamī", "locative"),
                 Vibhakti.Sambodhana: ("sambodhana", "vocative")}
LINGA_NAME = {Linga.Pum: ("puṃliṅga", "masculine"),
              Linga.Stri: ("strīliṅga", "feminine"),
              Linga.Napumsaka: ("napuṃsakaliṅga", "neuter")}
GANA_IAST = {"BvAdi": "bhvādi", "adAdi": "adādi", "juhotyAdi": "juhotyādi",
             "divAdi": "divādi", "svAdi": "svādi", "tudAdi": "tudādi",
             "ruDAdi": "rudhādi", "tanAdi": "tanādi", "kryAdi": "kryādi",
             "curAdi": "curādi"}

# Common roots by dhātupāṭha code, with the sense used in prompts. Curated so
# that every prompt names one unambiguous root (gaṇa + meaning).
ROOTS = {
    "01.0001": "to be", "01.1137": "to go", "01.1077": "to stand",
    "01.1143": "to see", "02.0058": "to speak", "02.0060": "to be",
    "08.0010": "to do, make", "03.0010": "to give", "03.0011": "to place",
    "01.1130": "to obtain", "04.0069": "to fight", "04.0073": "to think",
    "09.0043": "to know", "01.1092": "to hear", "02.0059": "to know",
    "01.1157": "to sacrifice", "01.1141": "to abandon", "01.1049": "to lead",
    "02.0002": "to strike, kill", "01.0643": "to live", "02.0044": "to go",
    "02.0040": "to go", "06.0166": "to release", "01.0919": "to remember",
    "01.0995": "to grow, ascend", "01.1153": "to share, worship",
    "01.0640": "to move, wander", "01.0979": "to fall", "01.1160": "to dwell",
    "04.0068": "to understand", "01.0746": "to protect", "05.0017": "to be able",
    "06.0078": "to wish", "01.1046": "to carry, take", "01.1164": "to speak",
    "01.0642": "to conquer", "04.0091": "to perish", "04.0081": "to be pleased",
    "02.0063": "to sleep", "01.1074": "to drink", "01.0574": "to serve",
    "01.0863": "to grow", "04.0044": "to be born", "01.0545": "to step",
    "02.0026": "to lie down", "02.0039": "to say", "05.0016": "to obtain",
    "01.1124": "to cross", "06.0160": "to enter", "01.1047": "to hold",
    "01.1140": "to heat, perform austerity", "01.0405": "to play",
    "01.1159": "to carry", "04.0065": "to go",
}


def curated_roots():
    from vidyut.prakriya import Data
    entries = Data(os.path.join(verify.DATA, "prakriya")).load_dhatu_entries()
    by_code = {e.code: e for e in entries}
    return [(by_code[c], meaning) for c, meaning in ROOTS.items()]


FORMAT_FORM = ('Answer with JSON only: {"form": "<word in IAST>"}. '
               "Use IAST transliteration with diacritics.")
FORMAT_ANALYSIS = ('Answer with JSON only: {"lakara": "<one of: lat, lan, lot, '
                   'vidhilin, lrt, lit, lun>", "purusha": "<prathama|madhyama|uttama>", '
                   '"vacana": "<eka|dvi|bahu>"}')
FORMAT_GITA = ('Answer with JSON only: {"lemma": "<dictionary form, IAST>", '
               '"pos": "<noun|pronoun|adjective|verb>", "case": "<nom|acc|ins|dat|abl|gen|loc|voc or null>", '
               '"number": "<sg|du|pl>", "gender": "<m|f|n or null>", '
               '"tense_mood": "<present|imperative|optative|imperfect|aorist|perfect|future|injunctive or null>", '
               '"person": "<1|2|3 or null>", "voice": "<active|passive or null>"}')
FORMAT_METER = ('Answer with JSON only: {"pattern": "<one character per syllable: '
                'G for guru (heavy), L for laghu (light)>"}')


def clean_root(aupadeshika: str) -> str:
    """Root as normally cited: strip accent and anubandha markers."""
    s = aupadeshika.replace("\\", "").replace("^", "")
    for pre in ("qu", "wu", "Yi", "Ri"):
        if s.startswith(pre) and len(s) > len(pre) + 1:
            s = s[len(pre):]
    if "~" in s:
        s = s[:s.index("~") - 1]
    s = s.rstrip("YNRkzrs") if s[-1] in "YNR" else s
    if s.startswith("z"):
        s = "s" + s[1:].replace("W", "T")
    if s.startswith("R"):
        s = "n" + s[1:]
    return s


def root_label(entry, meaning) -> str:
    d = entry.dhatu
    gana = GANA_IAST.get(str(d.gana), str(d.gana))
    return f"√{verify.to_iast(clean_root(d.aupadeshika))} ({gana}, '{meaning}')"


def attested(rng):
    """Roots and stems the engine confirms in the Gītā, with frequencies."""
    roots, stems, gold = Counter(), Counter(), []
    root_entry, stem_entry = {}, {}
    for f in sorted(glob.glob(os.path.join(ROOT, "data/sources/dcs-gita/*.conllu"))):
        for hv in dcs.read(f):
            for g in hv["groups"]:
                for t in g["tokens"]:
                    r = verify.check(t)
                    if r["status"] != "agree":
                        continue
                    v, e = r["entry"], r["entry"]["raw"]
                    if v["kind"] == "tinanta":
                        d = e.dhatu_entry.dhatu
                        if not (getattr(d, "prefixes", None) or []):
                            k = (d.aupadeshika, str(d.gana))
                            roots[k] += 1
                            root_entry[k] = e.dhatu_entry
                    elif (not v.get("krdanta") and not v.get("avyaya")
                          and t["upos"] in ("NOUN", "ADJ")):
                        pe = e.pratipadika_entry
                        stems[pe.pratipadika.text] += 1
                        stem_entry[pe.pratipadika.text] = pe
                    if t["upos"] in ("NOUN", "ADJ", "PRON", "VERB") and \
                            t["feats"].get("VerbForm") is None:
                        gold.append((hv, g, t))
    return roots, root_entry, stems, stem_entry, gold


def derive_forms(pada) -> list[str]:
    try:
        return sorted({verify.to_iast(p.text) for p in verify.vyakarana().derive(pada)})
    except Exception:
        return []


def gen_tinanta(rng, roots, n):
    items = []
    tries = 0
    while len(items) < n and tries < n * 20:
        tries += 1
        de, meaning = rng.choice(roots)
        lak, pur, vac = rng.choice(LAKARAS), rng.choice(list(PURUSHA_NAME)), \
            rng.choice(list(VACANA_NAME))
        pada = Pada.Tinanta(dhatu=de.dhatu, prayoga=Prayoga.Kartari,
                            lakara=lak, purusha=pur, vacana=vac)
        forms = derive_forms(pada)
        if not forms:
            continue
        spec = (f"{LAKARA_NAME[lak][0]} ({LAKARA_NAME[lak][1]}), "
                f"{PURUSHA_NAME[pur][0]}-puruṣa ({PURUSHA_NAME[pur][1]} person), "
                f"{VACANA_NAME[vac][0]}vacana ({VACANA_NAME[vac][1]}), kartari (active)")
        items.append({
            "task": "tinanta",
            "prompt": (f"Give the Sanskrit verb form of {root_label(de, meaning)} in "
                       f"{spec}. If the root takes both parasmaipada and "
                       f"ātmanepada endings, either is accepted. {FORMAT_FORM}"),
            "accept": forms,
            "meta": {"root": clean_root(de.dhatu.aupadeshika), "code": de.code,
                     "aupadeshika": de.dhatu.aupadeshika, "label": root_label(de, meaning),
                     "lakara": lak.name, "purusha": pur.name, "vacana": vac.name}})
    return items


def gen_subanta(rng, stems, stem_entry, n):
    items, keys = [], [k for k, _ in stems.most_common(150)]
    tries = 0
    while len(items) < n and tries < n * 20:
        tries += 1
        k = rng.choice(keys)
        pe = stem_entry[k]
        lingas = list(pe.lingas) or [Linga.Pum]
        lin = rng.choice(lingas)
        vib, vac = rng.choice(list(VIBHAKTI_NAME)), rng.choice(list(VACANA_NAME))
        pada = Pada.Subanta(pratipadika=Pratipadika.basic(k), linga=lin,
                            vibhakti=vib, vacana=vac)
        forms = derive_forms(pada)
        if not forms:
            continue
        items.append({
            "task": "subanta",
            "prompt": (f"Decline the stem '{verify.to_iast(k)}' "
                       f"({LINGA_NAME[lin][0]}, {LINGA_NAME[lin][1]}) in "
                       f"{VIBHAKTI_NAME[vib][0]} ({VIBHAKTI_NAME[vib][1]}) "
                       f"{VACANA_NAME[vac][0]}vacana ({VACANA_NAME[vac][1]}). "
                       f"{FORMAT_FORM}"),
            "accept": forms,
            "meta": {"stem": k, "linga": lin.name, "vibhakti": vib.name,
                     "vacana": vac.name}})
    return items


def gen_analyze(rng, tinanta_items, n):
    """Reverse task: given a form and its root, name lakāra/puruṣa/vacana.
    The accepted set is every analysis Vidyut admits for that form and root."""
    items = []
    pool = tinanta_items[:]
    rng.shuffle(pool)
    for it in pool:
        if len(items) >= n:
            break
        form = it["accept"][0]
        root = it["meta"]["aupadeshika"]
        ok = []
        for v in verify.lookup(form):
            if v["kind"] == "tinanta" and \
                    v["raw"].dhatu_entry.dhatu.aupadeshika == root and \
                    v["prayoga"] == Prayoga.Kartari and v["lakara"] in LAKARA_NAME:
                ok.append({"lakara": v["lakara"].name.lower(),
                           "purusha": v["purusha"].name.lower(),
                           "vacana": v["vacana"].name.lower()})
        if not ok:
            continue
        uniq = [dict(t) for t in {tuple(sorted(d.items())) for d in ok}]
        items.append({
            "task": "analyze",
            "prompt": (f"The Sanskrit word '{form}' is a finite verb form of the root "
                       f"{it['meta']['label']}, active voice. Identify its "
                       f"lakāra, puruṣa and vacana. {FORMAT_ANALYSIS}"),
            "accept": sorted(uniq, key=lambda d: json.dumps(d)),
            "meta": {"form": form, "root": it["meta"]["root"]}})
    return items


UD_CASE = {"Nom": "nom", "Acc": "acc", "Ins": "ins", "Dat": "dat", "Abl": "abl",
           "Gen": "gen", "Loc": "loc", "Voc": "voc"}
UD_NUM = {"Sing": "sg", "Dual": "du", "Plur": "pl"}
UD_GEN = {"Masc": "m", "Fem": "f", "Neut": "n"}
UD_TM = {("Pres", "Ind"): "present", ("Pres", "Imp"): "imperative",
         ("Pres", "Opt"): "optative", ("Impf", "Ind"): "imperfect",
         ("Past", "Ind"): "past", ("Aor", "Ind"): "aorist", ("Perf", "Ind"): "perfect",
         ("Fut", "Ind"): "future", ("Past", "Jus"): "injunctive"}


def gen_gita(rng, gold, n):
    items, seen = [], set()
    pool = gold[:]
    rng.shuffle(pool)
    for hv, g, t in pool:
        if len(items) >= n:
            break
        key = (t["form"], t["lemma"], json.dumps(t["feats"], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        f = t["feats"]
        finite = t["upos"] == "VERB"
        ans = {"lemma": t["lemma"],
               "pos": {"NOUN": "noun", "PRON": "pronoun", "ADJ": "adjective",
                       "VERB": "verb"}[t["upos"]],
               "number": UD_NUM.get(f.get("Number"))}
        if finite:
            tm = UD_TM.get((f.get("Tense", "Pres"), f.get("Mood", "Ind")))
            if not tm:
                continue
            ans.update(tense_mood=tm, person=f.get("Person"),
                       voice="passive" if f.get("Voice") == "Pass" else "active")
        else:
            if f.get("Case") not in UD_CASE:
                continue
            ans.update(case=UD_CASE[f["Case"]], gender=UD_GEN.get(f.get("Gender")))
        items.append({
            "task": "gita",
            "prompt": (f"In this line of the Bhagavad Gītā:\n  {hv['text']}\n"
                       f"analyse the word '{t['form']}' (as it stands before sandhi), "
                       f"which occurs in '{g['surface']}'. Give its lemma and grammar "
                       f"in this context. {FORMAT_GITA}"),
            "accept": [ans],
            "meta": {"verse": f"{hv.get('counter')}", "form": t["form"],
                     "gold_source": "DCS annotation confirmed by Vidyut"}})
    return items


def gen_meter(rng, n):
    with open(os.path.join(ROOT, "data/build/gita.json"), encoding="utf-8") as fh:
        gita = json.load(fh)
    pool = [(v["id"], line, v["meter"]) for c in gita["chapters"] for v in c["verses"]
            for line in v["lines"]
            if v["meter"].get("check") == "rule" and
            v["meter"].get("variant") in ("pathyā", "upajāti", "indravajrā",
                                          "upendravajrā")]
    rng.shuffle(pool)
    items = []
    for vid, line, m in pool[:n]:
        w = "".join(x[1] for x in meter.weights(line))
        pada_len = 8 if m["name"] == "anuṣṭubh" else 11
        items.append({
            "task": "meter",
            "prompt": (f"Scan this half-verse from the Bhagavad Gītā ({vid}) into "
                       f"syllable weights:\n  {line}\nApply the standard rules of "
                       f"Sanskrit prosody (long vowel, anusvāra, visarga, or a "
                       f"following conjunct makes a syllable guru). {FORMAT_METER}"),
            "accept": [w],
            # Pāda-final syllables are anceps; the grader ignores them.
            "meta": {"verse": vid, "meter": m["name"],
                     "anceps": [i for i in range(len(w)) if (i + 1) % pada_len == 0]}})
    return items


# Removed after hand review (19 Oct 2026) of every question at least one model
# got wrong. Each key below was wrong or genuinely disputable.
EXCLUDED = {
    "subanta-0191": "asat is the negated participle of √as: masculine nominative is asan, not asat",
    "subanta-0227": "asat is the negated participle of √as: masculine dual is asantau",
    "subanta-0199": "the feminine of īśvara is īśvarī; the key declined it as īśvarā",
    "subanta-0235": "rājasa is an aṇ derivative, so its feminine is rājasī (Gītā 17.2); the key declined rājasā",
    "gita-0350": "śaśisūryayoḥ (7.8) is read as genitive by the commentators; the annotation has locative",
    "gita-0362": "dhṛti is feminine (dhṛtiḥ sā, 18.34); the annotation has masculine",
    "gita-0377": "atīndriyam (6.21) can be nominative or the object of vetti; the annotation picks one",
    "gita-0395": "vaiśyāḥ (9.32) is the masculine plural of vaiśya; the annotation has feminine vaiśyā",
    "gita-0403": "akarmaṇaḥ (3.8) is read as ablative (Śaṅkara: akaraṇāt) or genitive; disputable",
    "gita-0412": "lelihyase (11.30) is the intensive of √lih with middle endings, not a passive",
    "gita-0418": "etayoḥ (5.1) refers to saṃnyāsa and yoga, both masculine; the annotation has neuter",
}


def confirmed(it) -> bool:
    """Second check on noun answers: every accepted form must also appear in
    Vidyut's dictionary (kosha) with the same stem, gender, case and number.
    The derivation from a bare stem can miss stem-specific rules; for example
    mahat (dual mahāntau) and the feminine of bhagavat (bhagavatī)."""
    if it["task"] != "subanta":
        return True
    m = it["meta"]
    for form in it["accept"]:
        if not any(v["kind"] == "subanta" and not v.get("krdanta")
                   and verify.canon(v["lemma"]) == verify.canon(m["stem"])
                   and v["vibhakti"].name == m["vibhakti"]
                   and v["vacana"].name == m["vacana"]
                   and v["linga"].name == m["linga"]
                   for v in verify.lookup(form)):
            return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=108)
    ap.add_argument("--out", default=os.path.join(ROOT, "bench/data/v0.jsonl"))
    ap.add_argument("--sizes", default="tinanta=150,subanta=100,analyze=100,gita=100,meter=50")
    a = ap.parse_args()
    sizes = dict((k, int(v)) for k, v in (x.split("=") for x in a.sizes.split(",")))
    rng = random.Random(a.seed)
    roots, root_entry, stems, stem_entry, gold = attested(rng)
    tin = gen_tinanta(rng, curated_roots(), sizes["tinanta"] + sizes["analyze"] * 2)
    items = (tin[:sizes["tinanta"]] +
             gen_subanta(rng, stems, stem_entry, sizes["subanta"]) +
             gen_analyze(rng, tin[sizes["tinanta"]:], sizes["analyze"]) +
             gen_gita(rng, gold, sizes["gita"]) +
             gen_meter(rng, sizes["meter"]))
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    for i, it in enumerate(items):
        it["id"] = f"{it['task']}-{i:04d}"
    # Ids are fixed before filtering, so dropping an item never renumbers others.
    dropped = [it["id"] for it in items if not confirmed(it) or it["id"] in EXCLUDED]
    items = [it for it in items if it["id"] not in dropped]
    if dropped:
        print("dropped after dictionary cross-check:", ", ".join(dropped))
    with open(a.out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(Counter(it["task"] for it in items), "->", a.out)


if __name__ == "__main__":
    main()
