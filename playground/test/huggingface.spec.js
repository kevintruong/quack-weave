import { expect, test } from "@playwright/test";
import { createRequire } from "node:module";
import { mkdir, readFile } from "node:fs/promises";

const lbug = createRequire(import.meta.url)("@ladybugdb/wasm-core/nodejs/sync");
const sha = "0123456789abcdef0123456789abcdef01234567";

test("select a public dataset file, query its immutable graph and recover from a failed switch", async ({ page, context }, testInfo) => {
  await lbug.init();
  const path = testInfo.outputPath("fixture.lbdb");
  await mkdir(testInfo.outputDir, { recursive: true });
  const db = new lbug.Database(path, 0, 1);
  const conn = new lbug.Connection(db, 1);
  try {
    const seed = conn.query("CREATE NODE TABLE City(id INT64 PRIMARY KEY); CREATE (:City {id: 73}); CHECKPOINT;");
    try { for (const r of seed) expect(r.isSuccess()).toBeTruthy(); }
    finally { seed.close(); }
  } finally { conn.close(); db.close(); }
  const bytes = await readFile(path);
  let rangeReads = 0;
  const file = "graphs/cities.lbdb";
  await context.route("https://huggingface.co/**", async route => {
    const req = route.request();
    const url = new URL(req.url());
    const headers = { "access-control-allow-origin": "*", "access-control-expose-headers": "Content-Length,Content-Range" };
    if (["main", sha].some(ref => url.pathname === `/api/datasets/test-org/public-graphs/revision/${ref}`)) {
      return route.fulfill({ headers, json: { sha, siblings: [
        { rfilename: file }, { rfilename: "other.lbdb" }, { rfilename: "dirty.lbdb" }, { rfilename: "dirty.lbdb.wal", size: 10 },
      ] } });
    }
    if (url.pathname !== `/datasets/test-org/public-graphs/resolve/${sha}/${file}`) {
      return route.fulfill({ status: 404, headers, body: "" });
    }
    if (req.method() === "HEAD") {
      return route.fulfill({ headers: { ...headers, "content-length": String(bytes.length) }, body: "" });
    }
    expect(req.method()).toBe("GET");
    const range = /^bytes=(\d+)-(\d+)$/.exec(req.headers().range);
    expect(range).toBeTruthy();
    const [start, end] = range.slice(1).map(Number);
    rangeReads++;
    return route.fulfill({ status: 206, headers: { ...headers, "content-range": `bytes ${start}-${end}/${bytes.length}` }, body: bytes.subarray(start, end + 1) });
  });
  await page.goto("./");
  await expect(page.getByRole("button", { name: "Run query" })).toBeEnabled();
  await page.getByRole("combobox", { name: "Graph source" }).selectOption("huggingface");
  await page.getByLabel("Dataset or file").fill("test-org/public-graphs");
  await page.getByRole("button", { name: "Open graph" }).click();
  await page.getByLabel("Database file").selectOption(file);
  await page.getByRole("button", { name: "Open graph" }).click();
  await expect(page.locator("#active-graph")).toContainText(file);
  const editor = page.getByRole("textbox", { name: "Query editor" });
  await editor.fill("MATCH (c:City) RETURN c.id AS city_id");
  await editor.press("Control+Enter");
  await expect(page.getByRole("cell", { name: "73" })).toBeVisible();
  expect(rangeReads).toBeGreaterThan(0);
  await editor.fill("CREATE (:City {id: 74})");
  await editor.press("Control+Enter");
  await expect(page.locator("#query-error")).toContainText(/read.only/i);
  const location = page.getByLabel("Dataset or file");
  await location.fill(`xet://datasets/test-org/public-graphs/${sha}/dirty.lbdb`);
  await page.getByRole("button", { name: "Open graph" }).click();
  await expect(page.locator("#source-error")).toContainText("pending WAL");
  await location.fill("https://huggingface.co/datasets/test-org/public-graphs/blob/main/other.lbdb");
  await page.getByRole("button", { name: "Open graph" }).click();
  await expect(page.locator("#source-error")).toContainText(/invalid path/i);
  await location.fill("https://huggingface.co/datasets/test-org/missing/blob/main/closed.lbdb");
  await page.getByRole("button", { name: "Open graph" }).click();
  await expect(page.locator("#source-error")).toContainText("404");
  await page.getByRole("button", { name: "SQL mode" }).click();
  await editor.fill("SELECT * FROM GRAPH_TABLE (kg MATCH (c:City) COLUMNS (c.id AS city_id))");
  await editor.press("Control+Enter");
  await expect(page.getByRole("cell", { name: "73" })).toBeVisible();
  await page.getByRole("combobox", { name: "Graph source" }).selectOption("papertrail");
  await expect(page.locator("#active-graph")).toContainText("PaperTrail");
  await expect(page.getByRole("button", { name: "Explore citations" })).toBeVisible();
});
