"""Meter identification for verse lines.

Syllable weights come from vidyut.chandas. Vidyut's own classifier handles
fixed-pattern vṛttas but does not recognise the anuṣṭubh śloka (whose
pattern is a set of positional constraints), so the śloka and triṣṭubh
checks are implemented here from the standard definitions.
"""
from __future__ import annotations

import os
from functools import lru_cache

from vidyut.chandas import Chandas

from .verify import DATA, to_slp1


@lru_cache(maxsize=1)
def chandas() -> Chandas:
    return Chandas(os.path.join(DATA, "chandas", "meters.tsv"))


def weights(line_iast: str) -> list[tuple[str, str]]:
    """[(syllable, 'G'|'L'), ...] for one line, ignoring spaces and avagraha."""
    slp = to_slp1(line_iast).replace("'", "").replace(" ", "")
    for ch in ",.|।॥-":
        slp = slp.replace(ch, "")
    m = chandas().classify(slp)
    if not m.aksharas:
        return []
    return [(a.text, a.weight) for row in m.aksharas for a in row]


def _split(sylls: list, n: int) -> list[list]:
    return [sylls[i:i + n] for i in range(0, len(sylls), n)]


def _sloka_pada(p: list, even: bool) -> str | None:
    """Return 'pathyā', 'vipulā' or None for one 8-syllable pāda."""
    w = [x[1] for x in p]
    if len(w) != 8:
        return None
    if w[1] == "L" and w[2] == "L":     # 2nd and 3rd may not both be light
        return None
    if even:
        return "pathyā" if (w[4], w[5], w[6]) == ("L", "G", "L") else None
    if (w[4], w[5], w[6]) == ("L", "G", "G"):
        return "pathyā"
    return "vipulā"                      # odd pādas admit the vipulā variants


def identify(half_lines: list[str]) -> dict:
    """Identify the meter of a verse given its half-verse lines."""
    sylls = [weights(h) for h in half_lines]
    counts = [len(s) for s in sylls]
    if counts and all(c == 16 for c in counts):
        padas = [p for s in sylls for p in _split(s, 8)]
        kinds = [_sloka_pada(p, i % 2 == 1) for i, p in enumerate(padas)]
        if all(kinds):
            variant = "vipulā" if "vipulā" in kinds else "pathyā"
            return {"name": "anuṣṭubh", "variant": variant,
                    "padas": _render(padas), "check": "rule"}
    if counts and all(c == 22 for c in counts):
        padas = [p for s in sylls for p in _split(s, 11)]
        names = [_tristubh_pada(p) for p in padas]
        kinds = set(names)
        if kinds <= {"indravajrā"}:
            variant = "indravajrā"
        elif kinds <= {"upendravajrā"}:
            variant = "upendravajrā"
        elif kinds <= {"indravajrā", "upendravajrā"}:
            variant = "upajāti"
        else:
            variant = "mixed (ārṣa)"
        return {"name": "triṣṭubh", "variant": variant, "pada_meters": names,
                "padas": _render(padas), "check": "rule"}
    # Hypermetric verses: a 9-syllable śloka pāda, or a 12-syllable
    # (jagatī) pāda inside triṣṭubh. These are features of the epic text.
    if counts and all(c in (16, 17) for c in counts):
        return {"name": "anuṣṭubh", "variant": "hypermetric pāda",
                "syllables": counts, "check": "count-only"}
    if counts and all(c in (22, 23, 24) for c in counts):
        return {"name": "triṣṭubh", "variant": "with jagatī pāda",
                "syllables": counts, "check": "count-only"}
    m = chandas().classify("\n".join(to_slp1(h).replace("'", "")
                                     for h in half_lines))
    name = m.padya if isinstance(m.padya, str) else getattr(m.padya, "name", None)
    if name:
        from .verify import to_iast
        name = to_iast(name)
    return {"name": name or "unidentified", "variant": None,
            "syllables": counts, "check": "vidyut" if name else "none"}


# Common 11-syllable patterns (last syllable anceps, so 10 are compared).
_TRISTUBH = {"GGLGGLLGLG": "indravajrā", "LGLGGLLGLG": "upendravajrā",
             "GGGGLGGLGG": "śālinī", "GGGGLLGGLG": "vātormī"}


def _tristubh_pada(p: list) -> str:
    return _TRISTUBH.get("".join(x[1] for x in p[:10]), "other")


def _render(padas: list[list]) -> list[dict]:
    return [{"syllables": [x[0] for x in p],
             "weights": "".join(x[1] for x in p)} for p in padas]
