"""Run every model in bench/models.txt through OpenRouter, then grade and
write web/data/leaderboard.json for the site. Works on Windows, macOS, Linux.

    # PowerShell:  $env:OPENROUTER_API_KEY = "sk-or-..."
    # bash/zsh:    export OPENROUTER_API_KEY=sk-or-...
    python bench/run_all.py              # all models
    python bench/run_all.py --workers 4  # gentler on rate limits
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", default="8")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Set OPENROUTER_API_KEY first.")
    with open(os.path.join(ROOT, "bench", "models.txt"), encoding="utf-8") as f:
        models = [l.strip() for l in f if l.strip() and not l.lstrip().startswith("#")]
    failed = []
    for m in models:
        print(f"== {m}", flush=True)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "bench", "run.py"),
                            "--provider", "openrouter", "--model", m,
                            "--workers", a.workers])
        if r.returncode != 0:
            failed.append(m)
    subprocess.run([sys.executable, os.path.join(ROOT, "bench", "leaderboard.py")], check=True)
    if failed:
        print("These models stopped early; run the same command again to resume:",
              ", ".join(failed))


if __name__ == "__main__":
    main()
