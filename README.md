# Samskritam.ai

AI for Sanskrit, Sanskrit for AI.

Learn Sanskrit using AI, with every word checked against Pāṇini's rules.

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
| `web/` | The static site served at samskritam.ai. Each text lives in `web/data/<slug>/`: `index.json` (chapters, labels, search files), `<chapter>.json` (verses and words), and per-chapter derivations, translations and sandhi, loaded as the reader moves. Chapter ids are `2` (Gītā) or `3.50` (Mahābhārata parvan 3, adhyāya 50); verse ids add the verse: `3.50.1`. |
| `api/waitlist.js` | Sign-up endpoint (Vercel function, Upstash Redis) |
| `api/suggest.js` | Translation suggestions, opened as GitHub pull requests (`reviewed/`) |
| `api/read.py` | Verse reader: an AI model analyses a pasted verse, `engine/reader.py` checks each word (needs `OPENROUTER_API_KEY` and Upstash; optional `READER_MODEL` (default), `READER_MODELS` (the models people can pick), `READER_DAILY_CAP`) |
| `brand/` | Logo source and build script |

## Build the data

```bash
pip install -r pipeline/requirements.txt
python -c "import vidyut; vidyut.download_data('vidyut-data')"
python pipeline/build_gita.py     # data/build/*.json
python pipeline/build_text.py     # data/build/<slug>*.json for each text in TEXTS (Meghadūta, Mahābhārata)
python pipeline/build_web.py      # web/data/<slug>/: index, one file per chapter, search files
python pipeline/build_sandhi.py   # web/data/<slug>/<chapter>-sandhi.json
python pipeline/audit_gita.py     # agreement report
```

## AI translations

English translations for the texts in the Library come from an AI model, given
each verse with its word-by-word analysis. The site labels them as the model's
and unchecked.

```bash
export OPENROUTER_API_KEY=...
python pipeline/translate.py mahabharata         # web/data/<slug>/<chapter>-translations.json; resumable
```

Default model `anthropic/claude-opus-5.5`; change with `--model`.

Readers can suggest a better translation for any verse. Each suggestion becomes a
pull request adding `reviewed/<text>/<verse>.json` (see `reviewed/README.md`): merge to
approve, edit the file in the pull request to change it, close to reject. Vercel's build
(`scripts/build_reviewed.mjs`) collects merged ones into `web/data/reviewed.json`, and the
site shows them in place of the AI translation, with the AI one a click away.
Needs `GITHUB_TOKEN` in Vercel: a fine-grained token for this repository only, with
Contents and Pull requests set to read and write.

## Sandhi: how the words join

`python pipeline/build_sandhi.py` traces, for every Library verse, how the scholars'
word split joins into the printed text, using Vidyut's sandhi table
(`engine/sandhi.py`). It writes `web/data/<slug>-sandhi.json`, the list of junction
types (`data/build/sandhi-types.json`) and `web/data/sutras.json` (the sūtrapāṭha).
Sūtra citations for each junction type come from an AI model, with every sūtra number
checked against the sūtrapāṭha:

```bash
export OPENROUTER_API_KEY=...
python pipeline/sandhi_cite.py          # web/data/sandhi-rules.json; resumable
```

Readers can suggest corrections; they arrive as pull requests adding
`reviewed/sandhi/<id>.json`, handled like translation suggestions.

## Run the benchmark

The runner uses only the Python standard library.

```bash
export OPENROUTER_API_KEY=...     # PowerShell: $env:OPENROUTER_API_KEY = "..."
python bench/run_all.py           # all models in parallel, 18 requests/min each, then web/data/leaderboard.json
```

One model at a time: `python bench/run.py --provider openrouter --model <vendor/model>`,
then `python bench/grade.py bench/results/<file>.jsonl`.

The questions are generated from templates in `bench/generate.py`. Answers come
from Vidyut's implementation of the Aṣṭādhyāyī and, for the Gītā questions,
from the Digital Corpus of Sanskrit annotation where Vidyut agrees with it.

Regenerate the items with `python bench/generate.py --seed 108`.

Published results: `web/data/leaderboard.json` (scores) and `bench/results-v0/`
(each model's final answer to every question, with its grade), written by
`python bench/leaderboard.py` and `python bench/publish_results.py`.

## Benchmark v1 (in progress)

v0 stays as published: its items, scores and leaderboard are frozen. v1 is
built from the Mahābhārata (for now the Nalopākhyāna) with five tasks:
grammar in context, sandhi split, sandhi join, sūtra citation and meter
(see the top of `bench/generate_v1.py` for how each answer key is fixed).

```
python bench/generate_v1.py                       # candidate pool -> bench/private/v1-pool.jsonl
python bench/run_all.py --bench bench/private/v1-pool.jsonl --models <file of pilot models>
export BENCH_SECRET=...                           # private; the same secret gives the same split
python bench/calibrate_v1.py bench/results/*.v1-pool.jsonl
```

Calibration drops items every pilot model gets right, lists items no model
gets right in `bench/private/v1-review.tsv` (read these: they are the likeliest
bad keys), and splits the rest into `bench/data/v1-dev.jsonl` (published) and
`bench/private/v1-test.jsonl` (never committed). `bench/private/` holds the
test items, so it is git-ignored. Results for v1 never enter the v0
leaderboard.

### Answer-key review (samskritam.ai/review, invite-only)

Reviewers check answer keys question by question: the key laid out readably,
where it came from, any hand correction, and each model's answer. Random-sample
questions hide the model answers until the reviewer decides.

```
export REVIEW_OWNER_TOKEN=...                   # same value as in Vercel
python bench/build_review_queue.py              # v0 + v1 dev + v1 test -> bench/private/review-queue.json
python bench/review_admin.py upload             # to the site (Upstash); test questions never enter the repo
python bench/review_admin.py invite "Name"      # prints a personal link
python bench/review_admin.py publish            # one pull request for decisions on public questions
python bench/review_admin.py pull               # all decisions -> bench/private/reviews.json
```

Merged decisions (`bench/reviews/*.json`) and pulled private ones are applied by
`bench/generate_v1.py`. v0 keys stay frozen; its reviews are errata: after merging
a review pull request, run `python bench/build_errata.py` and commit
`web/data/errata-v0.json`. The /bench page lists each correction and every
model's score re-graded with the corrected keys next to the published one.
v0's 13 removed questions are in `bench/data/v0-removed.jsonl` and can be
reviewed (and restored) like the rest.

### Publishing v1 scores

```
python bench/v1/publish.py        # grades bench/results/*.v1.jsonl -> web/data/bench-v1.json
git add web/data/bench-v1.json && git commit -m "v1 scores" && git push
```

Only scores are published (the questions stay private), with the memorisation
probe's results when they're there. After correcting keys through the review
page: `bench/review_admin.py pull`, `bench/v1/generate.py` (same BENCH_SECRET),
then publish again.

## Deploy

Vercel serves `web/` as static files and `api/` as functions (`vercel.json`).
Add Upstash Redis from the Vercel Marketplace for the sign-up list; export it with
`node --env-file=.env.local scripts/export_waitlist.mjs > waitlist.csv`.

## License

Code: Apache-2.0 (`LICENSE`). Data and benchmark: CC BY 4.0 (`LICENSE-DATA.md`).
Third-party sources and their licenses are listed in `NOTICE`.
