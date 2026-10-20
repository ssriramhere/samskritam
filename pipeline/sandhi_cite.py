"""AI sūtra citations for each junction type found by build_sandhi.py.
Standard library only.

Each junction type (for example a + a -> ā) is sent with up to three examples
from the texts. The model names the Aṣṭādhyāyī sūtras that produce the join,
in order, with the junction after each step. Every cited number is checked
against Vidyut's sūtrapāṭha (web/data/sutras.json); a citation with an unknown
number is asked for again once, then kept and marked. The site labels these
as the model's citations; readers can suggest corrections.

    export OPENROUTER_API_KEY=...
    python pipeline/sandhi_cite.py                     # default model
    python pipeline/sandhi_cite.py --limit 5           # try a few first

Writes web/data/sandhi-rules.json. Re-running resumes.
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, wait

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SLP_IAST = {"A": "ā", "I": "ī", "U": "ū", "f": "ṛ", "F": "ṝ", "x": "ḷ", "X": "ḹ", "E": "ai", "O": "au",
            "M": "ṃ", "H": "ḥ", "~": "m̐", "K": "kh", "G": "gh", "N": "ṅ", "C": "ch", "J": "jh", "Y": "ñ",
            "w": "ṭ", "W": "ṭh", "q": "ḍ", "Q": "ḍh", "R": "ṇ", "T": "th", "D": "dh", "P": "ph", "B": "bh",
            "S": "ś", "z": "ṣ"}


def iast(slp):
    return "".join(SLP_IAST.get(c, c) for c in slp)


PROMPT = """You are a Pāṇinian grammarian. Explain one kind of external sandhi (the join
between two words, or between members of a compound) with the sūtras of the
Aṣṭādhyāyī.

The join: a word ending in "-{fa}" meets a word beginning with "{ib}-", and the
result is "{res}". (A final -s or -r here stands for the visarga of the word as
cited alone; a space in the result means the words stay apart.)

Examples from the texts:
{examples}

Give:
- why: one plain-English sentence a beginner can follow, describing what changes.
- steps: the sūtras that apply, in the order they apply, using standard
  adhyāya.pāda.sūtra numbers (e.g. 6.1.77). Include each sūtra that changes a
  sound, and the sūtra that blocks a change where that is the point of the
  join. No vārttikas or paribhāṣās. For each step give the junction after that
  sūtra applies, written like the result above (e.g. "aru a", then "a u a").

Answer with JSON only:
{{"why": "...", "steps": [{{"sutra": "8.2.66", "result": "..."}}]}}"""


def ask(model, prompt, provider=None):
    body = {"model": model, "max_tokens": 4000, "messages": [{"role": "user", "content": prompt}]}
    if provider:
        # OpenRouter routing: try these providers first (e.g. "anthropic").
        body["provider"] = {"order": [provider], "allow_fallbacks": False}
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                 "HTTP-Referer": "https://samskritam.ai", "X-Title": "Samskritam.ai sandhi"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    choice = resp["choices"][0]
    text = choice["message"].get("content") or ""
    if isinstance(text, list):  # some providers return content parts
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    m = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", text), re.S)
    if not m:
        raise RuntimeError(f"no JSON (finish_reason={choice.get('finish_reason')}, provider={resp.get('provider')}): {text[:200]!r}")
    try:
        d = json.loads(m.group())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"bad JSON: {m.group()[:200]!r}") from e
    steps = [[str(s.get("sutra", "")).strip(), str(s.get("result", "")).strip()] for s in d.get("steps") or []]
    if not d.get("why") or not steps:
        raise RuntimeError("empty answer")
    return str(d["why"]).strip(), steps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-opus-5.5")
    ap.add_argument("--rpm", type=float, default=18)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--provider", default=None,
                    help="OpenRouter provider to use only, e.g. anthropic (see the model's page on openrouter.ai)")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY first.")
    types = json.load(open(os.path.join(ROOT, "data/build/sandhi-types.json"), encoding="utf-8"))
    sutras = json.load(open(os.path.join(ROOT, "web/data/sutras.json"), encoding="utf-8"))
    out_path = os.path.join(ROOT, "web/data/sandhi-rules.json")
    out = {"model": a.model, "r": {}}
    if os.path.exists(out_path):
        old = json.load(open(out_path, encoding="utf-8"))
        if old.get("model") == a.model:
            out = old
    todo = [k for k in types if k not in out["r"]][:a.limit]
    print(f"{len(todo)} junction types to cite, {len(out['r'])} done, model {a.model}")
    lock, pace_lock, next_slot, errors = threading.Lock(), threading.Lock(), [time.monotonic()], []

    def pace():
        with pace_lock:
            w = next_slot[0] - time.monotonic()
            next_slot[0] = max(next_slot[0], time.monotonic()) + 60 / a.rpm
        if w > 0:
            time.sleep(w)

    def work(key):
        fa, ib, res = key.split("|")
        ex = "\n".join(f"- {l} + {r} -> {j}  ({ref})" for l, r, j, ref in types[key]["ex"])
        prompt = PROMPT.format(fa=iast(fa), ib=iast(ib), res=iast(res), examples=ex)
        got = None
        for attempt in range(6):
            pace()
            try:
                why, steps = ask(a.model, prompt, a.provider)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 5:
                    time.sleep(int(e.headers.get("Retry-After") or 10 * (attempt + 1)))
                    continue
                errors.append((key, repr(e)))
                return
            except Exception as e:
                if "content_filter" in str(e) and "Examples from the texts" in prompt:
                    # The filter answers the same way every time, so retrying is
                    # pointless. Ask once more about the join alone, without the
                    # example words, which are the likeliest trigger.
                    prompt = re.sub(r"Examples from the texts:\n.*?\n\n", "", prompt, flags=re.S)
                    continue
                if attempt < (0 if "content_filter" in str(e) else 5):
                    continue
                errors.append((key, repr(e)))
                return
            bad = [c for c, _ in steps if c not in sutras]
            got = (why, steps, bad)
            if not bad:
                break
            # one more try, telling the model which numbers don't exist
            prompt += f"\n\nNote: {', '.join(bad)} is not a sūtra number in the Aṣṭādhyāyī. Check the numbering."
        why, steps, bad = got
        rec = {"why": why, "s": [[c, sutras.get(c, ""), r] for c, r in steps]}
        if bad:
            rec["bad"] = bad
        with lock:
            out["r"][key] = rec
            if len(out["r"]) % 10 == 0:
                save(out_path, out)
                print(f"  {len(out['r'])}/{len(types)}")

    ex = ThreadPoolExecutor(a.workers)
    futures = [ex.submit(work, k) for k in todo]
    try:
        while wait(futures, timeout=1).not_done:
            pass
    except KeyboardInterrupt:
        with lock:
            save(out_path, out)
        print(f"\nStopped. {len(out['r'])}/{len(types)} saved; run the same command to continue.")
        os._exit(1)
    ex.shutdown()
    save(out_path, out)
    flagged = [k for k, v in out["r"].items() if v.get("bad")]
    print(f"{len(out['r'])}/{len(types)} cited -> {out_path}; {len(flagged)} with a sūtra number not found")
    for k, err in errors:
        print("  failed", k, err, "(re-run to retry)")


def save(path, out):
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".part", path)


if __name__ == "__main__":
    main()
