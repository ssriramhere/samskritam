# Reviewed translations

One file per verse: `reviewed/<text>/<verse>.json`, for example `reviewed/gita/2.47.json`:

```json
{ "t": "The translation.", "by": "Name to credit" }
```

Reader suggestions from the site arrive as pull requests that add or change one
of these files. Merge to approve, edit the file in the pull request to change it,
close to reject. On deploy, `scripts/build_reviewed.mjs` collects them into
`web/data/reviewed.json`, and the site shows them in place of the AI translation.
