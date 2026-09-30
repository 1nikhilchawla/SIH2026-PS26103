// ANUMAAN Laya sidecar - local System-1 triage for field remarks.
//
// Laya (@receptron/laya) is the open-weights, Jev-compatible decision model:
// one forward pass returns calibrated probabilities over typed questions, no
// text generation. It runs here, beside ANUMAAN, on CPU. Nothing leaves the
// server: there is no hosted AI API and, once the bundle is on disk, no
// network access at all.
//
// Security posture
//   - Refuses to start without LAYA_TOKEN (32+ chars) and a model directory
//     whose every file matches model-manifest.json by size and SHA-256.
//   - Loads with `modelDir`, so @receptron/laya never downloads anything.
//   - Binds 127.0.0.1 by default; in Docker it sits on an internal network
//     with no published port. Every inference call needs X-Laya-Token.
//   - 16 KB body cap, 4,000-character state cap, at most 8 questions.
//   - One inference at a time (bounded memory, predictable latency).
//   - Never logs request text - only timings and status.
import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import { performance } from "node:perf_hooks";
import { Laya } from "@receptron/laya";
import { loadManifest, verifyBundle } from "./verify.mjs";

const HOST = process.env.LAYA_HOST ?? "127.0.0.1";
const PORT = Number(process.env.LAYA_PORT ?? "8090");
const TOKEN = process.env.LAYA_TOKEN ?? "";
const MODEL_DIR = process.env.LAYA_MODEL_DIR ?? "";
const MAX_BODY = 16 * 1024;
const MAX_STATE_CHARS = 4000;
const MAX_QUESTIONS = 8;
const QTYPES = new Set(["choice", "score", "noul"]);

function refuse(msg) {
  console.error(`[laya] refusing to start: ${msg}`);
  process.exit(1);
}
if (TOKEN.length < 32) refuse("LAYA_TOKEN must be set to 32+ characters");
if (!MODEL_DIR) refuse("LAYA_MODEL_DIR must point at a verified bundle - run: node fetch-model.mjs");
if (!Number.isInteger(PORT) || PORT < 1 || PORT > 65535) refuse(`LAYA_PORT ${PORT} is not a port`);

const manifest = await loadManifest();
let t0 = performance.now();
const check = await verifyBundle(MODEL_DIR, manifest);
if (!check.ok) refuse("model verification failed: " + check.problems.join("; "));
console.log(`[laya] model verified in ${Math.round(performance.now() - t0)} ms (revision ${manifest.revision})`);
t0 = performance.now();
const laya = await Laya.load({ modelDir: MODEL_DIR });
console.log(`[laya] model loaded in ${Math.round(performance.now() - t0)} ms`);

const tokenBuf = Buffer.from(TOKEN, "utf8");
function authorised(req) {
  const got = Buffer.from(String(req.headers["x-laya-token"] ?? ""), "utf8");
  return got.length === tokenBuf.length && timingSafeEqual(got, tokenBuf);
}

// Serialise inference: a queue of one.
let tail = Promise.resolve();
function serialised(fn) {
  const run = tail.then(fn, fn);
  tail = run.catch(() => undefined);
  return run;
}

function validate(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return "body must be a JSON object";
  const { state, questions } = body;
  if (!state || typeof state !== "object" || Array.isArray(state)) return "state must be an object";
  const chars = JSON.stringify(state).length;
  if (chars > MAX_STATE_CHARS) return `state is ${chars} characters, limit ${MAX_STATE_CHARS}`;
  if (!questions || typeof questions !== "object" || Array.isArray(questions)) return "questions must be an object";
  const ids = Object.keys(questions);
  if (ids.length < 1 || ids.length > MAX_QUESTIONS) return `between 1 and ${MAX_QUESTIONS} questions`;
  for (const id of ids) {
    const q = questions[id];
    if (!q || typeof q !== "object" || !QTYPES.has(q.type)) return `question ${id}: type must be choice, score or noul`;
  }
  return null;
}

function send(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/health") {
    return send(res, 200, { status: "ok", model: manifest.repo, revision: manifest.revision });
  }
  if (req.url !== "/v1/system-one") return send(res, 404, { detail: "not found" });
  if (req.method !== "POST") return send(res, 405, { detail: "method not allowed" });
  if (!authorised(req)) return send(res, 401, { detail: "unauthorised" });
  const declared = Number(req.headers["content-length"]);
  if (!Number.isInteger(declared)) return send(res, 411, { detail: "Content-Length required" });
  if (declared > MAX_BODY) return send(res, 413, { detail: "body too large" });

  const chunks = [];
  let size = 0;
  req.on("data", (c) => {
    size += c.length;
    if (size > MAX_BODY) {
      send(res, 413, { detail: "body too large" });
      req.destroy();
      return;
    }
    chunks.push(c);
  });
  req.on("end", async () => {
    if (res.writableEnded) return;
    let body;
    try {
      body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    } catch {
      return send(res, 400, { detail: "invalid JSON" });
    }
    const problem = validate(body);
    if (problem) return send(res, 422, { detail: problem });
    const t = performance.now();
    try {
      const out = await serialised(() => laya.systemOne(body.state, body.questions));
      const ms = Math.round((performance.now() - t) * 10) / 10;
      console.log(`[laya] 200 ${ms} ms, ${Object.keys(body.questions).length} question(s)`);
      send(res, 200, { ...out, ms, revision: manifest.revision });
    } catch (e) {
      const msg = String(e && e.message ? e.message : e).slice(0, 200);
      console.error(`[laya] inference error: ${msg}`);
      send(res, 422, { detail: "inference failed: " + msg });
    }
  });
});
server.requestTimeout = 15000;
server.headersTimeout = 5000;
server.listen(PORT, HOST, () => console.log(`[laya] listening on http://${HOST}:${PORT}`));

for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, async () => {
    server.close();
    await laya.close();
    process.exit(0);
  });
}
