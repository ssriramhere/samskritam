// Fold reviewed/<slug>/<id>.json (merged translation suggestions) into
// web/data/reviewed.json for the site. Runs as Vercel's build command; a bad
// file is skipped with a warning so it can't break a deploy.
//   node scripts/build_reviewed.mjs
import { existsSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(ROOT, "reviewed");
const out = {};
let n = 0;
if (existsSync(SRC)) {
  for (const slug of readdirSync(SRC)) {
    if (slug === "sandhi" || slug === "rasa" || slug === "words" || !statSync(join(SRC, slug)).isDirectory()) continue;
    for (const f of readdirSync(join(SRC, slug))) {
      const m = f.match(/^(\d+(?:\.\d+){1,2})\.json$/);
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
// Reviewed sandhi citations: reviewed/sandhi/<id>.json {key, why, steps: [[sūtra, junction]], by}
const sandhiDir = join(SRC, "sandhi");
if (existsSync(sandhiDir)) {
  let sutras = {};
  try { sutras = JSON.parse(readFileSync(join(ROOT, "web/data/sutras.json"), "utf8")); } catch {}
  for (const f of readdirSync(sandhiDir)) {
    if (!f.endsWith(".json")) continue;
    try {
      const r = JSON.parse(readFileSync(join(sandhiDir, f), "utf8"));
      if (!r.key || !r.why || !Array.isArray(r.steps) || !r.steps.length) throw new Error("needs key, why and steps");
      (out._sandhi ||= {})[r.key] = { why: String(r.why).trim(), by: String(r.by || "a reader").trim(),
        s: r.steps.map(([c, x]) => [String(c), sutras[c] || "", String(x || "")]) };
      n++;
    } catch (e) {
      console.warn(`skipped reviewed/sandhi/${f}: ${e.message}`);
    }
  }
}
// Reviewed rasa readings for verses read in the Verse Reader:
// reviewed/rasa/<id>.json {verse: [IAST lines], kind, rasa, variety, sthayi, why, by}
const RASAS = ["śṛṅgāra", "hāsya", "karuṇa", "raudra", "vīra", "bhayānaka", "bībhatsa", "adbhuta", "śānta"];
const rasaDir = join(SRC, "rasa");
if (existsSync(rasaDir)) {
  for (const f of readdirSync(rasaDir)) {
    if (!f.endsWith(".json")) continue;
    try {
      const r = JSON.parse(readFileSync(join(rasaDir, f), "utf8"));
      if (!Array.isArray(r.verse) || !r.verse.length) throw new Error("needs verse");
      if (!["rasa", "bhava", "none"].includes(r.kind)) throw new Error("kind must be rasa, bhava or none");
      if (r.kind === "rasa" && !RASAS.includes(r.rasa)) throw new Error("rasa must be one of the nine");
      if (!r.why) throw new Error("needs why");
      const id = createHash("sha1").update(r.verse.join("\n")).digest("hex").slice(0, 12);
      (out._rasa ||= {})[id] = { kind: r.kind, rasa: r.kind === "rasa" ? r.rasa : null, variety: r.variety || null,
        sthayi: r.sthayi || null, why: String(r.why).trim(), by: String(r.by || "a reader").trim() };
      n++;
    } catch (e) {
      console.warn(`skipped reviewed/rasa/${f}: ${e.message}`);
    }
  }
}
// Reviewed word corrections: reviewed/words/<slug>/<verse id>-<word index>.json
const wordsDir = join(SRC, "words");
if (existsSync(wordsDir)) {
  let sutras = {};
  try { sutras = JSON.parse(readFileSync(join(ROOT, "web/data/sutras.json"), "utf8")); } catch {}
  for (const slug of readdirSync(wordsDir)) {
    if (!statSync(join(wordsDir, slug)).isDirectory()) continue;
    for (const f of readdirSync(join(wordsDir, slug))) {
      const m = f.match(/^(\d+(?:\.\d+){1,2})-(\d+)\.json$/);
      if (!m) continue;
      try {
        const r = JSON.parse(readFileSync(join(wordsDir, slug, f), "utf8"));
        const entry = { by: String(r.by || "a reader").trim(), why: String(r.why || "").trim() };
        if (r.lemma) entry.lemma = String(r.lemma);
        if (r.grammar) entry.grammar = String(r.grammar);
        if (r.gloss) entry.gloss = String(r.gloss);
        if (Array.isArray(r.steps) && r.steps.length) entry.steps = r.steps.map(([c, x]) => [String(c), sutras[String(c)] || "", String(x || "")]);
        ((((out._words ||= {})[slug] ||= {})[m[1]] ||= {}))[+m[2]] = entry;
        n++;
      } catch (e) {
        console.warn(`skipped reviewed/words/${slug}/${f}: ${e.message}`);
      }
    }
  }
}
writeFileSync(join(ROOT, "web/data/reviewed.json"), JSON.stringify(out));
console.log(`reviewed entries: ${n}`);
