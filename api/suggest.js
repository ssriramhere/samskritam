// POST /api/suggest  {slug, id, text, name, email, note, website}
// Stores a reader's suggested translation of a Library verse for review.
// Nothing reaches the site until it is approved with scripts/suggestions.mjs.
// Env: the same Upstash variables as api/waitlist.js.

const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const PER_IP_PER_HOUR = 10;
const EMAIL = /^[^\s@<>()\[\]\\,;:"]+@[^\s@<>()\[\]\\,;:"]+\.[^\s@<>()\[\]\\,;:"]{2,}$/;

async function redis(commands) {
  const r = await fetch(`${URL_}/pipeline`, {
    method: "POST",
    headers: { Authorization: `Bearer ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(commands),
  });
  if (!r.ok) throw new Error(`redis ${r.status}`);
  const out = await r.json();
  const bad = out.find((x) => x.error);
  if (bad) throw new Error(bad.error);
  return out.map((x) => x.result);
}

function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try { return JSON.parse(req.body || "{}"); } catch { return {}; }
}

const clean = (s, max) => String(s || "").replace(/\s+/g, " ").trim().slice(0, max);

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Use POST." });
  }
  if (!URL_ || !TOKEN) return res.status(503).json({ ok: false, error: "Suggestions are not connected yet." });
  const b = readBody(req);
  if (b.website) return res.status(200).json({ ok: true });  // honeypot

  const slug = String(b.slug || ""), id = String(b.id || "");
  if (!/^[a-z]{2,20}$/.test(slug) || !/^\d{1,3}\.\d{1,3}$/.test(id)) {
    return res.status(400).json({ ok: false, error: "That verse wasn't recognised. Reload the page and try again." });
  }
  const text = clean(b.text, 1500), name = clean(b.name, 80), note = clean(b.note, 600);
  const email = clean(b.email, 254).toLowerCase();
  if (text.length < 15) return res.status(400).json({ ok: false, error: "Write the full translation you suggest for this verse." });
  if (email && !EMAIL.test(email)) return res.status(400).json({ ok: false, error: "Check the email address, or leave it empty." });

  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  try {
    const [hits] = await redis([["INCR", `suggest:rl:${ip}`], ["EXPIRE", `suggest:rl:${ip}`, 3600, "NX"]]);
    if (hits > PER_IP_PER_HOUR) {
      return res.status(429).json({ ok: false, error: "That's the hourly limit for suggestions from your network. Try again later." });
    }
    const now = Date.now();
    const sid = `${now.toString(36)}${Math.random().toString(36).slice(2, 6)}`;
    await redis([
      ["HSET", `suggest:${sid}`, "slug", slug, "id", id, "text", text, "name", name, "email", email,
        "note", note, "at", new Date(now).toISOString(), "status", "pending"],
      ["ZADD", "suggest:pending", now, sid],
    ]);
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error("suggest", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your suggestion just now. Please try again." });
  }
};
