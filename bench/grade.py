"""Grade model answers against benchmark items.

Answers are normalised before comparison: Devanagari or ISO 15919 input is
converted to IAST, and anusvāra vs homorganic nasal spellings
(saṃjaya / sañjaya) are treated as equal. Nothing else is forgiven.

    python bench/grade.py bench/results/<model>.jsonl
    python bench/grade.py --bench bench/private/v1-pool.jsonl bench/results/<model>.v1-pool.jsonl
"""
import json
from functools import lru_cache
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.lipi import Scheme, detect, transliterate  # noqa: E402

from engine import verify  # noqa: E402


def extract_json(text: str, nested: bool = False):
    if text is None:
        return None
    text = re.sub(r"```(?:json)?", "", text)
    if nested:  # answers with objects inside (v1 parse): the outermost {...}
        i, j = text.find("{"), text.rfind("}")
        if 0 <= i < j:
            try:
                return json.loads(text[i:j + 1])
            except json.JSONDecodeError:
                pass
    for m in re.finditer(r"\{[^{}]*\}", text, re.S):
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            continue
    return None


def norm_form(s) -> str:
    if not isinstance(s, str):
        return ""
    s = s.strip().strip(".,;:!?\"'।॥ ").replace("ṁ", "ṃ").replace("ḿ", "ṃ")
    if not s:
        return ""
    try:
        if detect(s) == Scheme.Devanagari:
            s = transliterate(s, Scheme.Devanagari, Scheme.Iast)
    except Exception:
        pass
    s = s.lower()
    return verify.canon(verify.to_slp1(s))


def lemma_equal(model: str, gold: str) -> bool:
    if not isinstance(model, str):
        return False
    m = model.strip().lstrip("√").split("(")[0].strip().replace("-", "")
    if norm_form(m) == norm_form(gold):
        return True
    claim = {"lemma": gold}
    try:
        return verify._lemma_ok(gold, norm_form(m)) or \
            norm_form(m) in verify.LEMMA_ALIASES.get(claim["lemma"], set())
    except Exception:
        return False


# DCS lemma conventions vs the citation forms most grammars use.
LEMMA_EQUIV = {"tvad": {"yuṣmad", "tvam"}, "mad": {"asmad", "aham"}, "pracch": {"prach"},
               "tad": {"sa", "saḥ"}, "idam": {"ayam"}, "etad": {"eṣa", "eṣaḥ"},
               "ka": {"kim"}}
LEMMA_EQUIV_V0 = {"tvad": {"yuṣmad", "tvam"}, "mad": {"asmad", "aham"},
               "tad": {"sa", "saḥ"}, "idam": {"ayam"}, "etad": {"eṣa", "eṣaḥ"},
               "ka": {"kim"}}

PAST = {"past", "aorist", "imperfect", "perfect"}


NOMINAL = {"noun", "adjective", "pronoun"}


OBLIQUE = {"ins", "dat", "abl", "gen", "loc"}


def _field_ok(field, model_v, gold_v, lemma=None, case=None):
    if gold_v is None:
        return True  # not applicable for this word; ignore what the model says
    if model_v is None:
        return False
    mv = str(model_v).strip().lower()
    if field == "tense_mood" and gold_v == "past":
        # vid has a present-meaning perfect, and Pāṇini derives vetti/vettha
        # as laṭ with perfect endings (vido laṭo vā, 3.4.83): accept both.
        return mv in PAST or (lemma == "vid" and mv == "present")
    if field == "pos" and gold_v in NOMINAL:
        # Only verb vs nominal is graded. The lines between noun, adjective
        # and pronominal adjective (para, sarva, anya) are conventions.
        return mv in NOMINAL
    if field == "gender" and case in OBLIQUE and {mv, str(gold_v)} <= {"m", "n"}:
        # Masculine and neuter forms are identical outside nom/acc/voc, and the
        # corpus often tags a neuter there as masculine (netrābhyām, mūleṣu).
        return True
    return mv == str(gold_v).lower()


def _lemma_ok(model, gold, gender=None):
    if lemma_equal(model, gold) or str(model or "").strip() in LEMMA_EQUIV.get(gold, set()):
        return True
    if not isinstance(model, str):
        return False
    m = model.strip()
    # A feminine noun cited by its feminine stem (ātmajā, sumadhyamā) or by the
    # masculine stem of the adjective it comes from.
    if gender == "f" and m[-1:] in ("a", "ā") and gold[-1:] in ("a", "ā") and m[:-1] == gold[:-1]:
        return True
    # Preverb + root written apart (pra-√nad, upa-i, ni-√grah): join them with sandhi.
    parts = [x for x in re.split(r"[-–\s√]+", m) if x]
    if len(parts) > 1:
        return any(lemma_equal(j, gold) for j in _joins(parts))
    return False


def _joins(parts):
    from engine import sandhi
    R = sandhi.rules()
    forms = {verify.to_slp1(parts[0])}
    for w in parts[1:]:
        nxt, new = verify.to_slp1(w), set()
        for acc in forms:
            new.add(acc + nxt)
            for res in R.get((acc[-1:], nxt[:1]), []):
                new.add(acc[:-1] + sandhi._clean(res) + nxt[1:])
            if "r" in acc and nxt[:1] == "n":
                new.add(acc + "R" + nxt[1:])  # ṇatva: pra + nad -> praṇad
        forms = new
    return [transliterate(f, Scheme.Slp1, Scheme.Iast) for f in forms]


def grade_item(item: dict, answer_text: str) -> dict:
    task = item["task"]
    ans = extract_json(answer_text, nested=task == "parse")
    if ans is None:
        return {"correct": False, "reason": "no-json"}
    if task in ("tinanta", "subanta", "generate"):
        accept = {norm_form(a) for a in item["accept"]}
        raw = ans.get("form")
        if task == "generate" and isinstance(raw, str):  # īpsāṃ cakratuḥ = īpsāñcakratuḥ
            raw = re.sub(r"(ām|āṃ|āñ|āṅ)\s+", r"āṃ", raw.strip())
        # "buddheḥ / buddhyāḥ": several forms count only if every one is right.
        parts = [p for p in re.split(r"\s*(?:/|,|\bor\b)\s*", raw)] if isinstance(raw, str) else [raw]
        parts = [p for p in parts if p]
        ok = bool(parts) and all(norm_form(p) in accept for p in parts)
        return {"correct": ok}
    if task == "analyze":
        got = {k: str(ans.get(k, "")).strip().lower().replace("ṅ", "n")
               for k in ("lakara", "purusha", "vacana")}
        return {"correct": any(got == a for a in item["accept"])}
    if task in ("gita", "context"):  # v1's context task uses v0's Gītā format
        gold = item["accept"][0]
        # v0 (gita) is graded exactly as published; the extra allowances are v1's.
        v1 = task == "context"
        lem = _lemma_ok(ans.get("lemma"), gold["lemma"], gold.get("gender")) if v1 else \
            lemma_equal(ans.get("lemma"), gold["lemma"]) or \
            str(ans.get("lemma", "")).strip() in LEMMA_EQUIV_V0.get(gold["lemma"], set())
        fields = {k: _field_ok(k, ans.get(k), gold.get(k), gold["lemma"], gold.get("case") if v1 else None)
                  for k in ("pos", "case", "number", "gender", "tense_mood",
                            "person", "voice")}
        return {"correct": lem and all(fields.values()), "lemma": lem,
                "grammar": all(fields.values()), "fields": fields}
    if task == "split":
        gold = item["accept"][0]
        got = ans.get("words")
        if not isinstance(got, list):
            return {"correct": False, "reason": "no word list"}
        got = [w for w in got if isinstance(w, str) and w.strip()]
        return {"correct": _split_ok(gold, got)}
    if task == "join":
        flat = lambda x: norm_form(re.sub(r"[\s'’ʼ‘-]", "", x if isinstance(x, str) else ""))
        return {"correct": flat(ans.get("form")) in {flat(a) for a in item["accept"]}}
    if task == "rule":
        need = set(item["accept"][0])
        got = ans.get("sutras")
        if not isinstance(got, list):
            return {"correct": False, "reason": "no sūtra list"}
        cited = {m.group(0) for x in got for m in [re.search(r"\d\.\d\.\d{1,3}", str(x))] if m}
        return {"correct": need <= cited, "missing": sorted(need - cited)}
    if task == "meter":
        gold = item["accept"][0]
        got = re.sub(r"[^GL]", "", str(ans.get("pattern", "")).upper())
        if len(got) != len(gold):
            return {"correct": False, "reason": f"length {len(got)} != {len(gold)}"}
        skip = set(item["meta"].get("anceps", []))
        ok = all(g == w for i, (g, w) in enumerate(zip(got, gold)) if i not in skip)
        return {"correct": ok}
    if task == "padapatha":
        got = ans.get("words")
        if not isinstance(got, list):
            return {"correct": False, "reason": "no word list"}
        got = [w.strip() for w in got if isinstance(w, str) and w.strip()]
        return {"correct": _pada_ok(item["accept"][0], got)}
    if task == "parse":
        gold, got = item["accept"][0], ans.get("words")
        words = item["meta"].get("words", [""] * len(gold))
        if not isinstance(got, list):
            return {"correct": False, "reason": "no word list", "right": 0, "n": len(gold)}
        got = [g for g in got if isinstance(g, dict)]
        used, right = set(), 0
        for i, (w, g) in enumerate(zip(words, gold)):
            # the entry that names this word, else the one in the same position
            k = next((j for j, a in enumerate(got) if j not in used and _fin(_flat(str(a.get("word", "")))) == _fin(_flat(w))), None)
            if k is None and i < len(got) and i not in used:
                k = i
            if k is not None:
                used.add(k)
            right += _parse_word_ok(got[k] if k is not None else {}, g, w)
        return {"correct": right == len(gold), "right": right, "n": len(gold)}
    if task == "scan":
        gold, anc = item["accept"][0], item["meta"].get("anceps", [])
        lines = ans.get("lines")
        if isinstance(lines, str):
            lines = [lines]
        if not isinstance(lines, list) or not lines:
            return {"correct": False, "reason": "no lines"}
        # Compare the whole verse: an answer may give one line per pāda or per half-verse.
        want = "".join(gold["lines"])
        got = "".join(re.sub(r"[^GL]", "", str(l).upper()) for l in lines)
        skip, off = set(), 0
        for i, line in enumerate(gold["lines"]):
            skip |= {off + j for j in (anc[i] if i < len(anc) else [])}
            off += len(line)
        lines_ok = len(got) == len(want) and all(g == w for j, (g, w) in enumerate(zip(got, want)) if j not in skip)
        meter_ok = _meter_name_ok(ans.get("meter"), gold["meter"], gold.get("variant"))
        return {"correct": lines_ok and meter_ok, "lines": lines_ok, "meter": meter_ok}
    if task == "recall":  # memorisation probe (bench/probe/): near-verbatim counts as recited
        sim = recall_similarity(item["accept"][0], ans.get("text"))
        return {"correct": sim >= 0.9, "similarity": round(sim, 3)}
    raise ValueError(task)


def recall_similarity(gold, got) -> float:
    """0..1 character similarity, ignoring spaces, punctuation, avagraha and
    anusvāra spelling (difflib ratio on canonical SLP1)."""
    import difflib
    if not isinstance(got, str):
        return 0.0
    flat = lambda x: norm_form(re.sub(r"[\s'’ʼ‘.,;:!?|।॥-]", "", x))
    return difflib.SequenceMatcher(None, flat(gold), flat(got)).ratio()


def _split_ok(gold, got):
    """Word by word, letting one answer word cover several consecutive key
    words: the corpus splits off a negative a- or a prefix like ati- that
    grammars write as part of the word (aparāṅmukhāḥ, atidīrgham)."""
    if not gold or not got:
        return not gold and not got
    if _same_word(gold[0], got[0]) and _split_ok(gold[1:], got[1:]):
        return True
    for k in range(2, len(gold) + 1):
        merged = "".join(w.rstrip("ḥ") for w in gold[:k - 1]) + gold[k - 1]
        if norm_form(merged) == norm_form(got[0]) and _split_ok(gold[k:], got[1:]):
            return True
    return False


def _parse_word_ok(ans: dict, gold: dict, word: str = "") -> bool:
    """One word of a parse question, with v1's allowances."""
    got = ans.get("lemma")
    lem = _lemma_ok(got, gold["lemma"], gold.get("gender"))
    if not lem and isinstance(got, str):
        g, m = _flat(gold["lemma"]).replace("M", "m"), _flat(got).replace("M", "m")
        # puṃs/pums; or the lemma of the whole compound the word ends (mahāratha for rathaḥ)
        lem = m == g or (len(m) > len(g) and m.endswith(g))
    def field_ok(k):
        if k == "gender" and gold.get("case") == "acc" and gold.get("number") == "sg" \
                and word.endswith("am") and {str(ans.get(k)).lower(), gold.get(k)} <= {"m", "n"}:
            return True  # vanam, sainyam: masculine and neuter accusatives are the same form
        return _field_ok(k, ans.get(k), gold.get(k), gold["lemma"], gold.get("case"))
    return lem and all(field_ok(k) for k in ("pos", "case", "number", "gender", "tense_mood", "person", "voice"))


def _flat(x) -> str:
    return norm_form(re.sub(r"[\s'’ʼ‘-]", "", x)) if isinstance(x, str) else ""


# Word-final sounds a pausa form may be written with: punar/punaḥ, tatas/tataḥ,
# tvac/tvak, tad/tat, dig/dik.
_FINAL = {"r": "H", "s": "H", "g": "k", "c": "k", "j": "k", "S": "k", "d": "t", "b": "p", "q": "w"}


def _fin(x: str) -> str:
    return x[:-1] + _FINAL[x[-1]] if x and x[-1] in _FINAL else x


@lru_cache(maxsize=20000)
def _joined(parts: tuple) -> frozenset:
    """Every way of joining these pieces with sandhi, normalised (plus plain concatenation)."""
    parts = tuple(p for p in parts if p)
    if not parts:
        return frozenset()
    outs = {"".join(parts)}
    if len(parts) > 1:
        outs |= set(_joins(list(parts)))
    return frozenset(_fin(_flat(o)) for o in outs)


def _ans_forms(w: str) -> frozenset:
    """A written answer word: hyphens may separate a compound's members."""
    return _joined(tuple(p for p in w.split("-")))


def _key_forms(e) -> frozenset:
    if isinstance(e, str):
        return _joined((e,))
    return frozenset({_fin(_flat(a)) for a in e["accept"]}) | _joined(tuple(e["members"]))


def _key_text(e) -> str:
    return e if isinstance(e, str) else e["accept"][0]


_JOINERS = {"a", "an", "su", "dus", "dur", "nis", "nir", "sa", "sam", "ati", "anu", "abhi", "pra", "pari", "vi", "ā"}


def _joins_on(e) -> bool:
    """A key entry the corpus split off that grammars write joined to the next word:
    a negative a-, or a prefix (also as the last member of a corpus compound: cāru-su + acchā)."""
    last = e if isinstance(e, str) else e["members"][-1]
    return last in _JOINERS


def _pada_ok(gold, got) -> bool:
    """Padapāṭha: every word, in order. A compound may be written whole (any
    joined spelling), with hyphens between members, or member by member; a word
    the corpus treats as one may be analysed with hyphens (siddha-ādeśān); a
    negative a- or a prefix the corpus splits off may stay attached; a
    periphrastic perfect may be written apart (prārthayām āsa); final r/s and
    visarga, and final stops, are spelled either way (punar/punaḥ, tvac/tvak)."""
    gold, got = list(gold), [w.strip() for w in got if w.strip()]

    @lru_cache(maxsize=None)
    def f(i, j):
        if i == len(gold):
            return j == len(got)
        if j == len(got):
            return False
        e, a = gold[i], got[j]
        if (_key_forms(e) & _ans_forms(a) or (isinstance(e, str) and _same_word(e, a))) and f(i + 1, j + 1):
            return True
        if not isinstance(e, str):  # member by member, as separate words
            k = len(e["members"])
            if len(got) - j >= k and all(_member_ok(m, p) for m, p in zip(e["members"], got[j:j + k])) and f(i + 1, j + k):
                return True
        for k in (2, 3):  # corpus pieces written as one word: a-paricita, cāru-su + acchā
            if i + k <= len(gold) and all(_joins_on(x) for x in gold[i:i + k - 1]):
                if _joined(tuple(_key_text(x) for x in gold[i:i + k])) & _ans_forms(a) and f(i + k, j + 1):
                    return True
        if j + 1 < len(got) and _flat(a).endswith("Am"):  # prārthayām āsa
            if _key_forms(e) & _joined((a, got[j + 1])) and f(i + 1, j + 2):
                return True
        return False

    return f(0, 0)


def _member_ok(member: str, got: str) -> bool:
    return _fin(_flat(member)) == _fin(_flat(got)) or _same_word(member, got)


def _meter_key(name) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


METER_ALIASES = {"anustubh": {"sloka", "anustup", "anushtubh", "shloka"},
                 "tristubh": {"tristup", "trishtubh"}}


def _meter_name_ok(got, gold, variant=None) -> bool:
    g, w = _meter_key(gold), _meter_key(got)
    if not w:
        return False
    # "anuṣṭubh (pathyā)" or "mandākrāntā meter": the name may come with extras
    names = {g} | METER_ALIASES.get(g, set())
    if variant and g == "tristubh":  # the triṣṭubh form may be named instead: upajāti, indravajrā
        names |= {_meter_key(variant)}
    return any(w == n or w.startswith(n) or n in w for n in names if n)


def _same_word(gold: str, got: str) -> bool:
    """Same word up to the spelling of its final sound: visarga or s, anusvāra
    or m, a final voiced or voiceless stop (kaścid / kaścit)."""
    try:
        if detect(got) == Scheme.Devanagari:
            got = transliterate(got, Scheme.Devanagari, Scheme.Iast)
    except Exception:
        pass
    got = got.strip().strip(".,;:!?\"'।॥ ").replace("ṁ", "ṃ").lower()
    return bool(set(map(verify.canon, verify.kosha_keys(gold))) & set(map(verify.canon, verify.kosha_keys(got))))


def score(items: dict, results: list) -> dict:
    by_task = defaultdict(lambda: [0, 0])
    for r in results:
        it = items[r["id"]]
        if it.get("meta", {}).get("dropped"):
            continue  # removed by hand review (bench/v1-key-fixes.json)
        g = grade_item(it, r.get("output"))
        r["grade"] = g
        by_task[it["task"]][0] += int(g["correct"])
        by_task[it["task"]][1] += 1
    total = [sum(v[0] for v in by_task.values()), sum(v[1] for v in by_task.values())]
    return {"by_task": {k: {"correct": c, "n": n, "acc": round(c / n, 4)}
                        for k, (c, n) in sorted(by_task.items())},
            "overall": {"correct": total[0], "n": total[1],
                        "no_answer": sum(r.get("output") is None for r in results),
                        "acc": round(total[0] / total[1], 4) if total[1] else 0}}


def load_items(path):
    with open(path, encoding="utf-8") as f:
        return {it["id"]: it for it in map(json.loads, f)}


if __name__ == "__main__":
    args = sys.argv[1:]
    bench = os.path.join(ROOT, "bench/data/v0.jsonl")
    if args[:1] == ["--bench"]:
        bench, args = args[1], args[2:]
    items = load_items(bench)
    for path in args:
        latest = {}
        with open(path, encoding="utf-8") as f:
            for r in map(json.loads, f):  # retries append; keep the last answer
                if r.get("output") is not None or r["id"] not in latest:
                    latest[r["id"]] = r
        results = list(latest.values())
        print(os.path.basename(path), json.dumps(score(items, results), indent=1))
