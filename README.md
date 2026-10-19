# Samskritam.ai

Sanskrit with its grammar shown.

- **Learn:** read the Bhagavad Gītā word by word. Each word carries the
  scholarly analysis from the Digital Corpus of Sanskrit, checked against
  [Vidyut](https://github.com/ambuda-org/vidyut), a working implementation of
  Pāṇini's Aṣṭādhyāyī, with sūtra-by-sūtra derivations and meter.
- **Improve AI:** an open Sanskrit grammar benchmark whose answers are fixed
  by Pāṇini's rules or by two independent sources, never by another model.

## Layout

| Path | What it is |
|---|---|
| `engine/` | Verifier (`verify.py`), DCS reader, meter identification, labels |
| `pipeline/` | Builds the verified dataset (`build_gita.py`) and the site data (`build_web.py`) |
| `data/sources/` | Source annotations (DCS, CC BY 4.0) and verse text (public domain) |
| `data/build/` | Built datasets: Gītā (`gita.json`) and Meghadūta (`meghaduta.json`), with derivations |
| `bench/` | Benchmark generator, runner, grader; items in `bench/data/v0.jsonl` |
| `web/` | The static site served at samskritam.ai |
| `api/waitlist.js` | Sign-up endpoint (Vercel function, Upstash Redis) |
| `brand/` | Logo source and build script |

## Build the data

```bash
pip install -r pipeline/requirements.txt
python -c "import vidyut; vidyut.download_data('vidyut-data')"
python pipeline/build_gita.py     # data/build/*.json
python pipeline/build_text.py     # data/build/meghaduta*.json (and any text in TEXTS)
python pipeline/build_web.py      # web/data/*.json
python pipeline/audit_gita.py     # agreement report
```

## Run the benchmark

The runner uses only the Python standard library.

```bash
export OPENROUTER_API_KEY=...     # PowerShell: $env:OPENROUTER_API_KEY = "..."
python bench/run_all.py           # every model in bench/models.txt, then web/data/leaderboard.json
```

One model at a time: `python bench/run.py --provider openrouter --model <vendor/model>`,
then `python bench/grade.py bench/results/<file>.jsonl`.

The questions are generated from templates in `bench/generate.py`. Answers come
from Vidyut's implementation of the Aṣṭādhyāyī and, for the Gītā questions,
from the Digital Corpus of Sanskrit annotation where Vidyut agrees with it.

Regenerate the items with `python bench/generate.py --seed 108`.

## Deploy

Vercel serves `web/` as static files and `api/` as functions (`vercel.json`).
Add Upstash Redis from the Vercel Marketplace for the sign-up list; export it with
`node --env-file=.env.local scripts/export_waitlist.mjs > waitlist.csv`.

## License

Code: Apache-2.0 (`LICENSE`). Data and benchmark: CC BY 4.0 (`LICENSE-DATA.md`).
Third-party sources and their licenses are listed in `NOTICE`.
