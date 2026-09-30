// Download the pinned Laya bundle once, then verify it.
//
//   node fetch-model.mjs                 download (if needed) + verify
//   node fetch-model.mjs --verify-only   verify an existing bundle, no network
//   node fetch-model.mjs --pin           first run only: record hashes for the
//                                        small files Hugging Face does not hash
//
// Destination: LAYA_MODEL_DIR, default ~/.cache/anumaan-laya/<revision>.
// After this, the server loads from that directory and never touches the
// network - the bundle can be copied to an air-gapped NIC / MeghRaj host.
import { writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ensureBundle } from "@receptron/laya";
import { loadManifest, verifyBundle } from "./verify.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = new Set(process.argv.slice(2));
const manifest = await loadManifest();
const cacheRoot = process.env.LAYA_CACHE_ROOT ?? path.join(homedir(), ".cache", "anumaan-laya");

let modelDir = process.env.LAYA_MODEL_DIR;
if (!args.has("--verify-only")) {
  let last = -1;
  modelDir = await ensureBundle({
    repo: manifest.repo,
    revision: manifest.revision,
    cacheDir: cacheRoot,
    onProgress: ({ file, received, total }) => {
      const pct = total ? Math.floor((received / total) * 100) : -1;
      if (pct !== last && pct % 10 === 0) {
        last = pct;
        console.log(`  ${file}: ${pct}%`);
      }
    },
  });
}
if (!modelDir) {
  modelDir = path.join(cacheRoot, manifest.repo.replace("/", "--"), manifest.revision);
}

const res = await verifyBundle(modelDir, manifest);
if (args.has("--pin")) {
  let changed = 0;
  for (const [name, want] of Object.entries(manifest.files)) {
    if (want.sha256 === null && res.computed[name]) {
      want.sha256 = res.computed[name];
      changed += 1;
    }
  }
  await writeFile(path.join(HERE, "model-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  console.log(`pinned ${changed} previously unhashed file(s)`);
  const again = await verifyBundle(modelDir, manifest);
  if (!again.ok) {
    console.error("verification failed after pinning:\n  - " + again.problems.join("\n  - "));
    process.exit(1);
  }
} else if (!res.ok) {
  console.error("model verification failed:\n  - " + res.problems.join("\n  - "));
  process.exit(1);
}
console.log(`model ok: ${Object.keys(manifest.files).length} files verified in ${modelDir}`);
console.log(`start the sidecar with LAYA_MODEL_DIR=${modelDir}`);
