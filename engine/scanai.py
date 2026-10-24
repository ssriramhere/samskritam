"""AI scansion beside the rules: one model marks every syllable of a pasted
verse heavy or light and names the meter; Vidyut's meter module does the same
by rule, and the two are compared syllable by syllable.

The rules are the answer key here. The last syllable of each pāda may be
heavy or light in most meters, so a difference there is reported apart.

    result = scanai.compare(text, ask_model)   # ask_model(prompt) -> str
"""
from __future__ import annotations

import re
import unicodedata

from . import meter
from .reader import ReaderError, clean_input, parse_model_json

# The same wording as the benchmark's scan task (bench/v1/generate.py).
PROMPT = """Scan this verse:
  {text}
Give the weight of every syllable, line by line (a long vowel, anusvāra, visarga, or a following conjunct makes a syllable guru), and name the meter. Answer with JSON only: {{"lines": ["<one character per syllable of line 1: G guru, L laghu>", "<line 2>", ...], "meter": "<name of the meter>"}}"""

ALIASES = {"anustubh": {"sloka", "anustup", "anushtubh", "shloka"},
           "tristubh": {"tristup", "trishtubh", "upajati", "indravajra", "upendravajra"},
           "jagati": {"vamsastha", "drutavilambita", "upajati"}}


def _key(name) -> str:
    s = unicodedata.normalize("NFD", str(name or "").lower())
    return re.sub(r"[^a-z]", "", "".join(c for c in s if not unicodedata.combining(c)))


def meter_matches(ai, rule, variant=None) -> bool:
    a, r = _key(ai), _key(rule)
    if not a or not r or r == "unidentified":
        return False
    names = {r} | ALIASES.get(r, set()) | ({_key(variant)} if variant else set())
    return any(n and (a == n or a.startswith(n) or n in a) for n in names)


def rule_scan(lines):
    m = meter.identify(lines) if len(lines) in (2, 4) else {"name": "unidentified"}
    padas = ([p["weights"] for p in m["padas"]] if m.get("padas")
             else ["".join(x[1] for x in meter.weights(l)) for l in lines])
    return m, padas


def compare(raw: str, ask_model) -> dict:
    lines = clean_input(raw)
    data = parse_model_json(ask_model(PROMPT.format(text="\n  ".join(lines))))
    got = data.get("lines")
    if isinstance(got, str):
        got = [got]
    if not isinstance(got, list) or not got:
        raise ReaderError("The model's answer had no scansion. Try again.")
    ai = "".join(re.sub(r"[^GL]", "", str(l).upper()) for l in got)
    m, padas = rule_scan(lines)
    rules = "".join(padas)
    anceps, off = set(), 0
    for p in padas:
        off += len(p)
        if p:
            anceps.add(off - 1)
    out = {"model_lines": [re.sub(r"[^GL]", "", str(l).upper()) for l in got][:8],
           "padas": padas, "meter": [m["name"], m.get("variant")],
           "ai_meter": str(data.get("meter") or "")[:60],
           "total": len(rules), "ai_total": len(ai)}
    out["meter_ok"] = meter_matches(out["ai_meter"], m["name"], m.get("variant"))
    if len(ai) == len(rules):
        diff = [i for i, (a, r) in enumerate(zip(ai, rules)) if a != r]
        out["ai_padas"], k = [], 0
        for p in padas:
            out["ai_padas"].append(ai[k:k + len(p)])
            k += len(p)
        out["wrong"] = [i for i in diff if i not in anceps]
        out["anceps"] = [i for i in diff if i in anceps]
    return out
