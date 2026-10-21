"""Turn the v1 item pool into the published dev set and the private test set.

    # 1. pilot run: a few models on the whole pool (see bench/README.md)
    python bench/run.py --provider openrouter --model <id> --bench bench/private/v1-pool.jsonl
    # 2. calibrate and split
    export BENCH_SECRET=...        # keep it private; the same secret gives the same split
    python bench/calibrate_v1.py bench/results/*.v1-pool.jsonl

What it does
  * drops items every pilot model got right (they no longer separate models),
    keeping a few per task so the easy end is still measured;
  * lists items no pilot model got right in bench/private/v1-review.tsv: these
    are the likeliest bad keys, so read them before publishing;
  * splits the rest into dev (published, bench/data/v1-dev.jsonl) and test
    (bench/private/v1-test.jsonl, never committed) by an HMAC of the item id
    with BENCH_SECRET, so nobody can tell from the public data which items are
    in the test set.
Without pilot results it only splits.
"""
import argparse
import collections
import hashlib
import hmac
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "bench"))
sys.path.insert(0, ROOT)
import grade  # noqa: E402

POOL = os.path.join(ROOT, "bench/private/v1-pool.jsonl")
PRIVATE = os.path.join(ROOT, "bench/private")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="*", help="pilot result files for the v1 pool")
    ap.add_argument("--test-share", type=float, default=0.5)
    ap.add_argument("--keep-easy", type=int, default=10, help="items per task kept even if every model got them right")
    a = ap.parse_args()
    secret = os.environ.get("BENCH_SECRET")
    if not secret:
        sys.exit("Set BENCH_SECRET first (any long random string; keep it private).")

    items = grade.load_items(POOL)
    right = collections.defaultdict(list)  # id -> [True/False per model]
    for path in a.results:
        latest = {}
        for r in map(json.loads, open(path, encoding="utf-8")):
            if r.get("output") is not None or r["id"] not in latest:
                latest[r["id"]] = r
        for iid, r in latest.items():
            if iid in items:
                right[iid].append(grade.grade_item(items[iid], r.get("output"))["correct"])
    models = len(a.results)

    easy = [i for i in items if models and len(right[i]) == models and all(right[i])]
    hard = [i for i in items if models and len(right[i]) == models and not any(right[i])]
    rng = random.Random(secret)
    keep_easy = set()
    by_task = collections.defaultdict(list)
    for i in easy:
        by_task[items[i]["task"]].append(i)
    for ids in by_task.values():
        keep_easy |= set(rng.sample(sorted(ids), min(a.keep_easy, len(ids))))
    keep = [i for i in items if i not in easy or i in keep_easy]

    def in_test(iid):
        h = hmac.new(secret.encode(), iid.encode(), hashlib.sha256).digest()
        return int.from_bytes(h[:8], "big") / 2**64 < a.test_share

    os.makedirs(PRIVATE, exist_ok=True)
    dev = [items[i] for i in keep if not in_test(i)]
    test = [items[i] for i in keep if in_test(i)]
    for path, rows in ((os.path.join(ROOT, "bench/data/v1-dev.jsonl"), dev),
                       (os.path.join(PRIVATE, "v1-test.jsonl"), test)):
        with open(path, "w", encoding="utf-8") as f:
            for it in rows:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
    with open(os.path.join(PRIVATE, "v1-review.tsv"), "w", encoding="utf-8") as f:
        f.write("id\ttask\tkey\tmeta\n")
        for i in hard:
            it = items[i]
            f.write(f"{i}\t{it['task']}\t{json.dumps(it['accept'], ensure_ascii=False)}\t"
                    f"{json.dumps(it['meta'], ensure_ascii=False)}\n")

    count = lambda rows: dict(sorted(collections.Counter(r["task"] for r in rows).items()))
    print(f"pool {len(items)}; pilot models {models}")
    if models:
        print(f"  every model right: {len(easy)} (kept {len(keep_easy)}), every model wrong: {len(hard)}"
              f" -> review bench/private/v1-review.tsv")
    print(f"dev  {len(dev)} {count(dev)} -> bench/data/v1-dev.jsonl (publish)")
    print(f"test {len(test)} {count(test)} -> bench/private/v1-test.jsonl (keep private)")


if __name__ == "__main__":
    main()
