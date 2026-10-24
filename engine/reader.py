"""Read any verse: a language model proposes the word-by-word analysis, and
Vidyut checks every word against Pāṇini's rules.

The model does the parts rules cannot settle alone: splitting sandhi, choosing
the reading that fits the context, and glossing. Each proposed analysis is
then tested with the same check the Gītā reader uses, and every word is shown
with what the rules said. Nothing the model claims is shown as verified unless
the rules allow it.

    analysis = reader.read(text, ask_model)   # ask_model(prompt) -> str
"""
from __future__ import annotations

import json
import re

from vidyut.lipi import Scheme, detect, transliterate

from . import labels, meter, sandhi, verify

MAX_CHARS = 400   # one verse: even a long sragdharā fits in about 300
MAX_LINES = 4     # four pādas, or two half-verses

PROMPT = """You are a careful Sanskrit grammarian. Analyse this text word by word.

Text:
{text}

Rules:
- Split the text into its printed chunks exactly as written (the space-separated
  pieces, in order). For each chunk, undo sandhi and list the words it contains.
- Split compounds into members. Every member except the last gets case "cpd".
- Give each word as it stands before sandhi (adhikāraḥ, not adhikāras or adhikāro).
- lemma: for verbs and participles, the root with any upasarga joined as usually
  cited (gam, prāp, upās); for nouns and adjectives, the stem (karman, ātman);
  for pronouns, the citation stem (tad, yad, idam, asmad, yuṣmad).
- Use IAST with diacritics throughout.
- gloss: a short English meaning of the word in this context.
- Also give a one-sentence English translation of the whole text.

Answer with JSON only, in this shape:
{{"chunks": [{{"surface": "<chunk as printed>", "words": [{{
  "form": "<word before sandhi>", "lemma": "<lemma>",
  "pos": "<noun|adjective|pronoun|verb|participle|absolutive|infinitive|gerundive|indeclinable>",
  "case": "<nom|acc|ins|dat|abl|gen|loc|voc|cpd or null>",
  "number": "<sg|du|pl or null>", "gender": "<m|f|n or null>",
  "tense_mood": "<present|imperative|optative|imperfect|aorist|perfect|future|periphrastic future|conditional|injunctive or null>",
  "person": "<1|2|3 or null>", "voice": "<active|middle|passive or null>",
  "gloss": "<English>"}}]}}],
 "translation": "<English>"}}"""

CASE = {"nom": "Nom", "acc": "Acc", "ins": "Ins", "dat": "Dat", "abl": "Abl",
        "gen": "Gen", "loc": "Loc", "voc": "Voc", "cpd": "Cpd"}
NUMBER = {"sg": "Sing", "du": "Dual", "pl": "Plur"}
GENDER = {"m": "Masc", "f": "Fem", "n": "Neut"}
TENSE = {"present": ("Pres", "Ind"), "imperative": ("Pres", "Imp"),
         "optative": ("Pres", "Opt"), "imperfect": ("Impf", "Ind"),
         "aorist": ("Aor", "Ind"), "perfect": ("Perf", "Ind"),
         "future": ("Fut", "Ind"), "periphrastic future": ("Fut", "Ind"),
         "conditional": ("Fut", "Cond"), "injunctive": ("Past", "Jus")}
VERBFORM = {"participle": "Part", "absolutive": "Conv", "infinitive": "Inf",
            "gerundive": "Gdv"}
UPOS = {"noun": "NOUN", "adjective": "ADJ", "pronoun": "PRON", "verb": "VERB",
        "participle": "VERB", "absolutive": "VERB", "infinitive": "VERB",
        "gerundive": "VERB", "indeclinable": "ADV"}


class ReaderError(Exception):
    """Something the person can fix (bad input) or retry (model output)."""


def to_iast_text(text: str) -> str:
    text = text.strip()
    try:
        scheme = detect(text)
    except Exception:
        scheme = Scheme.Iast
    if scheme != Scheme.Iast and scheme is not None:
        text = transliterate(text, scheme, Scheme.Iast)
    return text


def clean_input(raw: str) -> list[str]:
    """Normalise to IAST lines, dropping verse numbers and daṇḍas."""
    if not raw or not raw.strip():
        raise ReaderError("Paste a verse or a line of Sanskrit first.")
    if len(raw) > MAX_CHARS:
        raise ReaderError(f"That is {len(raw)} characters; the limit is {MAX_CHARS}. Paste one verse at a time.")
    # Daṇḍas and verse numbers end a line; strip them before transliterating
    # (IAST renders a daṇḍa as ".", which would look like text).
    text = re.sub(r"(?:[|।॥]+\s*[\d०-९]*[\d०-९.\s]*[|।॥]*)", "\n", raw)
    text = re.sub(r"(?m)^\s*[\d०-९]+[.)]?\s*$", "", text)
    if not re.search(r"[ऀ-ॿ]", text) and not re.search(r"[āīūṛṝḷṃḥśṣṭḍṇñṅ]", text) \
            and re.search(r"[fqwxFQWX]", text):
        # Plain Latin with letters no Sanskrit romanisation people type uses
        # is almost always English.
        raise ReaderError("That doesn't look like Sanskrit. Paste it in Devanagari or IAST.")
    text = to_iast_text(text)
    lines = [re.sub(r"\s+", " ", l).strip(" ,;") for l in text.splitlines()]
    lines = [l for l in lines if l]
    if len(lines) > MAX_LINES:
        raise ReaderError(f"That has {len(lines)} lines. Paste one verse at a time, up to {MAX_LINES} lines.")
    if not any(re.search(r"[a-zāīūṛṝḷṃḥśṣṭḍṇñṅ]", l) for l in lines):
        raise ReaderError("That doesn't look like Sanskrit in Devanagari or IAST.")
    return lines


def parse_model_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ReaderError("The model's answer was not in the expected format. Try again.")
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise ReaderError("The model's answer was not valid JSON. Try again.") from e


def to_claim(w: dict) -> dict:
    pos = str(w.get("pos") or "").lower().strip()
    upos = UPOS.get(pos, "ADV")
    feats = {}
    case = CASE.get(str(w.get("case") or "").lower())
    if case:
        feats["Case"] = case
    if NUMBER.get(str(w.get("number") or "").lower()):
        feats["Number"] = NUMBER[str(w["number"]).lower()]
    if GENDER.get(str(w.get("gender") or "").lower()):
        feats["Gender"] = GENDER[str(w["gender"]).lower()]
    if pos == "verb":
        tm = TENSE.get(str(w.get("tense_mood") or "").lower())
        if tm:
            feats["Tense"], feats["Mood"] = tm
        if str(w.get("person") or "") in ("1", "2", "3"):
            feats["Person"] = str(w["person"])
        if str(w.get("voice") or "").lower() == "passive":
            feats["Voice"] = "Pass"
        feats.pop("Case", None)
        feats.pop("Gender", None)
    if pos in VERBFORM:
        feats["VerbForm"] = VERBFORM[pos]
    form = to_iast_text(str(w.get("form") or "")).strip()
    lemma = to_iast_text(str(w.get("lemma") or "")).strip().lstrip("√").replace("-", "")
    return {"form": form, "lemma": lemma, "upos": upos, "feats": feats}


def _letters(s: str) -> str:
    """Spelling used to compare the model's chunks with the input."""
    slp = verify.to_slp1(s)
    slp = re.sub(r"[^A-Za-z~\\^]", "", slp)
    return verify.canon(slp.replace("M", "m"))


def read(raw: str, ask_model) -> dict:
    lines = clean_input(raw)
    text = "\n".join(lines)
    data = parse_model_json(ask_model(PROMPT.format(text=text)))
    chunks = data.get("chunks") or []
    if not chunks:
        raise ReaderError("The model returned no analysis. Try again.")

    words, stats = [], {"agree": 0, "form-known": 0, "unknown": 0, "not-checked": 0}
    derivs = {}
    for ci, ch in enumerate(chunks):
        surface = to_iast_text(str(ch.get("surface") or ""))
        members = ch.get("words") or []
        for w in members:
            claim = to_claim(w)
            if not claim["form"]:
                continue
            r = verify.check(claim)
            status = r["status"]
            stats[status] = stats.get(status, 0) + 1
            label = labels.describe(claim["upos"], claim["feats"])
            out = {"f": claim["form"], "d": transliterate(claim["form"], Scheme.Iast, Scheme.Devanagari),
                   "l": claim["lemma"], "sa": label["sa"], "en": label["en"], "s": status,
                   "gloss": str(w.get("gloss") or "")[:120], "k": f"c{ci}"}
            if len(members) > 1:
                out["g"] = surface
            if status == "form-known":
                out["alt"] = r["alternatives"][:4]
            if status == "agree":
                ev = r["entry"]
                verbal = claim["upos"] == "VERB" and (ev["kind"] == "tinanta" or ev.get("krdanta"))
                nominal = (claim["upos"] in ("NOUN", "ADJ", "PRON") and ev["kind"] == "subanta"
                           and not ev.get("krdanta") and not ev.get("avyaya"))
                if verbal or nominal:
                    d = verify.derivation(ev, claim["form"])
                    if d and "steps" in d[0]:
                        key = f"x{len(derivs)}"
                        derivs[key] = {"f": d[0]["form"], "s": [
                            [s["sutra"], s["text"], s["result"],
                             transliterate(s["result_slp"].replace("\\", "").replace("^", ""),
                                           Scheme.Slp1, Scheme.Devanagari)]
                            for s in d[0]["steps"]]}
                        out["x"] = key
            words.append(out)

    # Did the model's chunks reproduce the pasted text? If not, its word
    # split cannot be trusted as a reading of this text.
    given = _letters("".join(lines))
    covered = _letters("".join(to_iast_text(str(c.get("surface") or "")) for c in chunks))
    coverage = "exact" if given == covered else "differs"

    m = meter.identify(lines) if len(lines) in (2, 4) else {"name": "unidentified"}
    scan = ([p["weights"] for p in m["padas"]] if m.get("padas")
            else ["".join(x[1] for x in meter.weights(l)) for l in lines])
    checkable = stats["agree"] + stats["form-known"] + stats["unknown"]
    return {
        "iast": lines,
        "dev": [transliterate(l, Scheme.Iast, Scheme.Devanagari) for l in lines],
        "chunks": [to_iast_text(str(c.get("surface") or "")) for c in chunks],
        "w": words, "derivs": derivs, "coverage": coverage,
        "m": [m["name"], m.get("variant")], "scan": scan,
        "translation": str(data.get("translation") or "")[:400],
        "stats": {**stats, "checkable": checkable},
    }


def joins(result: dict):
    """How the words join, traced with Vidyut's sandhi table over the model's
    split, in the shape the Library uses: {"c": [chunk, ...], "p": 1 if some
    joins couldn't be traced}. None when the model's chunks don't follow the
    printed words, so its split can't be laid over the line."""
    chunks = result.get("chunks") or []
    by_chunk = {}
    for w in result.get("w") or []:
        by_chunk.setdefault(int(str(w.get("k", "c-1"))[1:]), []).append(w["f"])
    out, partial, ci = [], False, 0
    for line in result.get("iast") or []:
        toks = line.split(" ")
        if ci + len(toks) > len(chunks) or any(
                _letters(t) != _letters(chunks[ci + i]) for i, t in enumerate(toks)):
            return None
        words, groups = [], []
        for i in range(len(toks)):
            for f in by_chunk.get(ci + i, []):
                words.append(f)
                groups.append(i)
        ci += len(toks)
        if len(words) < 2:
            continue
        try:
            parts, complete = sandhi.trace(words, groups, line)
        except Exception:
            parts, complete = [], False
        partial |= not complete
        for ws, gs, ln, js in parts:
            out += sandhi.render(ws, gs, ln, js)
    return {"c": out, **({"p": 1} if partial else {})}

