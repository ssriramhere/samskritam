// /api/record: the invite-only recording sheet behind samskritam.ai/record.
//
// Every request carries "Authorization: Bearer <token>". The owner's token is
// RECORD_OWNER_TOKEN (or REVIEW_OWNER_TOKEN if that is unset); other voices get
// their own token from an invite link the owner makes on the page.
//
// Audio goes to a private Vercel Blob store, as
//   takes/<text>/<verse>/<voice>/<time>.wav
// and only this function can read it back. Takes are sent in parts of up to
// 3 MB (a function request is capped at 4.5 MB), joined here, then the parts
// are deleted. Which take each voice kept for each verse, and each voice's
// consent, live in Upstash.
//
//   GET  ?action=me                         who I am, my consent, my kept takes (owner: every voice)
//   POST ?action=part&upload=<id>&n=<i>     raw bytes of one part (application/octet-stream)
//   POST {action:"finish", upload, parts, text, vid, dur, checks}  join the parts and keep the take
//   GET  ?action=audio&text=&vid=&voice=    play a kept take (your own; the owner can play any)
//   POST {action:"consent", publish, train, credit}
//   owner only:
//   POST {action:"invite", name}   ->  {link}       POST {action:"revoke", voice}
//   GET  ?action=export            every kept take and every consent (scripts/pull_recordings.mjs)
//
// Env: RECORD_OWNER_TOKEN, RECORD_OWNER_NAME, Upstash variables, and a private
// Blob store connected to the project (BLOB_STORE_ID with OIDC, or
// BLOB_READ_WRITE_TOKEN). RECORD_LOCAL_DIR stores audio on disk instead (tests).

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const URL_ = process.env.UPSTASH_REDIS_REST_URL || process.env.KV_REST_API_URL;
const TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || process.env.KV_REST_API_TOKEN;
const OWNER = process.env.RECORD_OWNER_TOKEN || process.env.REVIEW_OWNER_TOKEN || "";
const OWNER_NAME = process.env.RECORD_OWNER_NAME || "Sriram";
const OWNER_SLUG = "owner";
const LOCAL = process.env.RECORD_LOCAL_DIR;
const PART_MAX = 3.5 * 1024 * 1024;
const PARTS_MAX = 12;
const CONSENT_VERSION = 1;

const VID = /^\d{1,3}\.\d{1,3}$/;
const TEXT = /^[a-z][a-z0-9-]{1,40}$/;
const UPLOAD = /^[A-Za-z0-9_-]{16,64}$/;
const SLUG = /^[a-z0-9-]{1,40}$/;

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

const pairs = (flat) => {
  const o = {};
  for (let i = 0; i + 1 < (flat || []).length; i += 2) o[flat[i]] = flat[i + 1];
  return o;
};
const json = (s, d) => { try { return JSON.parse(s); } catch { return d; } };

// Private audio storage: Vercel Blob, or a folder when testing.
const store = {
  async put(p, buf) {
    if (LOCAL) { const f = path.join(LOCAL, p); fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, buf); return; }
    const { put } = require("@vercel/blob");
    await put(p, buf, { access: "private", contentType: "audio/wav", addRandomSuffix: false, allowOverwrite: true });
  },
  async read(p) {
    if (LOCAL) { const f = path.join(LOCAL, p); return fs.existsSync(f) ? fs.readFileSync(f) : null; }
    const { get } = require("@vercel/blob");
    const r = await get(p, { access: "private", useCache: false });
    if (!r || r.statusCode !== 200) return null;
    return Buffer.from(await new Response(r.stream).arrayBuffer());
  },
  async del(ps) {
    if (!ps.length) return;
    if (LOCAL) { for (const p of ps) fs.rmSync(path.join(LOCAL, p), { force: true }); return; }
    const { del } = require("@vercel/blob");
    await del(ps);
  },
};

const same = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));

async function whoIs(req) {
  const tok = String(req.headers.authorization || "").replace(/^Bearer\s+/i, "").trim();
  if (!tok || tok.length > 200) return null;
  if (OWNER && same(tok, OWNER)) return { slug: OWNER_SLUG, name: OWNER_NAME, owner: true };
  const [slug] = await redis([["GET", `rec:tok:${crypto.createHash("sha256").update(tok).digest("hex")}`]]);
  if (!slug) return null;
  const [v] = await redis([["HGETALL", `rec:voice:${slug}`]]);
  const voice = pairs(v);
  return voice.name ? { slug, name: voice.name, owner: false } : null;
}

function readBody(req) {
  if (req.body && typeof req.body === "object" && !Buffer.isBuffer(req.body)) return req.body;
  try { return JSON.parse(req.body || "{}"); } catch { return {}; }
}

async function rawBody(req) {
  if (Buffer.isBuffer(req.body)) return req.body;
  const chunks = [];
  let n = 0;
  for await (const c of req) {
    n += c.length;
    if (n > PART_MAX) throw Object.assign(new Error("part too large"), { status: 413 });
    chunks.push(c);
  }
  return Buffer.concat(chunks);
}

async function consentOf(slug) {
  const [c] = await redis([["HGETALL", `rec:consent:${slug}`]]);
  const o = pairs(c);
  return o.at ? { publish: o.publish === "1", train: o.train === "1", credit: o.credit || "", at: o.at, version: +o.version || 1 } : null;
}

async function keptOf(slug) {
  const [k] = await redis([["HGETALL", `rec:kept:${slug}`]]);
  const o = pairs(k), out = {};
  for (const key of Object.keys(o)) out[key] = json(o[key], {});
  return out;
}

function slugify(name) {
  const s = name.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 30);
  return s && s !== OWNER_SLUG ? s : "voice";
}

function wavInfo(buf) {
  if (buf.length < 44 || buf.toString("ascii", 0, 4) !== "RIFF" || buf.toString("ascii", 8, 12) !== "WAVE") return null;
  const sr = buf.readUInt32LE(24), ch = buf.readUInt16LE(22), bits = buf.readUInt16LE(34);
  const data = buf.length - 44;
  return { sr, ch, bits, dur: Math.round((data / (sr * ch * (bits / 8))) * 100) / 100 };
}

module.exports = async (req, res) => {
  res.setHeader("Cache-Control", "no-store");
  if (!URL_ || !TOKEN) return res.status(503).json({ ok: false, error: "Recording is not set up yet." });
  const url = new URL(req.url, "http://x");
  const q = Object.fromEntries(url.searchParams);
  let me;
  try { me = await whoIs(req); } catch (e) { console.error("record auth", e); return res.status(502).json({ ok: false, error: "Could not check the passcode just now." }); }
  if (!me) return res.status(401).json({ ok: false, error: "That passcode or link isn't valid." });

  try {
    if (req.method === "GET" && (q.action || "me") === "me") {
      const out = { ok: true, me: { name: me.name, slug: me.slug, owner: me.owner }, consent: me.owner ? { publish: true, train: true, credit: me.name } : await consentOf(me.slug), kept: await keptOf(me.slug), consentVersion: CONSENT_VERSION };
      if (me.owner) {
        const [slugs] = await redis([["SMEMBERS", "rec:voices"]]);
        out.voices = [];
        for (const s of (slugs || []).sort()) {
          const [v] = await redis([["HGETALL", `rec:voice:${s}`]]);
          const voice = pairs(v);
          if (!voice.name) continue;
          out.voices.push({ slug: s, name: voice.name, created: voice.created, link: voice.link || null, revoked: voice.revoked || null, consent: await consentOf(s), kept: await keptOf(s) });
        }
      }
      return res.status(200).json(out);
    }

    if (req.method === "POST" && q.action === "part") {
      if (!UPLOAD.test(q.upload || "") || !/^\d{1,2}$/.test(q.n || "") || +q.n >= PARTS_MAX) return res.status(400).json({ ok: false, error: "Bad part." });
      const [owner] = await redis([["SET", `rec:up:${q.upload}`, me.slug, "NX", "EX", 86400], ["GET", `rec:up:${q.upload}`]]).then((r) => [r[1]]);
      if (owner !== me.slug) return res.status(403).json({ ok: false, error: "Not your upload." });
      const buf = await rawBody(req);
      if (!buf.length) return res.status(400).json({ ok: false, error: "Empty part." });
      await store.put(`uploads/${q.upload}/${+q.n}`, buf);
      return res.status(200).json({ ok: true, n: +q.n, size: buf.length });
    }

    if (req.method === "GET" && q.action === "audio") {
      const voice = q.voice || me.slug;
      if (!TEXT.test(q.text || "") || !VID.test(q.vid || "") || !SLUG.test(voice)) return res.status(400).json({ ok: false });
      if (voice !== me.slug && !me.owner) return res.status(403).json({ ok: false });
      const [k] = await redis([["HGET", `rec:kept:${voice}`, `${q.text}/${q.vid}`]]);
      const take = json(k, null);
      const buf = take && (await store.read(take.path));
      if (!buf) return res.status(404).json({ ok: false, error: "No kept take for that verse." });
      res.setHeader("Content-Type", "audio/wav");
      res.setHeader("Cache-Control", "private, no-store");
      res.setHeader("Content-Disposition", `inline; filename="${q.text}-${q.vid}-${voice}.wav"`);
      return res.status(200).send(buf);
    }

    if (req.method === "GET" && q.action === "export") {
      if (!me.owner) return res.status(403).json({ ok: false });
      const [slugs] = await redis([["SMEMBERS", "rec:voices"]]);
      const voices = [{ slug: OWNER_SLUG, name: OWNER_NAME, consent: { publish: true, train: true, credit: OWNER_NAME } }];
      for (const s of slugs || []) {
        const [v] = await redis([["HGETALL", `rec:voice:${s}`]]);
        voices.push({ slug: s, name: pairs(v).name, consent: await consentOf(s) });
      }
      for (const v of voices) v.kept = await keptOf(v.slug);
      return res.status(200).json({ ok: true, voices });
    }

    if (req.method !== "POST") { res.setHeader("Allow", "GET, POST"); return res.status(405).json({ ok: false }); }
    const body = readBody(req);

    if (body.action === "consent") {
      if (me.owner) return res.status(200).json({ ok: true });
      const credit = String(body.credit || "").trim().slice(0, 80) || me.name;
      const at = new Date().toISOString();
      await redis([["HSET", `rec:consent:${me.slug}`, "publish", body.publish ? "1" : "0", "train", body.train ? "1" : "0", "credit", credit, "at", at, "version", String(CONSENT_VERSION)],
        ["RPUSH", `rec:consentlog:${me.slug}`, JSON.stringify({ publish: !!body.publish, train: !!body.train, credit, at, version: CONSENT_VERSION })]]);
      return res.status(200).json({ ok: true, consent: await consentOf(me.slug) });
    }

    if (body.action === "finish") {
      const parts = +body.parts;
      if (!UPLOAD.test(body.upload || "") || !TEXT.test(body.text || "") || !VID.test(body.vid || "") || !(parts >= 1 && parts <= PARTS_MAX)) return res.status(400).json({ ok: false, error: "Bad take." });
      if (!me.owner && !(await consentOf(me.slug))) return res.status(403).json({ ok: false, error: "Please confirm how your recordings may be used first." });
      const [owner, done] = await redis([["GET", `rec:up:${body.upload}`], ["GET", `rec:done:${body.upload}`]]);
      if (done) return res.status(200).json({ ok: true, take: json(done, {}) }); // a retried finish
      if (owner !== me.slug) return res.status(403).json({ ok: false, error: "Not your upload." });
      const names = Array.from({ length: parts }, (_, i) => `uploads/${body.upload}/${i}`);
      const bufs = [];
      for (const n of names) {
        const b = await store.read(n);
        if (!b) return res.status(409).json({ ok: false, error: "A part is missing; it will be sent again." });
        bufs.push(b);
      }
      const wav = Buffer.concat(bufs);
      const info = wavInfo(wav);
      if (!info) return res.status(400).json({ ok: false, error: "That isn't a WAV recording." });
      const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "");
      const p = `takes/${body.text}/${body.vid}/${me.slug}/${stamp}.wav`;
      await store.put(p, wav);
      const checks = body.checks && typeof body.checks === "object" ? body.checks : {};
      const take = { path: p, dur: info.dur, sr: info.sr, size: wav.length, at: new Date().toISOString(),
        peak: +checks.peak || null, noise: +checks.noise || null, recordedAt: String(body.recordedAt || "").slice(0, 40) };
      const key = `${body.text}/${body.vid}`;
      await redis([["HSET", `rec:kept:${me.slug}`, key, JSON.stringify(take)], ["RPUSH", `rec:history:${me.slug}`, JSON.stringify({ key, ...take })],
        ["SET", `rec:done:${body.upload}`, JSON.stringify(take), "EX", 86400]]);
      await store.del(names).catch((e) => console.warn("record: parts not deleted", e.message));
      return res.status(200).json({ ok: true, take });
    }

    if (body.action === "invite") {
      if (!me.owner) return res.status(403).json({ ok: false });
      const name = String(body.name || "").trim().slice(0, 60);
      if (!name) return res.status(400).json({ ok: false, error: "Give the singer's name." });
      let slug = slugify(name);
      const [taken] = await redis([["SISMEMBER", "rec:voices", slug]]);
      if (taken) slug = `${slug}-${crypto.randomBytes(2).toString("hex")}`;
      const tok = crypto.randomBytes(24).toString("base64url");
      const origin = `https://${req.headers["x-forwarded-host"] || req.headers.host || "samskritam.ai"}`;
      const link = `${origin}/record#k=${tok}`;
      await redis([["SET", `rec:tok:${crypto.createHash("sha256").update(tok).digest("hex")}`, slug],
        ["HSET", `rec:voice:${slug}`, "name", name, "created", new Date().toISOString(), "link", link,
          "tokhash", crypto.createHash("sha256").update(tok).digest("hex")],
        ["SADD", "rec:voices", slug]]);
      return res.status(200).json({ ok: true, voice: { slug, name, link } });
    }

    if (body.action === "revoke") {
      if (!me.owner) return res.status(403).json({ ok: false });
      if (!SLUG.test(body.voice || "")) return res.status(400).json({ ok: false });
      const [v] = await redis([["HGETALL", `rec:voice:${body.voice}`]]);
      const voice = pairs(v);
      // The link stops working; the voice's takes and consent stay until deleted by hand.
      await redis([["DEL", `rec:tok:${voice.tokhash || "-"}`], ["HDEL", `rec:voice:${body.voice}`, "link", "tokhash"],
        ["HSET", `rec:voice:${body.voice}`, "revoked", new Date().toISOString()]]);
      return res.status(200).json({ ok: true });
    }

    return res.status(400).json({ ok: false, error: "Unknown action." });
  } catch (e) {
    console.error("record", e);
    return res.status(e.status || 502).json({ ok: false, error: e.status === 413 ? "That part is too large." : "Something went wrong saving that; it will be tried again." });
  }
};
