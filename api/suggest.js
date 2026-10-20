// POST /api/suggest  {slug, id, text, name, email, note, current, website}
// Turns a reader's suggested translation into a GitHub pull request that adds
// reviewed/<slug>/<id>.json. Merging the pull request approves it; editing the
// file in the pull request edits it; closing it rejects it. On deploy,
// scripts/build_reviewed.mjs folds reviewed/ into web/data/reviewed.json.
//
// Env: GITHUB_TOKEN (fine-grained, this repository only: Contents and Pull
// requests, read and write), GITHUB_REPO (default ssriramhere/samskritam), and
// the Upstash variables for rate limits and the private contact email.
// The repository is public, so the email is never written to GitHub.

const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const GH = process.env.GITHUB_TOKEN;
const REPO = process.env.GITHUB_REPO || "ssriramhere/samskritam";
const PER_IP_PER_HOUR = 10;
const PER_DAY = 50;
const EMAIL = /^[^\s@<>()\[\]\\,;:"]+@[^\s@<>()\[\]\\,;:"]+\.[^\s@<>()\[\]\\,;:"]{2,}$/;
// Texts that accept suggestions; add new Library texts here.
const TITLES = { gita: "Bhagavad Gītā", meghaduta: "Meghadūta" };

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

async function gh(method, path, body) {
  const r = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    method,
    headers: { Authorization: `Bearer ${GH}`, Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "samskritam-suggest" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 404 && method === "GET") return null;
  if (!r.ok) throw new Error(`github ${method} ${path} ${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try { return JSON.parse(req.body || "{}"); } catch { return {}; }
}

const clean = (s, max) => String(s || "").replace(/\s+/g, " ").trim().slice(0, max);
// Shown inside fenced blocks in the pull request, so links and @mentions stay inert.
const fence = (s) => "```text\n" + String(s).replace(/`{3,}/g, "``") + "\n```";

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Use POST." });
  }
  if (!URL_ || !TOKEN || !GH) return res.status(503).json({ ok: false, error: "Suggestions are not connected yet." });
  const b = readBody(req);
  if (b.website) return res.status(200).json({ ok: true });  // honeypot

  const slug = String(b.slug || ""), id = String(b.id || "");
  if (!TITLES[slug] || !/^\d{1,3}\.\d{1,3}$/.test(id)) {
    return res.status(400).json({ ok: false, error: "That verse wasn't recognised. Reload the page and try again." });
  }
  const text = clean(b.text, 1500), name = clean(b.name, 80), note = clean(b.note, 600);
  const current = clean(b.current, 1500), email = clean(b.email, 254).toLowerCase();
  if (text.length < 15) return res.status(400).json({ ok: false, error: "Write the full translation you suggest for this verse." });
  if (text === current) return res.status(400).json({ ok: false, error: "That's the same as the current translation. Edit it first." });
  if (email && !EMAIL.test(email)) return res.status(400).json({ ok: false, error: "Check the email address, or leave it empty." });

  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  try {
    const [hits, , today] = await redis([
      ["INCR", `suggest:rl:${ip}`], ["EXPIRE", `suggest:rl:${ip}`, 3600, "NX"],
      ["INCR", `suggest:day:${day}`], ["EXPIRE", `suggest:day:${day}`, 172800, "NX"]]);
    if (hits > PER_IP_PER_HOUR) return res.status(429).json({ ok: false, error: "That's the hourly limit for suggestions from your network. Try again later." });
    if (today > PER_DAY) return res.status(429).json({ ok: false, error: "We've had many suggestions today. Please try again tomorrow." });

    const sid = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
    const branch = `suggest-${slug}-${id}-${sid}`;
    const path = `reviewed/${slug}/${id}.json`;
    const main = await gh("GET", "/git/ref/heads/main");
    await gh("POST", "/git/refs", { ref: `refs/heads/${branch}`, sha: main.object.sha });
    const existing = await gh("GET", `/contents/${path}?ref=main`);
    const file = { t: text, by: name || "a reader" };
    await gh("PUT", `/contents/${path}`, {
      message: `Suggested translation: ${TITLES[slug]} ${id}`, branch,
      content: Buffer.from(JSON.stringify(file, null, 2) + "\n").toString("base64"),
      ...(existing ? { sha: existing.sha } : {}),
    });
    const ref = `${TITLES[slug]} ${id}`;
    const body = [
      `A reader suggested a translation for **${ref}**: https://samskritam.ai/#${slug}-${id}`,
      "", "**Suggested**", fence(text), "", "**Current**", fence(current || "(none)"),
      ...(note ? ["", "**Reader's note**", fence(note)] : []),
      "", "**Credit**", fence(name || "a reader (no name given)"),
      email ? "\nThe reader left a contact email; it is stored privately, not here." : "",
      "", "---", "**Approve:** merge. **Edit:** change `t` (the translation) or `by` (the credit) in this pull request's file, then merge. **Reject:** close.",
    ].join("\n");
    const pr = await gh("POST", "/pulls", { title: `Translation suggestion: ${ref}`, head: branch, base: "main", body });
    if (email) await redis([["HSET", `suggest:pr:${pr.number}`, "email", email, "name", name, "verse", `${slug} ${id}`]]);
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error("suggest", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your suggestion just now. Please try again." });
  }
};
