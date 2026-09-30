// Model integrity check shared by fetch-model.mjs and server.mjs.
// Every file in the pinned bundle must match model-manifest.json by size and
// SHA-256. A mismatch is fatal: a swapped weight file is a swapped model.
import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

export async function loadManifest() {
  return JSON.parse(await readFile(path.join(HERE, "model-manifest.json"), "utf8"));
}

export function sha256File(file) {
  return new Promise((resolve, reject) => {
    const h = createHash("sha256");
    createReadStream(file).on("data", (c) => h.update(c)).on("end", () => resolve(h.digest("hex"))).on("error", reject);
  });
}

/** Returns {ok, problems, computed}. `computed` holds every file's real hash. */
export async function verifyBundle(modelDir, manifest) {
  const problems = [];
  const computed = {};
  for (const [name, want] of Object.entries(manifest.files)) {
    const file = path.join(modelDir, ...name.split("/"));
    let size;
    try {
      size = (await stat(file)).size;
    } catch {
      problems.push(`missing: ${name}`);
      continue;
    }
    if (size !== want.size) problems.push(`size: ${name} is ${size}, pinned ${want.size}`);
    const got = await sha256File(file);
    computed[name] = got;
    if (want.sha256 === null) problems.push(`unpinned: ${name} (sha256 ${got}) - run fetch-model.mjs --pin once`);
    else if (got !== want.sha256) problems.push(`sha256: ${name} is ${got}, pinned ${want.sha256}`);
  }
  return { ok: problems.length === 0, problems, computed };
}
