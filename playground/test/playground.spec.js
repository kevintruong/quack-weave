import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("./");
  const status = page.getByRole("status", { name: "Engine status" });
  await expect(status).not.toHaveText("Starting engines", { timeout: 25_000 });
  await expect(status, await page.locator("#query-error").textContent()).toHaveText("Engines ready", { timeout: 100 });
});

test("guided hybrid example runs DuckDB SQL over live Ladybug results", async ({ page }) => {
  await page.getByRole("button", { name: "Join both engines" }).click();
  await page.getByRole("button", { name: "Load query" }).click();
  const editor = page.getByRole("textbox", { name: "Query editor" });
  await expect(editor).toHaveValue(/source\.id = 100/);
  await page.getByRole("button", { name: "Run query" }).click();
  const table = page.getByRole("table", { name: "Query results" });
  await expect(table.getByText("Vector Search for Archives")).toBeVisible();
  await expect(table.getByText("SIGIR")).toBeVisible();
  await expect(page.getByText(/Arrow data transferred/)).toBeVisible();

  await editor.fill((await editor.inputValue()).replace("source.id = 100", "source.id = 101"));
  await editor.press("Control+Enter");
  await expect(table.getByText("Provenance in Digital Libraries")).toBeVisible();
  await expect(table.getByText("Vector Search for Archives")).toHaveCount(0);
});

test("plain SQL and Cypher work, and a bad schema leaves the session usable", async ({ page }) => {
  const editor = page.getByRole("textbox", { name: "Query editor" });
  await page.getByRole("button", { name: "SQL mode" }).click();
  await editor.fill("SELECT 6 * 7 AS answer");
  await page.getByRole("button", { name: "Run query" }).click();
  const table = page.getByRole("table", { name: "Query results" });
  await expect(table.getByRole("cell", { name: "42" })).toBeVisible();

  await page.getByRole("button", { name: "Cypher mode" }).click();
  await editor.fill("MATCH (p:Document) WHERE p.id = 100 RETURN p.title AS paper");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(table.getByText("Mapping Research Networks")).toBeVisible();

  await page.getByRole("button", { name: "SQL mode" }).click();
  await editor.fill("SELECT * FROM qw_query('kg', 'cypher', $$MATCH (p:Document) RETURN p.id AS id$$, schema := 'id VARCHAR')");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.getByRole("alert")).toContainText("QW_SCHEMA");

  await editor.fill("SELECT * FROM qw_query('kg', 'cypher', $$MATCH (p:Document) WHERE p.id = 0 RETURN p.id AS id$$, schema := 'id BIGINT')");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(table.getByRole("columnheader", { name: "id" })).toBeVisible();
  await expect(page.getByText("0 rows", { exact: true })).toBeVisible();
});

test("graph data remains readable after a rejected write", async ({ page }) => {
  await page.getByRole("button", { name: "Cypher mode" }).click();
  const editor = page.getByRole("textbox", { name: "Query editor" });
  await editor.fill("MATCH (p:Document) DELETE p");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.getByRole("alert")).toContainText(/read.only/i);

  await editor.fill("MATCH (p:Document) RETURN COUNT(*) AS papers");
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.getByRole("table").getByRole("cell", { name: "12", exact: true })).toBeVisible();
});

test("typed graph results preserve large integers and non-ASCII text", async ({ page }) => {
  await page.getByRole("button", { name: "SQL mode" }).click();
  const editor = page.getByRole("textbox", { name: "Query editor" });
  await editor.fill(`SELECT * FROM qw_query('kg', 'cypher',
    $$RETURN 9007199254740993 AS id, true AS found, 1.25 AS score, 'café' AS title$$,
    schema := 'id BIGINT, found BOOLEAN, score DOUBLE, title VARCHAR'
  )`);
  await page.getByRole("button", { name: "Run query" }).click();
  const table = page.getByRole("table", { name: "Query results" });
  for (const value of ["9007199254740993", "true", "1.25", "café"]) {
    await expect(table.getByRole("cell", { name: value, exact: true })).toBeVisible();
  }
});

test("the mobile console runs a guided graph query without horizontal page overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Follow two hops" }).click();
  await page.getByRole("button", { name: "Load query" }).click();
  await page.getByRole("button", { name: "Run query" }).click();
  await expect(page.getByRole("table").getByRole("cell", { name: "Provenance in Digital Libraries" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});
