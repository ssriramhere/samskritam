// Review suggested translations. Approving writes the translation into
// web/data/<slug>-translations.json; commit and push to publish it.
//
//   vercel env pull .env.local          # once, for the Upstash credentials
//   node --env-file=.env.local scripts/suggestions.mjs list
//   node --env-file=.env.local scripts/suggestions.mjs approve <sid>
//   node --env-file=.env.local scripts/suggestions.mjs approve <sid> "edited text"
//   node --env-file=.env.local scripts/suggestions.mjs reject <sid>
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
if (!URL_ || !TOKEN) { console.error("No Upstash credentials. Run: vercel env pull .env.local"); process.exit(1); }

const call = async (cmds) => {
  const r = await fetch(`${URL_}/pipeline`, { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` }, body: JSON.stringify(cmds) });
  const out = await r.json();
  const bad = out.find((x) => x.error); if (bad) throw new Error(bad.error);
  return out.map((x) => x.result);
};
const hash = (flat) => { const h = {}; for (let i = 0; i < (flat || []).length; i += 2) h[flat[i]] = flat[i + 1]; return h; };
const trPath = (slug) => join(ROOT, "web/data", `${slug}-translations.json`);
const loadTr = (slug) => JSON.parse(readFileSync(trPath(slug), "utf8"));

async function get(sid) {
  const [flat] = await call([["HGETALL", `suggest:${sid}`]]);
  const s = hash(flat);
  if (!s.slug) { console.error(`No suggestion ${sid}.`); process.exit(1); }
  return s;
}

const [cmd, sid, edited] = process.argv.slice(2);

if (cmd === "list" || !cmd) {
  const [ids] = await call([["ZRANGE", "suggest:pending", 0, -1]]);
  if (!ids.length) { console.log("No pending suggestions."); process.exit(0); }
  const rows = await call(ids.map((i) => ["HGETALL", `suggest:${i}`]));
  ids.forEach((i, n) => {
    const s = hash(rows[n]);
    let tr = {};
    try { tr = loadTr(s.slug); } catch {}
    const cur = (tr.h && tr.h[s.id] && tr.h[s.id].t) || (tr.t && tr.t[s.id]) || "(none)";
    console.log(`\n── ${i}  ${s.slug} ${s.id}  ${s.at}  ${s.name || "anonymous"}${s.email ? ` <${s.email}>` : ""}`);
    console.log(`   now:       ${cur}`);
    console.log(`   suggested: ${s.text}`);
    if (s.note) console.log(`   note:      ${s.note}`);
  });
  console.log(`\n${ids.length} pending. approve <id> ["edited text"] | reject <id>`);
} else if (cmd === "approve" && sid) {
  const s = await get(sid);
  const tr = loadTr(s.slug);
  tr.h = tr.h || {};
  tr.h[s.id] = { t: edited || s.text, by: s.name || "a reader", on: new Date().toISOString().slice(0, 10) };
  writeFileSync(trPath(s.slug), JSON.stringify(tr));
  await call([["HSET", `suggest:${sid}`, "status", "approved", "final", tr.h[s.id].t],
    ["ZREM", "suggest:pending", sid], ["ZADD", "suggest:approved", Date.now(), sid]]);
  console.log(`Approved ${s.slug} ${s.id}. Now publish it:\n  git add web/data/${s.slug}-translations.json && git commit -m "Reviewed translation, ${s.slug} ${s.id}" && git push`);
} else if (cmd === "reject" && sid) {
  await get(sid);
  await call([["HSET", `suggest:${sid}`, "status", "rejected"],
    ["ZREM", "suggest:pending", sid], ["ZADD", "suggest:rejected", Date.now(), sid]]);
  console.log(`Rejected ${sid}.`);
} else {
  console.log("Usage: list | approve <id> [\"edited text\"] | reject <id>");
}
