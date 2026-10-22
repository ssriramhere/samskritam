"""Grade model answers against benchmark items.

Answers are normalised before comparison: Devanagari or ISO 15919 input is
converted to IAST, and anusvāra vs homorganic nasal spellings
(saṃjaya / sañjaya) are treated as equal. Nothing else is forgiven.

    python bench/grade.py bench/results/<model>.jsonl
    python bench/grade.py --bench bench/private/v1-pool.jsonl bench/results/<model>.v1-pool.jsonl
"""
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from vidyut.lipi import Scheme, detect, transliterate  # noqa: E402

from engine import verify  # noqa: E402


def extract_json(text: str):
    if text is None:
        return None
    text = re.sub(r"```(?:json)?", "", text)
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
    ans = extract_json(answer_text)
    task = item["task"]
    if ans is None:
        return {"correct": False, "reason": "no-json"}
    if task in ("tinanta", "subanta"):
        accept = {norm_form(a) for a in item["accept"]}
        raw = ans.get("form")
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
