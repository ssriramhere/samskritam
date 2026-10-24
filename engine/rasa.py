"""Rasa in a verse: a language model names the rasa (or only a bhāva) and the
elements that build it, chosen from the fixed lists of the Nāṭyaśāstra, and
quotes the words that carry each element.

Nothing here is checked by rule: rasa is a judgement. What the code does check
is that every name comes from the lists and every quoted word is in the verse;
anything else is dropped, so the page never underlines words that aren't there.

    result = rasa.analyse(text, ask_model)   # ask_model(prompt) -> str
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from vidyut.lipi import Scheme, transliterate

from .reader import ReaderError, _letters, clean_input, parse_model_json

# The nine rasas (Bharata's eight, with śānta) and the sthāyi-bhāva of each.
RASAS = [
    ("śṛṅgāra", "love", "rati", "love"),
    ("hāsya", "the comic", "hāsa", "laughter"),
    ("karuṇa", "compassion, grief", "śoka", "grief"),
    ("raudra", "fury", "krodha", "anger"),
    ("vīra", "the heroic", "utsāha", "energy"),
    ("bhayānaka", "terror", "bhaya", "fear"),
    ("bībhatsa", "the loathsome", "jugupsā", "disgust"),
    ("adbhuta", "wonder", "vismaya", "astonishment"),
    ("śānta", "peace", "śama", "calm"),
]
VYABHICARI = [
    ("nirveda", "world-weariness"), ("glāni", "weakness"), ("śaṅkā", "apprehension"),
    ("asūyā", "envy"), ("mada", "intoxication"), ("śrama", "fatigue"), ("ālasya", "languor"),
    ("dainya", "despondency"), ("cintā", "anxious brooding"), ("moha", "bewilderment"),
    ("smṛti", "recollection"), ("dhṛti", "steadiness"), ("vrīḍā", "shame"),
    ("capalatā", "restlessness"), ("harṣa", "joy"), ("āvega", "agitation"), ("jaḍatā", "stupor"),
    ("garva", "pride"), ("viṣāda", "dejection"), ("autsukya", "longing"), ("nidrā", "sleep"),
    ("apasmāra", "loss of control"), ("supta", "dreaming"), ("vibodha", "awakening"),
    ("amarṣa", "indignation"), ("avahitthā", "concealment"), ("ugratā", "ferocity"),
    ("mati", "resolve"), ("vyādhi", "sickness"), ("unmāda", "madness"), ("maraṇa", "death"),
    ("trāsa", "terror"), ("vitarka", "deliberation"),
]
SATTVIKA = [
    ("stambha", "stupefaction"), ("sveda", "sweating"), ("romāñca", "hair standing on end"),
    ("svarabheda", "faltering voice"), ("vepathu", "trembling"), ("vaivarṇya", "pallor"),
    ("aśru", "tears"), ("pralaya", "fainting"),
]
ALIASES = {"capala": "capalatā", "cāpala": "capalatā", "cāpalya": "capalatā", "jāḍya": "jaḍatā",
           "nirvedaḥ": "nirveda", "śṛṅgāraḥ": "śṛṅgāra", "romaharṣa": "romāñca", "pulaka": "romāñca",
           "kampa": "vepathu", "gadgada": "svarabheda", "vaisvarya": "svarabheda", "bāṣpa": "aśru"}

PROMPT = """You are a scholar of Sanskrit poetics (alaṃkāraśāstra). Identify the rasa of this verse.

Verse:
{text}

Use the theory of the Nāṭyaśāstra as the later tradition reads it:
- rasa arises from vibhāva (the ālambana, whom or what the emotion is about, and the
  uddīpana, what stirs it), anubhāva (visible signs), sāttvika-bhāva (involuntary signs)
  and vyabhicāri-bhāva (passing feelings), which together develop a sthāyi-bhāva.
- Choose the rasa from these nine only: {rasas}.
- Choose sāttvika-bhāvas from these eight only: {sattvika}.
- Choose vyabhicāri-bhāvas from these thirty-three only: {vyabhicari}.

Decide which of three kinds this verse is:
- "rasa": the elements are present and develop one sthāyi-bhāva into a rasa.
- "bhava": an emotion is present but does not reach rasa in this verse, for instance
  love toward a deity, teacher or king (classed as bhāva), or a single passing feeling
  without its supports.
- "none": the verse teaches, narrates or describes without conveying an emotion.
Rasa is suggested, not stated: a word naming an emotion is not enough on its own.

For every element you name, quote the words of the verse that carry it, copied exactly
as they appear in the verse above, with its sandhi. If an element is not in this verse
but known from the work it comes from, give it with "context": true and no words.
Leave out any element that is not there. Do not invent words.

Answer with JSON only, in this shape:
{{"kind": "rasa|bhava|none",
 "rasa": "<one of the nine, or null>",
 "variety": "<sub-type in a few words, e.g. vipralambha (in separation), or null>",
 "sthayi": "<its sthāyi-bhāva, or the bhāva present, or null>",
 "summary": "<one short English line: what the verse conveys>",
 "why": "<one or two English sentences: why this rasa, or why only a bhāva, or why none>",
 "alambana": {{"text": "<English>", "words": ["<quoted>"], "context": false}} or null,
 "uddipana": {{"text": "<English>", "words": ["<quoted>"], "context": false}} or null,
 "anubhava": [{{"text": "<English>", "words": ["<quoted>"]}}],
 "sattvika": [{{"name": "<one of the eight>", "words": ["<quoted>"]}}],
 "vyabhicari": [{{"name": "<one of the thirty-three>", "words": ["<quoted>"]}}],
 "considered": [{{"rasa": "<another of the nine>", "why_not": "<English>"}}]}}"""


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in s if not unicodedata.combining(c)))


def _lookup(name, table):
    """The canonical (name, gloss) for a name the model gave, or None."""
    name = ALIASES.get(str(name or "").strip().lower(), name)
    f = _fold(name)
    for row in table:
        if _fold(row[0]) == f:
            return row
    return None


def _strip(letters: str) -> str:
    # Final sounds change with sandhi (jajñuḥ, jajñur); compare without them.
    return re.sub(r"[HrsmMntdkgpbN]$", "", letters)


def tokens(lines):
    """The verse as printed, word by word: [[iast, devanagari], ...] per line."""
    return [[[t, transliterate(t, Scheme.Iast, Scheme.Devanagari)] for t in l.split(" ") if t] for l in lines]


def _span(q, line):
    """Token indices of a run of printed words that spells out the quote, or []."""
    ql = _letters(q)
    if len(ql) < 2:
        return []
    letters = [_letters(t[0]) for t in line]
    for s in range(len(line)):
        cat = ""
        for e in range(s, len(line)):
            cat += letters[e]
            if cat == ql or _strip(cat) == _strip(ql) or (e == s and len(_strip(ql)) >= 3 and _strip(ql) in cat):
                return list(range(s, e + 1))
            if len(cat) > len(ql) + 2:
                break
    return []


def locate(quotes, toks):
    """Indices ("line.token") of printed words that the quotes cover."""
    hits = []
    for q in quotes or []:
        found = False
        for i, line in enumerate(toks):
            span = _span(str(q), line)
            if span:
                found = True
                hits += [f"{i}.{j}" for j in span if f"{i}.{j}" not in hits]
                break
        if not found:  # a quote across sandhi joins: match its words one by one
            for w in re.split(r"[\s\-]+", str(q)):
                for i, line in enumerate(toks):
                    span = _span(w, line) if len(_strip(_letters(w))) >= 3 else []
                    if span:
                        hits += [f"{i}.{j}" for j in span if f"{i}.{j}" not in hits]
                        break
    return hits


def _element(x, toks, named=None):
    if not isinstance(x, dict):
        return None
    out = {}
    if named:
        row = _lookup(x.get("name"), named)
        if not row:
            return None
        out["name"], out["gloss"] = row
    else:
        out["text"] = str(x.get("text") or "")[:160]
        if not out["text"]:
            return None
    out["at"] = locate(x.get("words") if isinstance(x.get("words"), list) else [], toks)
    if x.get("context") and not out["at"]:
        out["context"] = True
    return out


def verse_id(lines) -> str:
    """A pasted verse's id for reviewed readings (reviewed/rasa/<id>.json).
    api/suggest.js and scripts/build_reviewed.mjs compute it the same way."""
    return hashlib.sha1("\n".join(lines).encode()).hexdigest()[:12]


def analyse(raw: str, ask_model) -> dict:
    lines = clean_input(raw)
    prompt = PROMPT.format(text="\n".join(lines), rasas=", ".join(r[0] for r in RASAS),
                           sattvika=", ".join(s[0] for s in SATTVIKA),
                           vyabhicari=", ".join(v[0] for v in VYABHICARI))
    data = parse_model_json(ask_model(prompt))
    toks = tokens(lines)
    kind = str(data.get("kind") or "").lower().replace("ā", "a")
    if kind not in ("rasa", "bhava", "none"):
        raise ReaderError("The model's answer was not in the expected format. Try again.")
    rasa = _lookup(data.get("rasa"), RASAS) if kind == "rasa" else None
    if kind == "rasa" and not rasa:
        raise ReaderError("The model named a rasa outside the nine. Try again, or try another model.")
    out = {"kind": kind, "toks": toks, "iast": lines, "vid": verse_id(lines),
           "rasa": rasa[0] if rasa else None, "rasa_en": rasa[1] if rasa else None,
           "variety": str(data.get("variety") or "")[:80] or None,
           "sthayi": rasa[2] if rasa else (str(data.get("sthayi") or "")[:100] or None),
           "sthayi_en": rasa[3] if rasa else None,
           "summary": str(data.get("summary") or "")[:200],
           "why": str(data.get("why") or "")[:400]}
    if kind != "none":
        out["alambana"] = _element(data.get("alambana"), toks)
        out["uddipana"] = _element(data.get("uddipana"), toks)
        out["anubhava"] = [e for e in (_element(x, toks) for x in (data.get("anubhava") or [])[:6]) if e]
        out["sattvika"] = [e for e in (_element(x, toks, SATTVIKA) for x in (data.get("sattvika") or [])[:8]) if e]
        out["vyabhicari"] = [e for e in (_element(x, toks, VYABHICARI) for x in (data.get("vyabhicari") or [])[:8]) if e]
    out["considered"] = [{"rasa": r[0], "why_not": str(c.get("why_not") or "")[:200]}
                         for c in (data.get("considered") or [])[:3] if isinstance(c, dict)
                         for r in [_lookup(c.get("rasa"), RASAS)] if r and r[0] != out["rasa"]]
    return out


LISTS = {"rasas": [list(r) for r in RASAS]}
