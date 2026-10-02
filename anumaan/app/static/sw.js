// ANUMAAN service worker - the offline-first part of the web app.
//
// What it caches, and when:
//   app shell   the page, script and icon: cached on install, served cache-
//               first, refreshed in the background. Holds no project data.
//   snapshot    /api/snapshot: cached ONLY when the user presses "Save for
//               offline use" (the page posts a message), and then refreshed
//               with If-None-Match, so an unchanged month costs a 304.
//               Nothing with project data is cached without that choice.
// Everything else under /api/ goes to the network and is never cached.
// "Clear offline data" (or signing out of the device) deletes both caches.
const SHELL = "anumaan-shell-v3";   // bump on every UI change: index.html and app.js must update together
const DATA = "anumaan-data-v1";
const SHELL_FILES = ["/", "/static/app.js", "/static/icon.svg", "/manifest.webmanifest"];

// cache: "reload" skips the browser's HTTP cache, which can still hold the
// previous app.js for hours; without it a new version caches the old script.
self.addEventListener("install", (event) => {
  const fresh = SHELL_FILES.map((u) => new Request(u, { cache: "reload" }));
  event.waitUntil(caches.open(SHELL).then((c) => c.addAll(fresh)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== SHELL && k !== DATA).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

async function shellFirst(request) {
  const cache = await caches.open(SHELL);
  const hit = await cache.match(request, { ignoreSearch: true });
  // "no-cache" revalidates with the server (an unchanged file costs a 304).
  const refresh = fetch(request, { cache: "no-cache" })
    .then((res) => { if (res.ok) cache.put(request, res.clone()); return res; })
    .catch(() => null);
  return hit || (await refresh) || new Response("offline", { status: 503 });
}

async function snapshotNetworkFirst(request) {
  const cache = await caches.open(DATA);
  const held = await cache.match("/api/snapshot");
  if (!held) {
    // not saved for offline use: plain network, nothing stored
    return fetch(request);
  }
  try {
    const headers = new Headers(request.headers);
    const etag = held.headers.get("ETag");
    if (etag) headers.set("If-None-Match", etag);
    const res = await fetch(new Request(request, { headers }));
    if (res.status === 304) return held.clone();
    if (res.ok) { await cache.put("/api/snapshot", res.clone()); }
    return res;
  } catch (e) {
    const offline = held.clone();
    return new Response(offline.body, { status: 200, headers: { "Content-Type": "application/json", "X-Anumaan-Offline": "1" } });
  }
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || event.request.method !== "GET") return;
  if (url.pathname === "/api/snapshot") { event.respondWith(snapshotNetworkFirst(event.request)); return; }
  if (url.pathname.startsWith("/api/")) return;              // network only, never cached
  if (SHELL_FILES.includes(url.pathname) || event.request.mode === "navigate") {
    event.respondWith(shellFirst(url.pathname === "/" || event.request.mode === "navigate" ? new Request("/") : event.request));
  }
});

self.addEventListener("message", async (event) => {
  const msg = event.data || {};
  if (msg.type === "save-snapshot") {
    const res = await fetch("/api/snapshot", { credentials: "same-origin" });
    if (res.ok) {
      const cache = await caches.open(DATA);
      await cache.put("/api/snapshot", res.clone());
      const bytes = (await res.arrayBuffer()).byteLength;
      event.source.postMessage({ type: "snapshot-saved", bytes, etag: res.headers.get("ETag") });
    } else {
      event.source.postMessage({ type: "snapshot-failed", status: res.status });
    }
  }
  if (msg.type === "clear") {
    await caches.delete(DATA);
    event.source.postMessage({ type: "cleared" });
  }
});
