// Print the waitlist as CSV, oldest first.
//   vercel env pull .env.local && node --env-file=.env.local scripts/export_waitlist.mjs > waitlist.csv
const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
if (!URL_ || !TOKEN) { console.error("Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN."); process.exit(1); }
const call = async (cmds) => {
  const r = await fetch(`${URL_}/pipeline`, { method: "POST", headers: { Authorization: `Bearer ${TOKEN}` }, body: JSON.stringify(cmds) });
  return (await r.json()).map((x) => x.result);
};
const [emails] = await call([["ZRANGE", "waitlist:bytime", 0, -1]]);
const rows = emails.length ? await call(emails.map((e) => ["HGETALL", `waitlist:${e}`])) : [];
const q = (s) => `"${String(s ?? "").replace(/"/g, '""')}"`;
console.log("email,interest,joined");
for (const flat of rows) {
  const h = {}; for (let i = 0; i < flat.length; i += 2) h[flat[i]] = flat[i + 1];
  console.log([h.email, h.interest, h.joined].map(q).join(","));
}
