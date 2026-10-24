"""POST /api/read  {"text": "<a verse in Devanagari or IAST>"}
POST /api/read  {"text": "...", "task": "rasa"}   the verse's rasa (engine/rasa.py)

A language model proposes the word-by-word analysis; Vidyut checks each word
against Pāṇini's rules (engine/reader.py). Results are cached by text, and
calls are limited per network and per day, because each one costs a model call.

Env:
  OPENROUTER_API_KEY                         required
  READER_MODEL                               default model, google/gemini-3.8-flash
  READER_MODELS                              comma-separated models people may pick;
                                             default: the five models on the leaderboard
  READER_DAILY_CAP                           default 500 model calls a day
  READER_PER_HOUR                            default 10 new readings per network per hour
  UPSTASH_REDIS_REST_URL / _TOKEN            required (or KV_REST_API_URL / _TOKEN)
"""
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Vidyut's data is not in the repository; fetch it once per cold start.
if not os.environ.get("VIDYUT_DATA"):
    local = os.path.join(ROOT, "vidyut-data")
    os.environ["VIDYUT_DATA"] = local if os.path.isdir(local) else "/tmp/vidyut-data"
from engine import fetch_data  # noqa: E402

fetch_data.ensure(os.environ["VIDYUT_DATA"])
from engine import rasa, reader  # noqa: E402

MODEL = os.environ.get("READER_MODEL", "google/gemini-3.8-flash")
MODELS = [m.strip() for m in os.environ.get("READER_MODELS", ",".join([
    "google/gemini-3.8-flash", "anthropic/claude-opus-5.5", "anthropic/claude-sonnet-5.5",
    "google/gemini-4-argon", "openai/gpt-6-sol"])).split(",") if m.strip()]
if MODEL not in MODELS:
    MODELS.insert(0, MODEL)
DAILY_CAP = int(os.environ.get("READER_DAILY_CAP", "500"))
PER_IP_PER_HOUR = int(os.environ.get("READER_PER_HOUR", "10"))  # new readings; saved ones are free
CACHE_DAYS = 30
RASA_VERSION = "a1"  # the rasa prompt's version, separate from the reading's
VERSION = "r1"  # bump when the prompt or checks change, so old answers are not reused
REDIS_URL = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
REDIS_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")


def _post(url, payload, headers, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def redis(*commands):
    out = _post(f"{REDIS_URL}/pipeline", list(commands),
                {"Authorization": f"Bearer {REDIS_TOKEN}"}, 10)
    for x in out:
        if x.get("error"):
            raise RuntimeError(x["error"])
    return [x.get("result") for x in out]


def ask_model(prompt: str, model: str = MODEL) -> str:
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 12000}
    # No temperature or response_format: some models on the list reject them,
    # and reader.parse_model_json already copes with fenced or wrapped JSON.
    r = _post("https://openrouter.ai/api/v1/chat/completions", body,
              {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
               "HTTP-Referer": "https://samskritam.ai", "X-Title": "Samskritam.ai reader"}, 52)
    return r["choices"][0]["message"]["content"] or ""


class handler(BaseHTTPRequestHandler):
    def _send(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        # The models a reader may choose from; the page labels them from the leaderboard.
        return self._send(200, {"ok": True, "models": MODELS, "default": MODEL})

    def do_POST(self):
        missing = [name for name, ok in (("database (Upstash)", REDIS_URL and REDIS_TOKEN),
                                          ("model key (OPENROUTER_API_KEY)", os.environ.get("OPENROUTER_API_KEY")))
                   if not ok]
        if missing:
            return self._send(503, {"ok": False, "error": "The reader is not connected yet: missing "
                                    + " and ".join(missing) + "."})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 8000)) or b"{}")
            raw = str(body.get("text") or "")
            model = str(body.get("model") or MODEL)
            task = "rasa" if body.get("task") == "rasa" else "read"
            if model not in MODELS:
                return self._send(400, {"ok": False, "error": "That model isn't available here."})
            lines = reader.clean_input(raw)
        except reader.ReaderError as e:
            return self._send(400, {"ok": False, "error": str(e)})
        except Exception:
            return self._send(400, {"ok": False, "error": "Send JSON like {\"text\": \"...\"}."})

        prefix = "reader:" + VERSION if task == "read" else "rasa:" + RASA_VERSION
        key = prefix + ":" + hashlib.sha256(
            (model + "\n" + "\n".join(lines)).encode()).hexdigest()[:32]
        try:
            (cached,) = redis(["GET", key])
            if cached:
                return self._send(200, {"ok": True, "cached": True, **json.loads(cached)})
            ip = (self.headers.get("x-forwarded-for") or "unknown").split(",")[0].strip()
            day = time.strftime("%Y%m%d", time.gmtime())
            rl = f"reader:rl:{ip}" if task == "read" else f"rasa:rl:{ip}"
            hits, _, today, _ = redis(["INCR", rl], ["EXPIRE", rl, 3600, "NX"],
                                      ["INCR", f"reader:day:{day}"], ["EXPIRE", f"reader:day:{day}", 172800, "NX"])
        except Exception:
            return self._send(503, {"ok": False, "error": "The reader is unavailable. Try again shortly."})
        if hits > PER_IP_PER_HOUR:
            return self._send(429, {"ok": False, "error": f"That's {PER_IP_PER_HOUR} new readings this hour from your network, the hourly limit. Verses already read still open; try a new one in an hour."})
        if today > DAILY_CAP:
            return self._send(429, {"ok": False, "error": "The reader has reached today's limit. Try again tomorrow, or read the Gītā and Meghadūta on the home page."})

        try:
            run = reader.read if task == "read" else rasa.analyse
            result = run(raw, lambda p: ask_model(p, model))
        except reader.ReaderError as e:
            return self._send(422, {"ok": False, "error": str(e)})
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError):
            return self._send(502, {"ok": False, "error": "The model did not answer. Try again."})
        result["model"] = model
        try:
            redis(["SET", key, json.dumps(result, ensure_ascii=False), "EX", CACHE_DAYS * 86400])
        except Exception:
            pass
        return self._send(200, {"ok": True, "cached": False, **result})
