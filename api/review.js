// /api/review: the invite-only answer-key review behind samskritam.ai/review.
//
// Every request carries "Authorization: Bearer <token>". The owner's token is
// REVIEW_OWNER_TOKEN; reviewers' tokens come from invite links the owner
// creates (bench/review_admin.py invite "Name").
//
// Storage (Upstash): the questions, uploaded by bench/review_admin.py upload,
// including the private v1 test questions, which never enter the repository;
// and every decision. Decisions on public questions (v0, v1 dev) are published
// as one GitHub pull request adding bench/reviews/<id>.json files; decisions
// on test questions stay here until the owner pulls them
// (bench/review_admin.py pull -> bench/private/reviews.json).
//
//   GET  /api/review                 me, the question index, my decisions
//   GET  /api/review?id=<id>         one question (+ decisions: all for the owner, mine otherwise)
//   POST {action:"decide", id, decision:"right"|"wrong"|"ambiguous", fix, note}
//   owner only:
//   POST {action:"upload", items:[...], reset}   POST {action:"invite", name}
//   POST {action:"revoke", token}    GET ?action=invites    GET ?action=export
//   POST {action:"publish"}          -> pull request for public decisions not yet published
//
// Env: REVIEW_OWNER_TOKEN, REVIEW_OWNER_NAME (shown as the reviewer's name),
// Upstash variables, GITHUB_TOKEN and GITHUB_REPO (as for suggestions).

const crypto = require("crypto");

const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const OWNER = process.env.REVIEW_OWNER_TOKEN || "";
const OWNER_NAME = process.env.REVIEW_OWNER_NAME || "Owner";
const GH = process.env.GITHUB_TOKEN;
const REPO = process.env.GITHUB_REPO || "ssriramhere/samskritam";
const GH_API = process.env.GITHUB_API || "https://api.github.com";
const PUBLIC_SETS = new Set(["v0", "v1-dev"]);
const DECISIONS = new Set(["right", "wrong", "ambiguous"]);

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

// HGETALL comes back as a flat [field, value, field, value, ...] list.
const pairs = (flat) => {
  const o = {};
  for (let i = 0; i + 1 < (flat || []).length; i += 2) o[flat[i]] = flat[i + 1];
  return o;
};

async function gh(method, path, body) {
  const r = await fetch(`${GH_API}/repos/${REPO}${path}`, {
    method,
    headers: { Authorization: `Bearer ${GH}`, Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "samskritam-review" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`github ${method} ${path} ${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try { return JSON.parse(req.body || "{}"); } catch { return {}; }
}

const same = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
const clean = (s, max) => String(s || "").replace(/\s+/g, " ").trim().slice(0, max);

async function whoIs(req) {
  const tok = String(req.headers.authorization || "").replace(/^Bearer\s+/i, "").trim();
  if (!/^[A-Za-z0-9_-]{20,100}$/.test(tok)) return null;
  if (OWNER && same(tok, OWNER)) return { id: "owner", name: OWNER_NAME, role: "owner" };
  const [inv] = await redis([["HGET", "review:invites", tok]]);
  if (!inv) return null;
  const v = JSON.parse(inv);
  return { id: v.id, name: v.name, role: "reviewer" };
}

// A fix is kept only in the shape the question's kind expects.
function cleanFix(kind, fix) {
  if (fix == null) return null;
  if (kind === "fields") {
    if (typeof fix !== "object" || Array.isArray(fix)) return null;
    const o = {};
    for (const [k, v] of Object.entries(fix).slice(0, 12)) {
      if (/^[a-z_]{1,20}$/.test(k)) o[k] = v == null || v === "" ? null : clean(v, 60);
    }
    return o;
  }
  if (kind === "syllables") {
    const p = String(fix).toUpperCase();
    return /^[GL]{1,40}$/.test(p) ? p : null;
  }
  if (kind === "lines") {
    if (!fix || typeof fix !== "object" || !Array.isArray(fix.lines)) return null;
    const lines = fix.lines.slice(0, 8).map((l) => String(l).toUpperCase());
    if (lines.some((l) => !/^[GL]{1,80}$/.test(l))) return null;
    return { lines, meter: clean(fix.meter, 60) };
  }
  if (kind === "table") {
    if (!Array.isArray(fix)) return null;
    return fix.slice(0, 16).map((row) => {
      const o = {};
      for (const [k, v] of Object.entries(row && typeof row === "object" ? row : {}).slice(0, 12)) {
        if (/^[a-z_]{1,20}$/.test(k) && v != null && v !== "") o[k] = clean(v, 60);
      }
      return o;
    });
  }
  if (!Array.isArray(fix)) return null;
  const list = fix.map((x) => clean(x, 80)).filter(Boolean).slice(0, 60);
  if (kind === "sutras" && list.some((x) => !/^\d\.\d\.\d{1,3}$/.test(x))) return null;
  return list.length ? list : null;
}

async function publish(res) {
  const [index, decs, done] = await redis([["HGETALL", "review:index"], ["HGETALL", "review:dec"],
    ["SMEMBERS", "review:published"]]);
  const items = pairs(index), all = pairs(decs), published = new Set(done || []);
  const byItem = {};
  for (const [field, v] of Object.entries(all)) {
    const id = field.split("\t")[0];
    const meta = items[id] ? JSON.parse(items[id]) : null;
    if (!meta || !PUBLIC_SETS.has(meta.set)) continue;
    (byItem[id] ||= { meta, decisions: [], fresh: false }).decisions.push(JSON.parse(v));
    if (!published.has(`${field}\t${JSON.parse(v).at}`)) byItem[id].fresh = true;
  }
  const ids = Object.keys(byItem).filter((id) => byItem[id].fresh).sort();
  if (!ids.length) return res.status(200).json({ ok: true, published: 0 });
  const main = await gh("GET", "/git/ref/heads/main");
  const commit = await gh("GET", `/git/commits/${main.object.sha}`);
  const tree = await gh("POST", "/git/trees", {
    base_tree: commit.tree.sha,
    tree: ids.map((id) => ({
      path: `bench/reviews/${id}.json`, mode: "100644", type: "blob",
      content: JSON.stringify({ id, set: byItem[id].meta.set, task: byItem[id].meta.task,
        decisions: byItem[id].decisions.sort((a, b) => a.at.localeCompare(b.at)) }, null, 2) + "\n",
    })),
  });
  const counts = { right: 0, wrong: 0, ambiguous: 0 };
  ids.forEach((id) => byItem[id].decisions.forEach((d) => counts[d.decision]++));
  const msg = `Answer-key review: ${ids.length} question${ids.length > 1 ? "s" : ""}`;
  const c = await gh("POST", "/git/commits", { message: msg, tree: tree.sha, parents: [main.object.sha] });
  const branch = `review-${Date.now().toString(36)}`;
  await gh("POST", "/git/refs", { ref: `refs/heads/${branch}`, sha: c.sha });
  const rows = ids.map((id) => {
    const ds = byItem[id].decisions.map((d) => `${d.by}: ${d.decision}${d.fix ? " → " + JSON.stringify(d.fix) : ""}`);
    return `| \`${id}\` | ${byItem[id].meta.set} | ${ds.join("; ").replace(/\|/g, "\\|").slice(0, 300)} |`;
  });
  const pr = await gh("POST", "/pulls", {
    title: msg, head: branch, base: "main",
    body: [`Decisions from samskritam.ai/review on public questions (v0 and the v1 dev set).`,
      `Key is right: ${counts.right} · wrong: ${counts.wrong} · ambiguous: ${counts.ambiguous}`, "",
      "| Question | Set | Decisions |", "|---|---|---|", ...rows.slice(0, 200), "",
      "---", "**Approve:** merge. The v1 generator applies these files; v0 keys stay frozen and these become its errata. **Reject:** close."].join("\n"),
  });
  await redis(ids.flatMap((id) => byItem[id].decisions.map((d) =>
    ["SADD", "review:published", `${id}\t${d.reviewer}\t${d.at}`])));
  return res.status(200).json({ ok: true, published: ids.length, url: pr.html_url });
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (!URL_ || !TOKEN || !OWNER) return res.status(503).json({ ok: false, error: "Review is not set up yet." });
  let me;
  try { me = await whoIs(req); } catch (e) {
    console.error("review auth", e);
    return res.status(502).json({ ok: false, error: "Couldn't check your invite just now." });
  }
  if (!me) return res.status(401).json({ ok: false, error: "This page is by invitation. Open the link from your invite." });
  const owner = me.role === "owner";
  const q = req.query || {};
  try {
    if (req.method === "GET") {
      if (q.action === "invites") {
        if (!owner) return res.status(403).json({ ok: false });
        const [inv] = await redis([["HGETALL", "review:invites"]]);
        return res.status(200).json({ ok: true, invites: Object.entries(pairs(inv)).map(([t, v]) => ({ token: t, ...JSON.parse(v) })) });
      }
      if (q.action === "export") {
        if (!owner) return res.status(403).json({ ok: false });
        const [index, decs] = await redis([["HGETALL", "review:index"], ["HGETALL", "review:dec"]]);
        const items = pairs(index), out = {};
        for (const v of Object.values(pairs(decs))) {
          const d = JSON.parse(v), meta = items[d.id] ? JSON.parse(items[d.id]) : {};
          (out[d.id] ||= { id: d.id, set: meta.set, task: meta.task, decisions: [] }).decisions.push(d);
        }
        return res.status(200).json({ ok: true, reviews: out });
      }
      if (q.id) {
        const id = String(q.id);
        const [raw, decs] = await redis([["GET", `review:item:${id}`], ["HGETALL", "review:dec"]]);
        if (!raw) return res.status(404).json({ ok: false, error: "No such question." });
        const item = JSON.parse(raw);
        const mine = Object.entries(pairs(decs)).filter(([f]) => f.startsWith(id + "\t")).map(([, v]) => JSON.parse(v));
        const decided = mine.some((d) => d.reviewer === me.id);
        if (item.tag === "sample" && !decided) item.models = null;  // blind until you decide
        return res.status(200).json({ ok: true, item, mine: mine.find((d) => d.reviewer === me.id) || null,
          decisions: owner ? mine : mine.filter((d) => d.reviewer === me.id),
          reviewers: new Set(mine.map((d) => d.reviewer)).size });
      }
      const [index, decs] = await redis([["HGETALL", "review:index"], ["HGETALL", "review:dec"]]);
      const counts = {}, mine = {};
      for (const [f, v] of Object.entries(pairs(decs))) {
        const [id, who] = f.split("\t");
        counts[id] = (counts[id] || 0) + 1;
        if (who === me.id) mine[id] = JSON.parse(v).decision;
      }
      const list = Object.entries(pairs(index)).map(([id, v]) => ({ id, ...JSON.parse(v), n: counts[id] || 0 }));
      list.sort((a, b) => a.order - b.order);
      return res.status(200).json({ ok: true, me: { name: me.name, role: me.role }, index: list, mine });
    }
    if (req.method !== "POST") {
      res.setHeader("Allow", "GET, POST");
      return res.status(405).json({ ok: false });
    }
    const b = readBody(req);
    if (b.action === "decide") {
      const id = String(b.id || "");
      if (!DECISIONS.has(b.decision)) return res.status(400).json({ ok: false, error: "Choose right, wrong or ambiguous." });
      const [raw] = await redis([["GET", `review:item:${id}`]]);
      if (!raw) return res.status(404).json({ ok: false, error: "No such question." });
      const item = JSON.parse(raw);
      const fix = b.decision === "wrong" ? cleanFix(item.kind, b.fix) : null;
      if (b.decision === "wrong" && !fix) return res.status(400).json({ ok: false, error: "Give the right answer, or choose Ambiguous." });
      const d = { id, reviewer: me.id, by: me.name, decision: b.decision, fix, note: clean(b.note, 1000),
        family: b.family && item.kind === "sutras" ? true : undefined, at: new Date().toISOString() };
      await redis([["HSET", "review:dec", `${id}\t${me.id}`, JSON.stringify(d)]]);
      return res.status(200).json({ ok: true, decision: d });
    }
    if (!owner) return res.status(403).json({ ok: false, error: "Only the owner can do that." });
    if (b.action === "upload") {
      const items = Array.isArray(b.items) ? b.items.slice(0, 500) : [];
      const cmds = b.reset ? [["DEL", "review:index"]] : [];
      for (const it of items) {
        if (!it || typeof it.id !== "string" || !/^[\w.-]{1,40}$/.test(it.id)) continue;
        cmds.push(["SET", `review:item:${it.id}`, JSON.stringify(it)]);
        cmds.push(["HSET", "review:index", it.id, JSON.stringify({ set: it.set, task: it.task, tag: it.tag,
          title: it.title || it.id, order: it.order || 0 })]);
      }
      if (cmds.length) await redis(cmds);
      return res.status(200).json({ ok: true, stored: items.length });
    }
    if (b.action === "invite") {
      const name = clean(b.name, 60);
      if (!name) return res.status(400).json({ ok: false, error: "Give the reviewer's name." });
      const tok = crypto.randomBytes(24).toString("base64url");
      const id = "r" + crypto.randomBytes(4).toString("hex");
      await redis([["HSET", "review:invites", tok, JSON.stringify({ id, name, at: new Date().toISOString() })]]);
      return res.status(200).json({ ok: true, name, token: tok, link: `https://${req.headers.host || "samskritam.ai"}/review#invite=${tok}` });
    }
    if (b.action === "revoke") {
      await redis([["HDEL", "review:invites", String(b.token || "")]]);
      return res.status(200).json({ ok: true });
    }
    if (b.action === "publish") {
      if (!GH) return res.status(503).json({ ok: false, error: "GITHUB_TOKEN is not set." });
      return await publish(res);
    }
    return res.status(400).json({ ok: false, error: "Unknown action." });
  } catch (e) {
    console.error("review", e);
    return res.status(502).json({ ok: false, error: "Something went wrong saving that. Please try again." });
  }
};
