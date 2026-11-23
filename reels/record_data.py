"""Write the verse list for the private recording page (samskritam.ai/record).

    python reels/record_data.py          # writes web/data/record/<text>.json

One entry per day of the Verse for Today series (web/data/today.json): the day,
the verse id, its meter, and its pādas in Devanagari and IAST with the meter
scan, split the same way as the reels.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_reel import WEB, padas_of  # noqa: E402


def main():
    cfg = json.load(open(os.path.join(WEB, "data/today.json"), encoding="utf-8"))
    slug = cfg["text"]
    idx = json.load(open(os.path.join(WEB, f"data/{slug}/index.json"), encoding="utf-8"))
    days, n = [], 0
    for c in idx["chapters"]:
        verses = {v["id"]: v for v in json.load(open(os.path.join(WEB, f"data/{slug}/{c['id']}.json"), encoding="utf-8"))["verses"]}
        for i in range(c["n"]):
            n += 1
            vid = f"{c['id']}.{i + 1}"
            v = dict(verses[vid])
            sc = v.get("scan") or []
            if len(sc) == len(v["lt"]) and all(len(x) > 24 for x in sc):  # scanned by half-line: halve each
                even = [len(x) // 2 for x in sc if len(x) % 2 == 0]
                cut = lambda x: len(x) // 2 if len(x) % 2 == 0 else (even[0] if even else (len(x) + 1) // 2)
                v["scan"] = [h for x in sc for h in (x[:cut(x)], x[cut(x):])]
            m = v.get("m") or v.get("meter") or [None]
            days.append({"day": n, "id": vid, "meter": m[0] if m else None,
                         "reel": bool((cfg["days"].get(vid) or {}).get("reel")),
                         "padas": [{"d": " ".join(p["d"]), "i": " ".join(p["i"]), "m": p["m"]} for p in padas_of(v)]})
    out = os.path.join(WEB, "data/record")
    os.makedirs(out, exist_ok=True)
    json.dump({"text": slug, "title": cfg["title"], "start": cfg["start"], "days": days},
              open(os.path.join(out, f"{slug}.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"web/data/record/{slug}.json: {len(days)} verses, {sum(d['reel'] for d in days)} with reels")


if __name__ == "__main__":
    main()
