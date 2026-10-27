// Print everyone who left a contact email, as CSV: sign-ups from the home page's
// list, and people who suggested a correction (translation, sandhi or rasa) and
// left an email with it. The emails live only in Upstash, never in the repository.
//   vercel env pull .env.local && node --env-file=.env.local scripts/export_contacts.mjs > contacts.csv
const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
if (!URL_ || !TOKEN) { console.error("Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN."); process.exit(1); }
const call = async (cmds) => {
  const r = await fetch(`${URL_}/pipeline`, { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` }, body: JSON.stringify(cmds) });
  return (await r.json()).map((x) => x.result);
};
const hash = (flat) => { const h = {}; for (let i = 0; i < (flat || []).length; i += 2) h[flat[i]] = flat[i + 1]; return h; };
const q = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;
console.log("source,email,name,detail,when");

// Sign-ups, oldest first
const [emails] = await call([["ZRANGE", "waitlist:bytime", 0, -1]]);
const rows = emails.length ? await call(emails.map((e) => ["HGETALL", `waitlist:${e}`])) : [];
for (const flat of rows) { const h = hash(flat); console.log(["sign-up", h.email, "", h.interest, h.joined].map(q).join(",")); }

// Correction suggestions with an email (one hash per pull request: suggest:pr:<number>)
let cursor = "0", keys = [];
do { const [[next, batch]] = await call([["SCAN", cursor, "MATCH", "suggest:pr:*", "COUNT", 500]]); cursor = next; keys = keys.concat(batch); } while (cursor !== "0");
keys.sort((a, b) => +a.split(":")[2] - +b.split(":")[2]);
const subs = keys.length ? await call(keys.map((k) => ["HGETALL", k])) : [];
subs.forEach((flat, i) => {
  const h = hash(flat), pr = keys[i].split(":")[2];
  const what = h.verse ? `translation ${h.verse}` : h.sandhi ? `sandhi ${h.sandhi}` : h.rasa ? `rasa ${h.rasa}` : "";
  console.log(["suggestion", h.email, h.name, `${what}, pull request #${pr}`, ""].map(q).join(","));
});
