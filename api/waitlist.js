// POST /api/waitlist  {email, interest, website}
// Stores sign-ups in Upstash Redis through its REST API (no dependencies).
// Env: UPSTASH_REDIS_REST_URL + UPSTASH_REDIS_REST_TOKEN, or the
// KV_REST_API_URL + KV_REST_API_TOKEN names some Vercel integrations use.

const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const INTERESTS = new Set(["learn", "research", "both"]);
const EMAIL = /^[^\s@<>()\[\]\\,;:"]+@[^\s@<>()\[\]\\,;:"]+\.[^\s@<>()\[\]\\,;:"]{2,}$/;
const PER_IP_PER_HOUR = 10;

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

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Use POST." });
  }
  if (!URL_ || !TOKEN) {
    return res.status(503).json({ ok: false, error: "Sign-ups are not connected yet. Please try again later." });
  }
  const body = readBody(req);
  // Honeypot: real people never see or fill this field.
  if (body.website) return res.status(200).json({ ok: true });

  const email = String(body.email || "").trim().toLowerCase();
  const interest = INTERESTS.has(body.interest) ? body.interest : "both";
  if (email.length > 254 || !EMAIL.test(email)) {
    return res.status(400).json({ ok: false, error: "Enter a valid email address, like name@example.com." });
  }

  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  try {
    const [hits] = await redis([["INCR", `waitlist:rl:${ip}`], ["EXPIRE", `waitlist:rl:${ip}`, 3600, "NX"]]);
    if (hits > PER_IP_PER_HOUR) {
      return res.status(429).json({ ok: false, error: "Too many sign-ups from this network. Try again in an hour." });
    }
    const now = Date.now();
    const [added] = await redis([
      ["SADD", "waitlist:emails", email],
      ["HSETNX", `waitlist:${email}`, "joined", new Date(now).toISOString()],
      ["HSET", `waitlist:${email}`, "email", email, "interest", interest],
      ["ZADD", "waitlist:bytime", "NX", now, email],
    ]);
    return res.status(200).json({ ok: true, already: added === 0 });
  } catch (e) {
    console.error("waitlist", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your sign-up just now. Please try again." });
  }
};
