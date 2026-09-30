// Render comp.html frame by frame through headless Chrome (CDP, no npm deps).
//   node render.mjs stills 0.9,3.2,...   -> stills/t_<sec>.png
//   node render.mjs frames               -> frames/00000.jpg ... at 30 fps
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const PORT = 9333, FPS = 30;
const [mode = "stills", arg = ""] = process.argv.slice(2);

const profile = join(HERE, "chrome-profile");
const chrome = spawn(CHROME, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--hide-scrollbars", "--force-device-scale-factor=1", "--window-size=1920,1080",
  "--allow-file-access-from-files", "--no-first-run", "--mute-audio",
  "about:blank",
], { stdio: "ignore" });

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function devtools(path, method = "GET") {
  let last;
  for (let i = 0; i < 60; i++) {
    try { const r = await fetch(`http://127.0.0.1:${PORT}${path}`, { method }); if (r.ok) return r.json(); last = `HTTP ${r.status}`; }
    catch (e) { last = e.message; }   // Chrome still starting; after 15 s we fail below
    await sleep(250);
  }
  throw new Error(`Chrome DevTools did not answer ${path}: ${last}`);
}

const page = await devtools(`/json/new?about:blank`, "PUT");
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = bad; });
let seq = 0; const waiting = new Map(), events = [];
ws.onmessage = m => {
  const d = JSON.parse(m.data);
  if (d.id && waiting.has(d.id)) { const { ok, bad } = waiting.get(d.id); waiting.delete(d.id); d.error ? bad(new Error(JSON.stringify(d.error))) : ok(d.result); }
  else if (d.method) {
    events.push(d.method);
    if (d.method === "Runtime.exceptionThrown") console.error("PAGE EXCEPTION:", d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text);
    if (d.method === "Log.entryAdded") console.error("PAGE LOG:", d.params.entry.level, d.params.entry.text, d.params.entry.url ?? "");
  }
};
process.on("exit", () => chrome.kill());
process.on("uncaughtException", e => { console.error(e.message); chrome.kill(); process.exit(1); });
const send = (method, params = {}) => new Promise((ok, bad) => { const id = ++seq; waiting.set(id, { ok, bad }); ws.send(JSON.stringify({ id, method, params })); });
async function evaluate(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`page error: ${JSON.stringify(r.exceptionDetails)}`);
  return r.result.value;
}

await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
await send("Page.enable");
await send("Runtime.enable");
await send("Log.enable");
await send("Page.navigate", { url: pathToFileURL(join(HERE, "comp.html")).href });
for (let i = 0; i < 80 && !events.includes("Page.loadEventFired"); i++) await sleep(100);
if (!events.includes("Page.loadEventFired")) throw new Error("comp.html did not load");
await evaluate("window.READY");
const duration = await evaluate("window.DURATION");

async function frameAt(t, format) {
  await evaluate(`window.renderAt(${t}); new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))`);
  const shot = await send("Page.captureScreenshot", format === "png" ? { format: "png" } : { format: "jpeg", quality: 94 });
  return Buffer.from(shot.data, "base64");
}

const t0 = Date.now();
if (mode === "stills") {
  const dir = join(HERE, "stills"); mkdirSync(dir, { recursive: true });
  for (const s of arg.split(",").filter(Boolean)) writeFileSync(join(dir, `t_${Number(s).toFixed(2)}.png`), await frameAt(Number(s), "png"));
} else {
  const dir = join(HERE, "frames"); rmSync(dir, { recursive: true, force: true }); mkdirSync(dir, { recursive: true });
  const n = Math.round(duration * FPS);
  for (let f = 0; f < n; f++) {
    writeFileSync(join(dir, String(f).padStart(5, "0") + ".jpg"), await frameAt(f / FPS, "jpeg"));
    if (f % 90 === 0) console.log(`frame ${f}/${n}`);
  }
  console.log(`${n} frames`);
}
console.log(`done in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
ws.close(); chrome.kill();
