"""Run a model over the benchmark. Standard library only.

    export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY / GEMINI_API_KEY / OPENROUTER_API_KEY
    python bench/run.py --provider anthropic --model <model-id>
    python bench/run.py --provider openai    --model <model-id>
    python bench/run.py --provider google    --model <model-id>
    python bench/run.py --provider openrouter --model <vendor/model-id>

Results go to bench/results/<provider>__<model>.jsonl. Re-running resumes:
items already answered are skipped. Then:

    python bench/grade.py bench/results/*.jsonl
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SYSTEM = ("You are being evaluated on Sanskrit grammar. Follow the answer "
          "format exactly and output only the requested JSON.")


def _post(url, headers, body, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"content-type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def call_anthropic(model, prompt, a):
    body = {"model": model, "max_tokens": a.max_tokens, "system": SYSTEM,
            "messages": [{"role": "user", "content": prompt}]}
    if a.temperature is not None:
        body["temperature"] = a.temperature
    r = _post("https://api.anthropic.com/v1/messages",
              {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
               "anthropic-version": "2023-06-01"}, body)
    return "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")


def _openai_compatible(url, key, model, prompt, a):
    body = {"model": model,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": prompt}]}
    if a.temperature is not None:
        body["temperature"] = a.temperature
    r = _post(url, {"authorization": f"Bearer {key}"}, body)
    return r["choices"][0]["message"]["content"]


def call_openai(model, prompt, a):
    return _openai_compatible("https://api.openai.com/v1/chat/completions",
                              os.environ["OPENAI_API_KEY"], model, prompt, a)


def call_openrouter(model, prompt, a):
    return _openai_compatible("https://openrouter.ai/api/v1/chat/completions",
                              os.environ["OPENROUTER_API_KEY"], model, prompt, a)


def call_google(model, prompt, a):
    key = os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"]
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if a.temperature is not None:
        body["generationConfig"] = {"temperature": a.temperature}
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              {"x-goog-api-key": key}, body)
    parts = r["candidates"][0]["content"].get("parts", [])
    return "".join(p.get("text", "") for p in parts)


PROVIDERS = {"anthropic": call_anthropic, "openai": call_openai,
             "google": call_google, "openrouter": call_openrouter}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True, choices=PROVIDERS)
    ap.add_argument("--model", required=True)
    ap.add_argument("--bench", default=os.path.join(ROOT, "bench/data/v0.jsonl"))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--temperature", type=float, default=None,
                    help="omit for the provider default (some reasoning models reject it)")
    ap.add_argument("--limit", type=int, default=None, help="first N items, for a smoke test")
    a = ap.parse_args()

    items = [json.loads(l) for l in open(a.bench, encoding="utf-8")]
    if a.limit:
        items = items[:a.limit]
    os.makedirs(os.path.join(ROOT, "bench/results"), exist_ok=True)
    out_path = os.path.join(ROOT, "bench/results",
                            f"{a.provider}__{a.model.replace('/', '_')}.jsonl")
    done = set()
    if os.path.exists(out_path):
        done = {r["id"] for r in map(json.loads, open(out_path, encoding="utf-8"))
                if r.get("output") is not None}
    todo = [it for it in items if it["id"] not in done]
    print(f"{len(todo)} to run, {len(done)} already done -> {out_path}")

    lock, call = threading.Lock(), PROVIDERS[a.provider]

    def work(it):
        for attempt in range(5):
            try:
                t0 = time.time()
                out = call(a.model, it["prompt"], a)
                rec = {"id": it["id"], "output": out, "latency_s": round(time.time() - t0, 2),
                       "provider": a.provider, "model": a.model}
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                    time.sleep(2 ** attempt * 3)
                    continue
                rec = {"id": it["id"], "output": None, "error": f"HTTP {e.code}: {msg}"}
                break
            except Exception as e:  # network hiccup; retry
                if attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                rec = {"id": it["id"], "output": None, "error": repr(e)}
        with lock:
            with open(out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    errors = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for i, rec in enumerate(ex.map(work, todo), 1):
            errors += int(rec.get("output") is None)
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} (errors: {errors})", flush=True)
    if errors:
        print(f"{errors} items failed; re-run the same command to retry them.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
