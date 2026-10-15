"""Run the verifier over every Gītā token and report agreement."""
import collections, glob, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import dcs, verify

stat = collections.Counter(); fails = collections.Counter()
for f in sorted(glob.glob(os.path.join(ROOT, "data/sources/dcs-gita/*.conllu"))):
    for hv in dcs.read(f):
        for g in hv["groups"]:
            for tok in g["tokens"]:
                r = verify.check(tok); stat[r["status"]] += 1
                if r["status"] in ("form-known", "unknown"):
                    fails[(tok["form"], tok["lemma"], tok["upos"], r["status"])] += 1
checkable = stat["agree"] + stat["form-known"] + stat["unknown"]
print(dict(stat), f"agreement {stat['agree']/checkable:.1%} of {checkable}")
for k, v in fails.most_common(int(sys.argv[1]) if len(sys.argv) > 1 else 15):
    print(v, k)
