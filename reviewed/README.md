# Reviewed translations

One file per verse: `reviewed/<text>/<verse>.json`, for example `reviewed/gita/2.47.json`:

```json
{ "t": "The translation.", "by": "Name to credit" }
```

Reader suggestions from the site arrive as pull requests that add or change one
of these files. Merge to approve, edit the file in the pull request to change it,
close to reject. On deploy, `scripts/build_reviewed.mjs` collects them into
`web/data/reviewed.json`, and the site shows them in place of the AI translation.

## Rasa readings

One file per verse read in the Verse Reader: `reviewed/rasa/<id>.json`, where the
id is the first 12 hex digits of the SHA-1 of the verse's IAST lines joined by
newlines (as the reader prints them):

```json
{ "verse": ["line 1", "line 2"], "kind": "rasa", "rasa": "śṛṅgāra",
  "variety": "vipralambha", "sthayi": "rati", "why": "Which words carry it, and why.",
  "by": "Name to credit" }
```

`kind` is `rasa`, `bhava` or `none`; `rasa` is one of the nine. The reader shows a
reviewed reading above the AI's for that verse.
