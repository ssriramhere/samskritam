"""Copy the Mahābhārata's CoNLL-U files from the Digital Corpus of Sanskrit into
data/sources/dcs-mahabharata/ as mbh-<parvan>-<adhyāya>.conllu, the names
build_text.py reads. The files are not kept in git (about 175 MB); this makes
them again from a copy of the DCS repository.

    python pipeline/fetch_mahabharata.py              # uses data/dcs-repo, cloning it if missing
    python pipeline/fetch_mahabharata.py /path/to/sanskrit

The DCS files the Bhagavad Gītā separately ("MBh, 6, BhaGī 2"); in the critical
edition it is Bhīṣmaparvan 23-40, so BhaGī n becomes adhyāya 22 + n.
"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "https://github.com/OliverHellwig/sanskrit"
SUB = "dcs/data/conllu/files/Mahābhārata"


def main():
    repo = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data/dcs-repo")
    src = os.path.join(repo, SUB)
    if not os.path.isdir(src):
        if os.path.exists(repo) and os.listdir(repo):
            sys.exit(f"{src} not found")
        print("cloning the DCS (Mahābhārata files only) ...")
        subprocess.run(["git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1", REPO, repo], check=True)
        subprocess.run(["git", "-C", repo, "sparse-checkout", "set", "--no-cone", SUB + "/*.conllu"], check=True)
        subprocess.run(["git", "-C", repo, "checkout"], check=True)
    dst = os.path.join(ROOT, "data/sources/dcs-mahabharata")
    os.makedirs(dst, exist_ok=True)
    n, skipped = 0, []
    for f in sorted(os.listdir(src)):
        m = re.match(r"Mahābhārata-\d+-MBh, (\d+), (\d+)-\d+\.conllu$", f)
        g = re.match(r"Mahābhārata-\d+-MBh, 6, BhaGī (\d+)-\d+\.conllu$", f)
        if m:
            p, a = int(m[1]), int(m[2])
        elif g:
            p, a = 6, 22 + int(g[1])
        else:
            if f.endswith(".conllu"):
                skipped.append(f)
            continue
        shutil.copyfile(os.path.join(src, f), os.path.join(dst, f"mbh-{p}-{a:03d}.conllu"))
        n += 1
    print(f"{n} adhyāya files in {dst}")
    for f in skipped:
        print("  skipped", f)


if __name__ == "__main__":
    main()
