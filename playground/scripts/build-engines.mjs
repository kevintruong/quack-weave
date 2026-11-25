import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";

const version = "v1.5.4"; // The engine inside @duckdb/duckdb-wasm 1.33.1-dev57.0.
const extensions = ["json", "parquet"];

const licenseDirectory = new URL("../public/licenses/", import.meta.url);
await mkdir(licenseDirectory, { recursive: true });
await copyFile(
  new URL("../node_modules/apache-arrow/NOTICE.txt", import.meta.url),
  new URL("apache-arrow-notice.txt", licenseDirectory),
);

await Promise.all(["wasm_eh", "wasm_mvp"].map(async platform => {
  const directory = new URL(`../public/duckdb-extensions/${version}/${platform}/`, import.meta.url);
  await mkdir(directory, { recursive: true });
  await Promise.all(extensions.map(async extension => {
    const filename = `${extension}.duckdb_extension.wasm`;
    const target = new URL(filename, directory);
    const cached = await readFile(target).catch(() => null);
    if (cached && WebAssembly.validate(cached)) return;
    const url = `https://extensions.duckdb.org/${version}/${platform}/${filename}`;
    const response = await fetch(url, { signal: AbortSignal.timeout(60_000) });
    if (!response.ok) throw new Error(`Could not download ${url} (HTTP ${response.status})`);
    const binary = new Uint8Array(await response.arrayBuffer());
    if (!WebAssembly.validate(binary)) throw new Error(`Invalid WebAssembly from ${url}`);
    await writeFile(target, binary);
  }));
}));
