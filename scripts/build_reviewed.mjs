// Fold reviewed/<slug>/<id>.json (merged translation suggestions) into
// web/data/reviewed.json for the site. Runs as Vercel's build command; a bad
// file is skipped with a warning so it can't break a deploy.
//   node scripts/build_reviewed.mjs
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "reviewed");
const out = {};
let n = 0;
if (existsSync(SRC)) {
  for (const slug of readdirSync(SRC)) {
    if (!statSync(join(SRC, slug)).isDirectory()) continue;
    for (const f of readdirSync(join(SRC, slug))) {
      const m = f.match(/^(\d+\.\d+)\.json$/);
      if (!m) continue;
      try {
        const r = JSON.parse(readFileSync(join(SRC, slug, f), "utf8"));
        if (typeof r.t !== "string" || !r.t.trim()) throw new Error("no t");
        (out[slug] ||= {})[m[1]] = { t: r.t.trim(), by: String(r.by || "a reader").trim() };
        n++;
      } catch (e) {
        console.warn(`skipped reviewed/${slug}/${f}: ${e.message}`);
      }
    }
  }
}
writeFileSync(join(ROOT, "web/data/reviewed.json"), JSON.stringify(out));
console.log(`reviewed translations: ${n}`);
