"""Build the memorisation probe: can a model recite the second half of a verse
from the first? Texts it can recite are ones it has memorised, and questions
from them would test memory more than Sanskrit.

    git clone --depth 1 --filter=blob:none --no-checkout https://github.com/OliverHellwig/sanskrit <dcs>
    python bench/probe/build_memory_probe.py --dcs <dcs>   # -> bench/probe/memory-probe.jsonl

The probe file is committed, so running it needs no corpus clone:
    python bench/run.py --provider openrouter --model <id> --bench bench/probe/memory-probe.jsonl
    python bench/probe/report.py bench/results/*.memory-probe.jsonl
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from engine import dcs  # noqa: E402

# Texts known to be widely read (controls) and less-read verse texts (candidates).
CONTROLS = ["Mahābhārata", "Rāmāyaṇa", "Bhāgavatapurāṇa", "Meghadūta", "Kumārasaṃbhava"]
CANDIDATES = ["Kathāsaritsāgara", "Bhāratamañjarī", "Bṛhatkathāślokasaṃgraha", "Matsyapurāṇa",
              "Liṅgapurāṇa", "Kūrmapurāṇa", "Garuḍapurāṇa", "Skandapurāṇa (Revākhaṇḍa)", "Harivaṃśa",
              "Kālikāpurāṇa", "Saundarānanda", "Kirātārjunīya", "Haṃsadūta", "Kokilasaṃdeśa",
              "Narmamālā", "Rasaratnākara", "Aṣṭāṅgahṛdayasaṃhitā", "Haribhaktivilāsa"]
PER_TEXT = 30
FORMAT = 'Answer with JSON only: {"text": "<the second half in IAST>"}'


def files_of(repo, text):
    out = subprocess.run(["git", "-C", repo, "-c", "core.quotepath=off", "ls-tree", "--name-only", "HEAD",
                          f"dcs/data/conllu/files/{text}/"], capture_output=True, text=True, check=True).stdout
    return sorted(l for l in out.splitlines() if l.endswith(".conllu"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dcs", required=True, help="a clone of github.com/OliverHellwig/sanskrit")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    items = []
    for text in CONTROLS + CANDIDATES:
        files = files_of(a.dcs, text)
        if text == "Mahābhārata":  # the Nalopākhyāna, the episode v1's pilot used
            files = [f for f in files if re.search(r"MBh, 3, (5\d|6\d|7[0-8])-", f)] or files
        picked = rng.sample(files, min(6, len(files)))
        pairs = []
        for f in picked:
            # read the file straight from git (works on a blob-less or sparse clone)
            blob = subprocess.run(["git", "-C", a.dcs, "show", f"HEAD:{f}"], capture_output=True, check=True).stdout
            with tempfile.NamedTemporaryFile("wb", suffix=".conllu", delete=False) as tmp:
                tmp.write(blob)
            try:
                halves = dcs.read(tmp.name)
            except ValueError:  # a file with malformed verse numbers: skip it
                halves = []
            os.unlink(tmp.name)
            by = {}
            for h in halves:
                by.setdefault(h.get("counter"), {})[h.get("sub")] = h["text"].strip()
            chapter = os.path.basename(f).split("-", 2)[-1].rsplit("-", 1)[0]
            for c, subs in by.items():
                if 1 in subs and 2 in subs and len(subs) == 2 and min(len(subs[1]), len(subs[2])) >= 18:
                    pairs.append((chapter, c, subs[1], subs[2]))
        for chapter, c, first, second in rng.sample(pairs, min(PER_TEXT, len(pairs))):
            items.append({
                "id": f"probe-{len(items):04d}", "task": "recall",
                "prompt": (f"This is the first half of a verse from the {text} ({chapter}, verse {c}):\n  {first}\n"
                           f"Give the second half of this verse exactly as it stands in the text. If you don't "
                           f"know it, give your best guess. {FORMAT}"),
                "accept": [second],
                "meta": {"text": text, "group": "control" if text in CONTROLS else "candidate",
                         "chapter": chapter, "verse": c, "first": first}})
        print(f"{text}: {sum(1 for i in items if i['meta']['text'] == text)} verses")
    out = os.path.join(ROOT, "bench/probe/memory-probe.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    print(f"{len(items)} questions -> {out}")


if __name__ == "__main__":
    main()
