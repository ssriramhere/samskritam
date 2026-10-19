"""Verification layer: checks a claimed word analysis against Vidyut's
Pāṇinian word database (kosha) and can produce the sūtra-by-sūtra
derivation (prakriyā) for a verified form.

A claim is a dict in DCS / Universal Dependencies style:
    {"form": "karmaṇi", "lemma": "karman", "upos": "NOUN",
     "feats": {"Case": "Loc", "Gender": "Neut", "Number": "Sing"}}

check() returns a status:
    "agree"        a kosha entry matches lemma and every stated feature
    "form-known"   the form exists, but no entry matches the claimed analysis
    "unknown"      the form is not in the kosha
    "not-checked"  compound members and other tokens the engine does not cover
"""
from __future__ import annotations

import csv
import os
import re
from functools import lru_cache

from vidyut.kosha import Kosha
from vidyut.lipi import Scheme, transliterate
from vidyut.prakriya import (Lakara, Linga, Prayoga, Purusha, Vacana,
                             Vibhakti, Vyakarana)

DATA = os.environ.get(
    "VIDYUT_DATA",
    os.path.join(os.path.dirname(__file__), "..", "vidyut-data"))

# ---- feature maps: UD/DCS -> Vidyut enums --------------------------------
CASE = {"Nom": Vibhakti.Prathama, "Acc": Vibhakti.Dvitiya,
        "Ins": Vibhakti.Trtiya, "Dat": Vibhakti.Caturthi,
        "Abl": Vibhakti.Panchami, "Gen": Vibhakti.Sasthi,
        "Loc": Vibhakti.Saptami, "Voc": Vibhakti.Sambodhana}
GENDER = {"Masc": Linga.Pum, "Fem": Linga.Stri, "Neut": Linga.Napumsaka}
NUMBER = {"Sing": Vacana.Eka, "Dual": Vacana.Dvi, "Plur": Vacana.Bahu}
PERSON = {"1": Purusha.Uttama, "2": Purusha.Madhyama, "3": Purusha.Prathama}

# DCS (Tense, Mood) -> acceptable lakāras. "Past" is broad in DCS, and the
# injunctive (Mood=Jus) is an augmentless past form used with mā (6.4.74).
LAKARA = {
    ("Pres", "Ind"): {Lakara.Lat}, ("Pres", "Imp"): {Lakara.Lot},
    ("Pres", "Opt"): {Lakara.VidhiLin}, ("Impf", "Ind"): {Lakara.Lan},
    ("Past", "Ind"): {Lakara.Lun, Lakara.Lan, Lakara.Lit},
    ("Perf", "Ind"): {Lakara.Lit}, ("Aor", "Ind"): {Lakara.Lun},
    ("Fut", "Ind"): {Lakara.Lrt, Lakara.Lut}, ("Fut", "Cond"): {Lakara.Lrn},
    ("Past", "Jus"): {Lakara.Lun, Lakara.Lan}, ("Pres", "Ben"): {Lakara.AshirLin},
}

# DCS lemma conventions that differ from Vidyut's.
LEMMA_ALIASES = {"tvad": {"yuzmad"}, "mad": {"asmad"}, "yuṣmad": {"yuzmad"},
                 "asmad": {"asmad"}, "ka": {"kim"}, "kaścit": {"kim"},
                 "kaścana": {"kim"}, "paś": {"dfS"}}

# DCS splits some bound morphemes into their own tokens (a-/an- negation,
# the -tva abstract suffix). The engine analyses whole words, so skip them.
BOUND_MORPHEMES = {"a", "an", "tva", "tā", "vat", "tas"}

# √vid has a present-meaning perfect (vidulaṭo vā, 3.4.83): accept both.
PRESENT_PERFECT = {"vid"}

AVYAYA_UPOS = {"PART", "ADV", "CONJ", "CCONJ", "SCONJ", "INTJ", "ADP"}


def to_slp1(text: str) -> str:
    return transliterate(text, Scheme.Iast, Scheme.Slp1)


def to_iast(text: str) -> str:
    return transliterate(text, Scheme.Slp1, Scheme.Iast)


# Anusvāra before a stop is written either as M or as the homorganic nasal
# (saṃjaya / sañjaya). Vidyut and DCS differ word by word, so keys are tried
# in both spellings and lemmas are compared in one canonical spelling.
_HOMORGANIC = {}
for nasal, stops in (("N", "kKgG"), ("Y", "cCjJ"), ("R", "wWqQ"),
                     ("n", "tTdD"), ("m", "pPbB")):
    for c in stops:
        _HOMORGANIC[c] = nasal


def _nasal_variants(s: str) -> set[str]:
    a = re.sub(r"M(?=[kKgGcCjJwWqQtTdDpPbB])",
               lambda m: _HOMORGANIC[s[m.end()]], s)
    b = re.sub(r"[NYRnm](?=[kKgGcCjJwWqQtTdDpPbB])",
               lambda m: "M" if _HOMORGANIC[s[m.end()]] == m.group() else m.group(), s)
    return {s, a, b}


def canon(slp: str) -> str:
    """Canonical spelling for comparing stems: homorganic nasal -> M."""
    return sorted(_nasal_variants(slp), key=lambda x: (x.count("M") * -1, x))[0]


_FINAL_VOICED = {"d": "t", "g": "k", "b": "p", "q": "w"}


def kosha_keys(form_iast: str) -> list[str]:
    """Kosha keys are pada forms before final sandhi: final visarga is
    stored as s, final anusvāra as m, final stops voiceless."""
    s = to_slp1(form_iast.strip().strip("'"))
    if s.endswith("H"):
        s = s[:-1] + "s"
    elif s.endswith("M"):
        s = s[:-1] + "m"
    elif s and s[-1] in _FINAL_VOICED:
        s = s[:-1] + _FINAL_VOICED[s[-1]]
    keys = sorted(_nasal_variants(s))
    return keys


def kosha_key(form_iast: str) -> str:
    return kosha_keys(form_iast)[0]


# Vowel sandhi at an upasarga + root boundary (pra + āp -> prāp).
_VSANDHI = {("a", "a"): "A", ("a", "A"): "A", ("A", "a"): "A", ("A", "A"): "A",
            ("a", "i"): "e", ("a", "I"): "e", ("a", "u"): "o", ("a", "U"): "o",
            ("a", "f"): "Ar", ("i", "i"): "I", ("i", "I"): "I", ("u", "u"): "U",
            ("u", "U"): "U"}
_YAN = {"i": "y", "I": "y", "u": "v", "U": "v"}
_VOWELS = set("aAiIuUfFxXeEoO")


def join_prefix(prefix: str, root: str) -> str:
    if not prefix or not root:
        return prefix + root
    a, b = prefix[-1], root[0]
    if (a, b) in _VSANDHI:
        return prefix[:-1] + _VSANDHI[(a, b)] + root[1:]
    if a in _YAN and b in _VOWELS:
        return prefix[:-1] + _YAN[a] + root
    if a == "d" and root[0] in "cC":   # ud + c -> uc
        return prefix[:-1] + "c" + root
    if a == "d" and root.startswith("sT"):  # ud + sthā -> utthā (8.4.61)
        return prefix[:-1] + "tT" + root[2:]
    if a == "m" and b not in _VOWELS:  # sam + yam -> saṃyam
        return prefix[:-1] + "M" + root
    return prefix + root


def dhatu_surface(dhatu_entry) -> str:
    """Prefixed root as normally written: pra + āp -> prāp."""
    clean = dhatu_entry.clean_text
    prefixes = list(getattr(dhatu_entry.dhatu, "prefixes", []) or [])
    if not prefixes:
        return clean
    root = clean[len("".join(prefixes)):]
    out = ""
    for p in prefixes:
        out = join_prefix(out, p) if out else p
    return join_prefix(out, root)


@lru_cache(maxsize=1)
def kosha() -> Kosha:
    return Kosha(os.path.join(DATA, "kosha"))


@lru_cache(maxsize=1)
def vyakarana() -> Vyakarana:
    return Vyakarana()


@lru_cache(maxsize=1)
def sutras() -> dict[str, str]:
    path = os.path.join(DATA, "prakriya", "sutrapatha.tsv")
    with open(path, encoding="utf-8") as f:
        return {r["code"]: r["text"] for r in csv.DictReader(f, delimiter="\t")}


def _entry_view(e) -> dict:
    """Flatten a kosha PadaEntry into a plain dict we can compare."""
    v = {"raw": e}
    if hasattr(e, "lakara") and hasattr(e, "purusha"):  # Tinanta
        v.update(kind="tinanta", lemma=dhatu_surface(e.dhatu_entry),
                 lakara=e.lakara, purusha=e.purusha, vacana=e.vacana,
                 prayoga=e.prayoga)
        return v
    pe = e.pratipadika_entry
    v.update(kind="subanta", linga=e.linga, vibhakti=e.vibhakti,
             vacana=e.vacana, avyaya=bool(getattr(pe, "is_avyaya", False)))
    if hasattr(pe, "dhatu_entry"):  # Krdanta
        v.update(lemma=dhatu_surface(pe.dhatu_entry), krt=pe.krt, krdanta=True)
    else:
        v.update(lemma=pe.pratipadika.text, krdanta=False)
    return v


def lookup(form_iast: str, extra_keys=()) -> list[dict]:
    seen, out = set(), []
    keys = list(kosha_keys(form_iast)) + list(extra_keys)
    for e in (x for k in keys for x in kosha().get(k)):
        s = str(e)
        if s in seen:
            continue
        seen.add(s)
        out.append(_entry_view(e))
    return out


def _lemma_ok(claim_lemma: str, entry_lemma: str) -> bool:
    raw = to_slp1(claim_lemma)
    c, e = canon(raw), canon(entry_lemma)
    if e == c or entry_lemma in LEMMA_ALIASES.get(claim_lemma, set()):
        return True
    # DCS cites -vat/-mat stems in their strong form (bhagavant, jagant).
    return raw.endswith("ant") and e == canon(raw[:-3] + "at")


def _matches(claim: dict, v: dict) -> bool:
    f, upos = claim.get("feats", {}), claim.get("upos")
    if not _lemma_ok(claim["lemma"], v["lemma"]):
        return False
    if upos == "VERB" and "Person" in f:  # finite verb
        if v["kind"] != "tinanta":
            return False
        lak = set(LAKARA.get((f.get("Tense", "Pres"), f.get("Mood", "Ind")), ()))
        if v["lemma"] in PRESENT_PERFECT and lak & {Lakara.Lat, Lakara.Lit}:
            lak |= {Lakara.Lat, Lakara.Lit}
        if lak and v["lakara"] not in lak:
            return False
        if PERSON.get(f.get("Person")) != v["purusha"]:
            return False
        if NUMBER.get(f.get("Number")) != v["vacana"]:
            return False
        want = Prayoga.Karmani if f.get("Voice") == "Pass" else None
        if want and v["prayoga"] != want:
            return False
        return True
    if v["kind"] != "subanta":
        return False
    if upos in AVYAYA_UPOS or f.get("VerbForm") in {"Conv", "Inf"}:
        return True  # indeclinables: lemma match is the whole check
    if "Case" in f and CASE.get(f["Case"]) != v["vibhakti"]:
        return False
    if "Number" in f and NUMBER.get(f["Number"]) != v["vacana"]:
        return False
    if "Gender" in f and GENDER.get(f["Gender"]) != v["linga"]:
        return False
    return True


def _avyaya_derivative(claim: dict, v: dict) -> bool:
    """Adverbs DCS lemmatises to their base: tattvataḥ <- tattva,
    satatam <- satata (accusative used adverbially)."""
    c = canon(to_slp1(claim["lemma"]))
    e = canon(v["lemma"])
    if v.get("avyaya") and e.startswith(c) and len(e) - len(c) <= 4:
        return True
    return (claim.get("upos") == "ADV" and c.endswith("m")
            and e == c[:-1] and v.get("vibhakti") == Vibhakti.Dvitiya)


def check(claim: dict) -> dict:
    f = claim.get("feats", {})
    if f.get("Case") == "Cpd":
        return {"status": "not-checked", "reason": "compound member"}
    if claim["lemma"] in BOUND_MORPHEMES and claim.get("upos") != "CONJ":
        return {"status": "not-checked", "reason": "bound morpheme"}
    extra = []
    # Pronominal sa/eṣa: the -s is lost by sandhi (6.1.132), kosha keeps it.
    form_slp = to_slp1(claim["form"])
    if claim["lemma"] in {"tad", "etad"} and form_slp in {"sa", "eza"}:
        extra.append(form_slp + "s")
    entries = lookup(claim["form"], extra)
    if not entries:
        return {"status": "unknown"}
    hits = [v for v in entries if _matches(claim, v)] or \
        [v for v in entries if _avyaya_derivative(claim, v)]
    if hits:
        return {"status": "agree", "entry": hits[0]}
    return {"status": "form-known",
            "alternatives": [describe(v) for v in entries[:6]]}


def describe(v: dict) -> str:
    if v["kind"] == "tinanta":
        return (f"√{to_iast(v['lemma'])} {v['lakara'].name} "
                f"{v['purusha'].name} {v['vacana'].name} {v['prayoga'].name}")
    base = ("√" if v.get("krdanta") else "") + to_iast(v["lemma"])
    if v.get("avyaya"):
        return f"{base} (avyaya)"
    return f"{base} {v['vibhakti'].name} {v['vacana'].name} {v['linga'].name}"


def derivation(entry_view: dict, form_iast: str | None = None) -> list[dict]:
    """Sūtra-by-sūtra derivation for a verified entry.

    Vidyut returns every prakriyā the rules allow (for example abravīt and
    abrūta, paśya and paśyatāt). When form_iast is given, only the variant
    that ends in that word is returned; if none does, the result is empty
    rather than a derivation of some other form."""
    e = entry_view["raw"]
    try:
        args = e.to_prakriya_args()
        ps = vyakarana().derive(args)
    except Exception as exc:  # engine gap; report, don't crash
        return [{"error": str(exc)}]
    if form_iast is not None:
        want = {canon(k) for k in kosha_keys(form_iast)}
        ps = [p for p in ps if canon(p.text) in want]
    out = []
    for p in ps[:1]:
        steps = []
        for s_ in p.history:
            raw = "".join(s_.result)
            steps.append({"sutra": s_.code, "text": to_iast(sutras().get(s_.code, "")),
                          "result_slp": raw, "result": display_iast(raw)})
        out.append({"form": to_iast(p.text), "steps": steps})
    return out


def display_iast(slp: str) -> str:
    """IAST for an intermediate prakriyā form. Accent marks (\\ and ^ in SLP1)
    are dropped, and the anunāsika marker on an it-vowel (~) is shown with a
    combining candrabindu on the vowel, the convention for upadeśa forms."""
    clean = slp.replace("\\", "").replace("^", "")
    out = to_iast(clean.replace("~", "\x00"))
    return out.replace("\x00", "\u0310")
