// Copy every kept take from samskritam.ai/record to recordings/ on this computer.
//
//   RECORD_OWNER_TOKEN=... node scripts/pull_recordings.mjs [site]
//
// Writes recordings/<voice>/<text>-<verse>.wav and recordings/voices.json (each
// voice's name and consent). Takes already here at the same size are skipped.
// recordings/ is gitignored: the audio is private.
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SITE = process.argv[2] || "https://samskritam.ai";
const TOKEN = process.env.RECORD_OWNER_TOKEN;
if (!TOKEN) { console.error("Set RECORD_OWNER_TOKEN (your passcode for /record) first."); process.exit(1); }
const auth = { Authorization: `Bearer ${TOKEN}` };

const r = await fetch(`${SITE}/api/record?action=export`, { headers: auth });
if (!r.ok) { console.error(`export failed: ${r.status} ${await r.text()}`); process.exit(1); }
const { voices } = await r.json();
const out = join(ROOT, "recordings");
mkdirSync(out, { recursive: true });
let got = 0, skipped = 0;
for (const v of voices) {
  for (const [k, take] of Object.entries(v.kept)) {
    const [text, vid] = k.split("/");
    const f = join(out, v.slug, `${text}-${vid}.wav`);
    if (existsSync(f) && statSync(f).size === take.size) { skipped++; continue; }
    const a = await fetch(`${SITE}/api/record?action=audio&text=${text}&vid=${vid}&voice=${v.slug}`, { headers: auth });
    if (!a.ok) { console.warn(`${v.slug} ${k}: ${a.status}`); continue; }
    mkdirSync(dirname(f), { recursive: true });
    writeFileSync(f, Buffer.from(await a.arrayBuffer()));
    got++;
  }
}
writeFileSync(join(out, "voices.json"), JSON.stringify(voices.map(({ slug, name, consent, kept }) => ({ slug, name, consent, kept })), null, 2));
console.log(`recordings/: ${got} new, ${skipped} already here, ${voices.length} voice(s)`);
