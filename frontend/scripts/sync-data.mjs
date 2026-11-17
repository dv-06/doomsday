// Copies the committed data/ folder into the Vite public dir so a static build
// always ships the newest snapshot. Runs automatically before dev/build.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const source = resolve(here, "../../data");
const target = resolve(here, "../public/data");

if (!existsSync(source)) {
  console.warn(`[sync-data] no data directory at ${source}; skipping`);
  process.exit(0);
}

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });

for (const entry of ["latest.json", "meta.json", "sources.json", "state.json", "history", "snapshots", "seatmaps"]) {
  const from = resolve(source, entry);
  if (!existsSync(from)) continue;
  cpSync(from, resolve(target, entry), { recursive: true });
}

// Cache files are local-only and never published.
rmSync(resolve(target, "cache"), { recursive: true, force: true });
console.log(`[sync-data] copied ${source} -> ${target}`);
