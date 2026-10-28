// POST /api/suggest  {slug, id, text, name, email, note, current, website}
// Turns a reader's suggested translation into a GitHub pull request that adds
// reviewed/<slug>/<id>.json. Corrections to a sandhi citation (kind "sandhi")
// and to the rasa of a verse read in the Verse Reader (kind "rasa") work the same way. Merging the pull request approves it; editing the
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
const TITLES = { gita: "Bhagavad Gītā", meghaduta: "Meghadūta", mahabharata: "Mahābhārata",
  kumarasambhava: "Kumārasaṃbhava", rtusamhara: "Ṛtusaṃhāra", ramayana: "Rāmāyaṇa",
  kathopanisad: "Kaṭhopaniṣad", astavakragita: "Aṣṭāvakragītā" };

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

async function limited(req) {
  const ip = String(req.headers["x-forwarded-for"] || "").split(",")[0].trim() || "unknown";
  const day = new Date().toISOString().slice(0, 10);
  const [hits, , today] = await redis([
    ["INCR", `suggest:rl:${ip}`], ["EXPIRE", `suggest:rl:${ip}`, 3600, "NX"],
    ["INCR", `suggest:day:${day}`], ["EXPIRE", `suggest:day:${day}`, 172800, "NX"]]);
  if (hits > PER_IP_PER_HOUR) return "That's the hourly limit for suggestions from your network. Try again later.";
  if (today > PER_DAY) return "We've had many suggestions today. Please try again tomorrow.";
  return null;
}

async function openPR({ branch, path, file, message, title, body }) {
  const main = await gh("GET", "/git/ref/heads/main");
  await gh("POST", "/git/refs", { ref: `refs/heads/${branch}`, sha: main.object.sha });
  const existing = await gh("GET", `/contents/${path}?ref=main`);
  await gh("PUT", `/contents/${path}`, {
    message, branch,
    content: Buffer.from(JSON.stringify(file, null, 2) + "\n").toString("base64"),
    ...(existing ? { sha: existing.sha } : {}),
  });
  return gh("POST", "/pulls", { title, head: branch, base: "main", body });
}

// A correction to the sūtra citation for one junction type (reviewed/sandhi/).
async function sandhi(req, res, b) {
  const key = String(b.key || "");
  if (!/^[A-Za-z~' ]{1,4}\|[A-Za-z~]{1,2}\|[A-Za-z~' ]{1,8}$/.test(key)) {
    return res.status(400).json({ ok: false, error: "That join wasn't recognised. Reload the page and try again." });
  }
  const why = clean(b.why, 400), name = clean(b.name, 80), note = clean(b.note, 600);
  const email = clean(b.email, 254).toLowerCase(), example = clean(b.example, 200), current = String(b.current || "").slice(0, 1500);
  const steps = String(b.steps || "").split(/\n/).map((l) => l.trim()).filter(Boolean).slice(0, 12).map((l) => {
    const m = l.match(/^(\d\.\d\.\d{1,3})\s*(?:→|->|:)?\s*(.*)$/);
    return m ? [m[1], m[2].slice(0, 60)] : null;
  });
  if (!steps.length || steps.some((x) => !x)) {
    return res.status(400).json({ ok: false, error: "Write one sūtra per line, starting with its number, like: 6.1.77 → y e" });
  }
  if (why.length < 10) return res.status(400).json({ ok: false, error: "Add a short explanation of the join." });
  if ([why, ...steps.map(([c, r]) => `${c} → ${r}`)].join("\n") === current.trim()) {
    return res.status(400).json({ ok: false, error: "That's the same as the current citation. Edit it first." });
  }
  if (email && !EMAIL.test(email)) return res.status(400).json({ ok: false, error: "Check the email address, or leave it empty." });
  try {
    const stop = await limited(req);
    if (stop) return res.status(429).json({ ok: false, error: stop });
    const id = require("crypto").createHash("sha1").update(key).digest("hex").slice(0, 10);
    const sid = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
    const suggested = [why, ...steps.map(([c, r]) => `${c} → ${r}`)].join("\n");
    const pr = await openPR({
      branch: `suggest-sandhi-${id}-${sid}`, path: `reviewed/sandhi/${id}.json`,
      file: { key, why, steps, by: name || "a reader" },
      message: `Suggested sandhi citation: ${example || key}`,
      title: `Sandhi citation suggestion: ${example || key}`,
      body: [
        `A reader suggested a correction to how this join is explained. It applies to every join of this type (\`${key}\` in SLP1).`,
        "", "**Example**", fence(example || key), "", "**Suggested**", fence(suggested), "", "**Current**", fence(current || "(none)"),
        ...(note ? ["", "**Reader's note**", fence(note)] : []),
        "", "**Credit**", fence(name || "a reader (no name given)"),
        email ? "\nThe reader left a contact email; it is stored privately, not here." : "",
        "", "---", "**Approve:** merge. **Edit:** change `why` or `steps` (each step is `[sūtra number, junction after it]`) in this pull request's file, then merge. **Reject:** close.",
      ].join("\n"),
    });
    if (email) await redis([["HSET", `suggest:pr:${pr.number}`, "email", email, "name", name, "sandhi", key]]);
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error("suggest sandhi", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your suggestion just now. Please try again." });
  }
}

// A correction to the rasa of a verse read in the Verse Reader (reviewed/rasa/<id>.json).
const RASAS = ["śṛṅgāra", "hāsya", "karuṇa", "raudra", "vīra", "bhayānaka", "bībhatsa", "adbhuta", "śānta"];
const KINDS = { rasa: "rasa", bhava: "bhāva only", none: "no rasa" };
async function rasa(req, res, b) {
  const lines = Array.isArray(b.lines) ? b.lines.map((l) => clean(l, 200)).filter(Boolean) : [];
  if (!lines.length || lines.length > 4 || !lines.some((l) => /[a-zāīūṛṝḷṃḥśṣṭḍṇñṅ]/.test(l))) {
    return res.status(400).json({ ok: false, error: "That verse wasn't recognised. Read it again and retry." });
  }
  const kind = String(b.verdict || "");
  if (!KINDS[kind]) return res.status(400).json({ ok: false, error: "Choose rasa, bhāva only, or no rasa." });
  const r = kind === "rasa" ? String(b.rasa || "") : null;
  if (kind === "rasa" && !RASAS.includes(r)) return res.status(400).json({ ok: false, error: "Choose one of the nine rasas." });
  const variety = clean(b.variety, 80), sthayi = clean(b.sthayi, 100), why = clean(b.why, 800);
  const name = clean(b.name, 80), email = clean(b.email, 254).toLowerCase(), current = clean(b.current, 600);
  if (why.length < 10) return res.status(400).json({ ok: false, error: "Say briefly why: which words carry the emotion, and what they build." });
  if (email && !EMAIL.test(email)) return res.status(400).json({ ok: false, error: "Check the email address, or leave it empty." });
  try {
    const stop = await limited(req);
    if (stop) return res.status(429).json({ ok: false, error: stop });
    const id = require("crypto").createHash("sha1").update(lines.join("\n")).digest("hex").slice(0, 12);
    const sid = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
    const verdict = kind === "rasa" ? `${r}${variety ? ` (${variety})` : ""}` : KINDS[kind];
    const pr = await openPR({
      branch: `suggest-rasa-${id}-${sid}`, path: `reviewed/rasa/${id}.json`,
      file: { verse: lines, kind, rasa: r, variety: variety || null, sthayi: sthayi || null, why, by: name || "a reader" },
      message: `Suggested rasa: ${lines[0].slice(0, 50)}`,
      title: `Rasa suggestion: ${lines[0].slice(0, 50)}`,
      body: [
        `A reader suggested a reading of the rasa of this verse, read in the Verse Reader: https://samskritam.ai/read#${encodeURIComponent(lines.join("\n"))}`,
        "", "**Verse**", fence(lines.join("\n")), "", "**Suggested**", fence([verdict, sthayi ? `sthāyi-bhāva or bhāva: ${sthayi}` : "", why].filter(Boolean).join("\n")),
        "", "**The AI's reading**", fence(current || "(not given)"),
        "", "**Credit**", fence(name || "a reader (no name given)"),
        email ? "\nThe reader left a contact email; it is stored privately, not here." : "",
        "", "---", "**Approve:** merge. **Edit:** change `kind` (rasa, bhava or none), `rasa` (one of the nine), `variety`, `sthayi`, `why` or `by` in this pull request's file, then merge. Don't change `verse`: it identifies the verse. **Reject:** close.",
      ].join("\n"),
    });
    if (email) await redis([["HSET", `suggest:pr:${pr.number}`, "email", email, "name", name, "rasa", id]]);
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error("suggest rasa", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your suggestion just now. Please try again." });
  }
}

// A correction to one word of a Library verse: its analysis, its derivation
// (with the steps the reader marked wrong), or its meaning.
// Adds reviewed/words/<slug>/<verse id>-<word index>.json.
const CODE = /^(\d\.\d\.\d{1,3}(\.\d{1,2})?|\d\d\.\d{4})$/;
async function word(req, res, b) {
  const slug = String(b.slug || ""), id = String(b.id || ""), wi = Number(b.wi);
  if (!TITLES[slug] || !/^\d{1,3}(?:\.\d{1,3}){1,2}$/.test(id) || !Number.isInteger(wi) || wi < 0 || wi > 300) {
    return res.status(400).json({ ok: false, error: "That word wasn't recognised. Reload the page and try again." });
  }
  const fix = Array.isArray(b.fix) ? b.fix.filter((x) => ["derivation", "analysis", "meaning"].includes(x)) : [];
  if (!fix.length) return res.status(400).json({ ok: false, error: "Tick at least one thing to fix." });
  const form = clean(b.form, 80), why = clean(b.why, 600), name = clean(b.name, 80), email = clean(b.email, 254).toLowerCase();
  if (why.length < 10) return res.status(400).json({ ok: false, error: "Say briefly what is wrong." });
  if (email && !EMAIL.test(email)) return res.status(400).json({ ok: false, error: "Check the email address, or leave it empty." });
  const file = { form, fix, why, by: name || "a reader" };
  if (fix.includes("derivation")) {
    const steps = (Array.isArray(b.steps) ? b.steps : []).slice(0, 80).map((x) => [clean(x && x[0], 12), clean(x && x[1], 60)]);
    if (!steps.length || steps.some(([c]) => !CODE.test(c))) {
      return res.status(400).json({ ok: false, error: "Each step needs a sūtra number like 6.1.77." });
    }
    file.steps = steps;
    file.flagged = (Array.isArray(b.flagged) ? b.flagged : []).map(Number).filter((n) => Number.isInteger(n) && n > 0 && n <= 200);
  }
  if (fix.includes("analysis")) { file.lemma = clean(b.lemma, 60); file.grammar = clean(b.grammar, 120); }
  if (fix.includes("meaning")) file.gloss = clean(b.gloss, 80);
  const cur = b.current && typeof b.current === "object" ? b.current : {};
  const curSteps = (Array.isArray(cur.steps) ? cur.steps : []).slice(0, 80).map((x) => `${clean(x && x[0], 12)} → ${clean(x && x[1], 60)}`);
  try {
    const stop = await limited(req);
    if (stop) return res.status(429).json({ ok: false, error: stop });
    const sid = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 5)}`;
    const ref = `${TITLES[slug]} ${id}`;
    const flaggedText = file.flagged && file.flagged.length
      ? file.flagged.map((n) => `step ${n}${curSteps[n - 1] ? ` (${curSteps[n - 1]})` : ""}`).join(", ") : "";
    const suggested = [
      file.lemma || file.grammar ? `Analysis: ${file.lemma || "(unchanged)"}; ${file.grammar || ""}` : "",
      file.gloss ? `Meaning: ${file.gloss}` : "",
      file.steps ? "Derivation:\n" + file.steps.map(([c, r], k) => `${k + 1}. ${c} → ${r}`).join("\n") : "",
    ].filter(Boolean).join("\n\n");
    const current = [
      `Analysis: ${clean(cur.lemma, 60)}; ${clean(cur.grammar, 120)}`,
      cur.gloss ? `Meaning: ${clean(cur.gloss, 80)}` : "",
      curSteps.length ? "Derivation:\n" + curSteps.map((x, k) => `${k + 1}. ${x}`).join("\n") : "Derivation: (none shown)",
    ].filter(Boolean).join("\n\n");
    const pr = await openPR({
      branch: `suggest-word-${slug}-${id}-${wi}-${sid}`, path: `reviewed/words/${slug}/${id}-${wi}.json`, file,
      message: `Suggested correction: ${form} in ${ref}`,
      title: `Word correction: ${form} in ${ref}`,
      body: [
        `A reader suggested a correction to **${form}** (word ${wi + 1}) in **${ref}**: https://samskritam.ai/#${slug}-${id}`,
        "", `**What to fix:** ${fix.join(", ")}`, ...(flaggedText ? ["", `**Steps marked wrong:** ${flaggedText}`] : []),
        "", "**Suggested**", fence(suggested), "", "**Current**", fence(current), "", "**Why**", fence(why),
        "", "**Credit**", fence(name || "a reader (no name given)"),
        email ? "\nThe reader left a contact email; it is stored privately, not here." : "",
        "", "---", "**Approve:** merge. **Edit:** change the fields in this pull request's file, then merge. **Reject:** close.",
      ].join("\n"),
    });
    if (email) await redis([["HSET", `suggest:pr:${pr.number}`, "email", email, "name", name, "word", `${slug} ${id} ${wi}`]]);
    return res.status(200).json({ ok: true });
  } catch (e) {
    console.error("suggest word", e);
    return res.status(502).json({ ok: false, error: "We couldn't save your suggestion just now. Please try again." });
  }
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ ok: false, error: "Use POST." });
  }
  if (!URL_ || !TOKEN || !GH) return res.status(503).json({ ok: false, error: "Suggestions are not connected yet." });
  const b = readBody(req);
  if (b.website) return res.status(200).json({ ok: true });  // honeypot

  if (b.kind === "sandhi") return sandhi(req, res, b);
  if (b.kind === "rasa") return rasa(req, res, b);
  if (b.kind === "word") return word(req, res, b);
  const slug = String(b.slug || ""), id = String(b.id || "");
  if (!TITLES[slug] || !/^\d{1,3}(?:\.\d{1,3}){1,2}$/.test(id)) {
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
