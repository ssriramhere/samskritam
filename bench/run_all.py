"""Run every model in bench/models.txt through OpenRouter, then grade and
write web/data/leaderboard.json for the site. Works on Windows, macOS, Linux.

    # PowerShell:  $env:OPENROUTER_API_KEY = "sk-or-..."
    # bash/zsh:    export OPENROUTER_API_KEY=sk-or-...
    python bench/run_all.py              # all models
    python bench/run_all.py --rpm 10     # if 429 errors persist
    python bench/run_all.py --sequential # one model at a time
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="4")
    ap.add_argument("--rpm", default="18",
                    help="per-model request cap; OpenRouter new accounts allow 20/min per model")
    ap.add_argument("--bench", default=None,
                    help="item set to run (default bench/data/v0.jsonl), e.g. bench/private/v1-pool.jsonl")
    ap.add_argument("--models", default=os.path.join(ROOT, "bench", "models.txt"),
                    help="file listing the models, one per line")
    ap.add_argument("--sequential", action="store_true",
                    help="run one model at a time instead of all at once")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("OPENROUTER_API_KEY is not set; only provider-prefixed models will run.")
    with open(a.models, encoding="utf-8") as f:
        models = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    # Rate limits are per model, so the models can run side by side.
    # A line like "sarvam:sarvam-105b" uses that provider's own API;
    # anything else goes through OpenRouter.
    def cmd(m):
        prov, model = m.split(":", 1) if ":" in m and m.split(":", 1)[0] in ("sarvam", "anthropic", "openai", "google") else ("openrouter", m)
        return [sys.executable, os.path.join(ROOT, "bench", "run.py"),
                "--provider", prov, "--model", model,
                "--workers", a.workers, "--rpm", a.rpm] + (["--bench", a.bench] if a.bench else [])
    failed = []
    if a.sequential:
        for m in models:
            print(f"== {m}", flush=True)
            if subprocess.run(cmd(m)).returncode != 0:
                failed.append(m)
    else:
        procs = {m: subprocess.Popen(cmd(m)) for m in models}
        print(f"Running {len(procs)} models at once, up to {a.rpm} requests/min each.", flush=True)
        for m, p in procs.items():
            if p.wait() != 0:
                failed.append(m)
    if a.bench and os.path.basename(a.bench) != "v0.jsonl":
        # Other item sets don't touch the v0 leaderboard; grade their results directly.
        stem = os.path.splitext(os.path.basename(a.bench))[0]
        import glob
        files = sorted(glob.glob(os.path.join(ROOT, "bench", "results", f"*.{stem}.jsonl")))
        subprocess.run([sys.executable, os.path.join(ROOT, "bench", "grade.py"), "--bench", a.bench] + files)
    else:
        subprocess.run([sys.executable, os.path.join(ROOT, "bench", "leaderboard.py")], check=True)
    if failed:
        print("These models stopped early; run the same command again to resume:",
              ", ".join(failed))


if __name__ == "__main__":
    main()
