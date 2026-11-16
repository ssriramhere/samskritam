"""Make the Verse for Today reel for one verse of the text in web/data/today.json.

    python reels/make_reel.py 1.2            # writes web/reels/meghaduta-1.2.mp4 and .jpg

It reads the verse, its meter scan and translation from the site's data, and the
day's hook and word from web/data/today.json (both must be there). Narration is
an open-source voice (Kokoro, Apache-2.0) run locally; the music bed is a
synthesized drone until a real chant is available. Setup, once:

    cd reels && npm install          # fonts
    pip install kokoro-onnx soundfile numpy
    # Kokoro model files (kokoro-v1.0.onnx, voices-v1.0.bin) from
    # github.com/thewh1teagle/kokoro-onnx/releases, in reels/models/ or $KOKORO_DIR
"""
import json
import os
import re
import subprocess
import sys

import numpy as np
import soundfile as sf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WEB = os.path.join(ROOT, "web")
VOICE = os.environ.get("REEL_VOICE", "af_heart")
PADA_S = 4.0  # seconds per pāda in the verse scene


def syllables(word: str) -> int:
    return len(re.findall(r"ai|au|[aāiīuūṛṝḷeo]", word.lower())) or 1


def split_at(word: str, n: int):
    """Split a printed (sandhi-joined) word after its n-th syllable; the consonant
    that follows the vowel goes with the first part (hetor | antar...)."""
    vowels = list(re.finditer(r"ai|au|[aāiīuūṛṝḷeo]", word))
    end = vowels[n - 1].end()
    if end < len(word) and word[end] in "ṃḥ":
        end += 1
    if end < len(word) and not re.match(r"ai|au|[aāiīuūṛṝḷeo]", word[end:]):
        end += 1
    return word[:end], word[end:]


def deva(iast: str) -> str:
    from vidyut.lipi import Scheme, transliterate
    return transliterate(iast, Scheme.Iast, Scheme.Devanagari)


def speakable(s: str) -> str:
    """IAST to something an English voice says sensibly."""
    for a, b in [("kṣ", "ksh"), ("ṣ", "sh"), ("ś", "sh"), ("ṛ", "ri"), ("ṝ", "ri"), ("ā", "a"), ("ī", "i"), ("ū", "u"),
                 ("ṭ", "t"), ("ḍ", "d"), ("ṇ", "n"), ("ñ", "n"), ("ṅ", "n"), ("ṃ", "m"), ("ḥ", "h"), ("Ā", "A"), ("Ś", "Sh"),
                 ("Ṣ", "Sh"), ("Ī", "I"), ("Ū", "U"), ("samskritam.ai", "samskritam dot AI")]:
        s = s.replace(a, b)
    return s


def split_translation(t: str):
    if "; " in t:
        a, b = t.split("; ", 1)
        return a.rstrip(",;") + ".", b[0].upper() + b[1:]
    parts = re.split(r"(?<=[.?!])\s+", t)
    if len(parts) > 1:
        h = len(parts) // 2
        return " ".join(parts[:h]), " ".join(parts[h:])
    return t, ""


def tts(kokoro, text):
    s, sr = kokoro.create(speakable(text), voice=VOICE, speed=0.95, lang="en-us")
    return s, sr


def main():
    vid = sys.argv[1]
    cfg = json.load(open(os.path.join(WEB, "data/today.json"), encoding="utf-8"))
    slug = cfg["text"]
    day = cfg["days"].get(vid) or sys.exit(f"web/data/today.json has no entry for {vid}: add its hook and word first")
    idx = json.load(open(os.path.join(WEB, f"data/{slug}/index.json"), encoding="utf-8"))
    order = [f"{c['id']}.{i + 1}" for c in idx["chapters"] for i in range(c["n"])]
    ch = vid.rsplit(".", 1)[0]
    v = next(x for x in json.load(open(os.path.join(WEB, f"data/{slug}/{ch}.json"), encoding="utf-8"))["verses"] if x["id"] == vid)
    tr = json.load(open(os.path.join(WEB, f"data/{slug}/{ch}-translations.json"), encoding="utf-8"))["t"][vid]
    t1, t2 = split_translation(tr)

    # Pādas: each printed half-line holds two; pb gives the last token of the first.
    padas = []
    for k, line in enumerate(v["lt"]):
        pb = (v.get("pb") or [[]] * len(v["lt"]))[k]
        if pb:
            cut = pb[0] + 1
        else:  # no recorded break: cut where the first pāda's syllables run out
            want, acc, cut = len(v["scan"][2 * k]) if len(v["scan"]) > 2 * k else 0, 0, len(line)
            for j, tok in enumerate(line):
                n = syllables(tok[0])
                if acc + n > want and acc < want:  # the printed word runs across the break: split it there
                    first, rest = split_at(tok[0], want - acc)
                    line = line[:j] + [[first, deva(first)], [rest, deva(rest)]] + line[j + 1:]
                    cut = j + 1
                    break
                acc += n
                if acc >= want:
                    cut = j + 1
                    break
        for j, toks in enumerate((line[:cut], line[cut:])):
            if toks:
                padas.append({"i": [t[0] for t in toks], "d": [t[1] for t in toks],
                              "n": [syllables(t[0]) for t in toks], "m": v["scan"][len(padas)] if len(padas) < len(v["scan"]) else ""})
    for p in padas:
        p["big"] = sum(len(x) for x in p["i"]) > 38

    from kokoro_onnx import Kokoro
    kd = os.environ.get("KOKORO_DIR", os.path.join(HERE, "models"))
    kok = Kokoro(os.path.join(kd, "kokoro-v1.0.onnx"), os.path.join(kd, "voices-v1.0.bin"))
    w = day["word"]
    clips = {"hook": day["hook"].replace("\n", " "), "t1": t1, "t2": t2,
             "word": f"One word. {w.get('say', w['iast'])}. {w['en'][0].upper() + w['en'][1:]}.",
             "end": "Read it word by word, at samskritam.ai."}
    audio, dur = {}, {}
    for k, text in clips.items():
        if text:
            s, sr = tts(kok, text)
            audio[k] = s
            dur[k] = len(s) / sr

    # Timeline (seconds)
    s1 = [0, max(4.0, dur["hook"] + 1.4)]
    a2 = s1[1]
    for k, p in enumerate(padas):
        p["start"], p["dur"] = a2 + 0.8 + k * PADA_S, PADA_S
    s2 = [a2, a2 + 0.8 + len(padas) * PADA_S + 0.8]
    at1 = s2[1] + 0.4
    at2 = at1 + dur["t1"] + 0.5
    s3 = [s2[1], (at2 + dur["t2"] if t2 else at1 + dur["t1"]) + 1.0]
    atw = s3[1] + 0.4
    s4 = [s3[1], max(s3[1] + 4.0, atw + dur["word"] + 0.8)]
    ate = s4[1] + 0.4
    s5 = [s4[1], max(s4[1] + 4.0, ate + dur["end"] + 1.0)]
    total = s5[1]
    n = order.index(vid) + 1
    data = {"day": n, "total": len(order), "ref": f"{cfg['title']} {vid}", "byline": f"Kālidāsa, {cfg['title']} {vid}",
            "hook": day["hook"], "meter": (v.get("m") or ["", None])[0] or "", "padas": padas,
            "t1": {"text": t1, "at": at1, "dur": dur["t1"]}, "t2": {"text": t2, "at": at2, "dur": dur.get("t2", 0)},
            "word": w, "endlink": f"samskritam.ai/#{slug}-{vid}",
            "scenes": {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5}, "total_s": total}
    with open(os.path.join(HERE, "data.js"), "w", encoding="utf-8") as f:
        f.write("window.DATA = " + json.dumps(data, ensure_ascii=False) + ";")

    # Sound: drone plus narration at its times
    sr = 24000
    t = np.arange(int(sr * total)) / sr
    bed = np.zeros_like(t)
    notes, start, k = [98.0, 130.81, 130.81, 65.41], 0.0, 0
    while start < total:
        f0 = notes[k % 4]
        m = int(sr * min(4.0, total - start))
        tt = np.arange(m) / sr
        pl = sum((0.6 / h) * np.sin(2 * np.pi * f0 * h * tt + 0.3 * h) * np.exp(-tt * (0.7 + 0.15 * h)) for h in range(1, 12))
        pl *= 1 + 0.15 * np.sin(2 * np.pi * 5.5 * tt)
        i = int(start * sr)
        bed[i:i + m] += pl[:len(bed) - i]
        start += 1.15
        k += 1
    bed = bed / np.abs(bed).max() * 0.18
    fd = int(sr * 1.5)
    bed[:fd] *= np.linspace(0, 1, fd)
    bed[-fd:] *= np.linspace(1, 0, fd)
    for key, at in [("hook", 0.4), ("t1", at1), ("t2", at2), ("word", atw), ("end", ate)]:
        if key in audio:
            i = int(at * sr)
            seg = audio[key][:len(bed) - i]
            bed[i:i + len(seg)] += seg
    bed = np.clip(bed, -0.99, 0.99)
    wav = os.path.join(HERE, "mix.wav")
    sf.write(wav, bed, sr)

    if os.environ.get("REEL_DRY"):  # data.js and sound only, to look at frames first
        return
    os.makedirs(os.path.join(WEB, "reels"), exist_ok=True)
    silent = os.path.join(HERE, "video.mp4")
    subprocess.run(["node", os.path.join(HERE, "render.js"), silent], check=True)
    out = os.path.join(WEB, "reels", f"{slug}-{vid}.mp4")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-shortest", "-movflags", "+faststart", out + ".tmp.mp4"], check=True)
    os.replace(out + ".tmp.mp4", out)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", "3", "-i", out, "-frames:v", "1", "-vf", "scale=540:-1", "-q:v", "4",
                    out[:-4] + ".jpg"], check=True)
    print(f"{out}: {total:.1f} s")


if __name__ == "__main__":
    main()
