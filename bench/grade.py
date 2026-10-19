"""Grade model answers against benchmark items.

Answers are normalised before comparison: Devanagari or ISO 15919 input is
converted to IAST, and anusvāra vs homorganic nasal spellings
(saṃjaya / sañjaya) are treated as equal. Nothing else is forgiven.

    python bench/grade.py bench/results/<model>.jsonl
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
LEMMA_EQUIV = {"tvad": {"yuṣmad", "tvam"}, "mad": {"asmad", "aham"},
               "tad": {"sa", "saḥ"}, "idam": {"ayam"}, "etad": {"eṣa", "eṣaḥ"},
               "ka": {"kim"}}

PAST = {"past", "aorist", "imperfect", "perfect"}


NOMINAL = {"noun", "adjective", "pronoun"}


def _field_ok(field, model_v, gold_v, lemma=None):
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
    return mv == str(gold_v).lower()


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
    if task == "gita":
        gold = item["accept"][0]
        lem = lemma_equal(ans.get("lemma"), gold["lemma"]) or \
            str(ans.get("lemma", "")).strip() in LEMMA_EQUIV.get(gold["lemma"], set())
        fields = {k: _field_ok(k, ans.get(k), gold.get(k), gold["lemma"])
                  for k in ("pos", "case", "number", "gender", "tense_mood",
                            "person", "voice")}
        return {"correct": lem and all(fields.values()), "lemma": lem,
                "grammar": all(fields.values()), "fields": fields}
    if task == "meter":
        gold = item["accept"][0]
        got = re.sub(r"[^GL]", "", str(ans.get("pattern", "")).upper())
        if len(got) != len(gold):
            return {"correct": False, "reason": f"length {len(got)} != {len(gold)}"}
        skip = set(item["meta"].get("anceps", []))
        ok = all(g == w for i, (g, w) in enumerate(zip(got, gold)) if i not in skip)
        return {"correct": ok}
    raise ValueError(task)


def score(items: dict, results: list) -> dict:
    by_task = defaultdict(lambda: [0, 0])
    for r in results:
        it = items[r["id"]]
        g = grade_item(it, r.get("output"))
        r["grade"] = g
        by_task[it["task"]][0] += int(g["correct"])
        by_task[it["task"]][1] += 1
    total = [sum(v[0] for v in by_task.values()), sum(v[1] for v in by_task.values())]
    return {"by_task": {k: {"correct": c, "n": n, "acc": round(c / n, 4)}
                        for k, (c, n) in sorted(by_task.items())},
            "overall": {"correct": total[0], "n": total[1],
                        "acc": round(total[0] / total[1], 4) if total[1] else 0}}


def load_items(path):
    with open(path, encoding="utf-8") as f:
        return {it["id"]: it for it in map(json.loads, f)}


if __name__ == "__main__":
    bench = os.path.join(ROOT, "bench/data/v0.jsonl")
    items = load_items(bench)
    for path in sys.argv[1:]:
        latest = {}
        with open(path, encoding="utf-8") as f:
            for r in map(json.loads, f):  # retries append; keep the last answer
                if r.get("output") is not None or r["id"] not in latest:
                    latest[r["id"]] = r
        results = list(latest.values())
        print(os.path.basename(path), json.dumps(score(items, results), indent=1))
