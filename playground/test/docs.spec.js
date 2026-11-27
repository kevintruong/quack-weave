import { expect, test } from "@playwright/test";

test("the Playground links to the capability guide and its evidence", async ({ page, request, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./");
  await page.getByRole("link", { name: "Documentation" }).click();

  const docsUrl = new URL("docs/", baseURL);
  await expect(page).toHaveURL(docsUrl.href);
  await expect(page.getByRole("heading", { name: "Quack Weave documentation" })).toBeVisible();
  const build = page.locator("#build");
  await expect(build).toContainText("Ladybug");
  await expect(build).toContainText("RelateDB");
  await expect(build).toContainText("Neo4j Aura");
  await expect(build.locator("pre").first()).toContainText("make native-deps && make native-release");
  await expect(build.locator("pre", { hasText: "LOAD" })).toHaveCount(1);
  await expect(page.getByRole("heading", { name: "SQLLogic evidence" })).toBeVisible();
  await expect(page.locator("#query h3").first()).toHaveText("SQL/PGQ with GRAPH_TABLE");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  const evidence = await request.get(new URL("evidence.json", docsUrl).href);
  expect(evidence.ok()).toBeTruthy();
  const manifest = await evidence.json();
  const providers = manifest.verification.standard_provider_package.provider_inventory;
  expect(providers.map(({ provider_id }) => provider_id)).toEqual(["ladybug", "neo4j", "relate"]);
  for (const id of ["native-debug", "native-release"]) {
    expect(manifest.suites.find((suite) => suite.id === id)?.cases).toEqual(
      expect.arrayContaining([expect.objectContaining({
        path: "test/stabilization/sqllogic/native_surface.test",
        status: "passed",
      })]),
    );
  }
  expect(manifest.suites.some(({ id }) => id === "neo4j-tls")).toBeTruthy();
  await page.getByRole("link", { name: "Playground", exact: true }).click();
  await expect(page).toHaveURL(baseURL);
});

test("benchmark charts switch between comparable measurements and sample counts", async ({ page, request, baseURL }) => {
  const docsUrl = new URL("docs/", baseURL);
  await page.goto(docsUrl.href);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "Benchmarks", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Performance benchmarks" })).toBeVisible();
  const chart = page.getByRole("figure", { name: "Benchmark comparison" });
  await expect(chart).toContainText("Selective creator join");
  await expect(chart).toContainText("119,052");
  await expect(chart).toContainText("81.828");
  await expect(chart).toContainText("1.751");

  await page.getByLabel("Metric").selectOption("p95");
  await expect(chart).toContainText("88.404");
  await page.getByLabel("Metric").selectOption("rows");
  await expect(chart).toContainText("734");

  await page.getByRole("button", { name: "Fanout experiment" }).click();
  await page.getByLabel("Provider").selectOption("ladybug");
  await page.getByLabel("Metric").selectOption("p50");
  await expect(chart).toContainText("Hot keys");
  await expect(chart).toContainText("5.203");
  await page.getByLabel("Run", { exact: true }).selectOption("0");
  await expect(chart).toContainText("5.332");

  await page.getByRole("button", { name: "Full SF1 baseline" }).click();
  await expect(chart).toContainText("log scale");
  await expect(chart).toContainText("Direct Cypher");
  await page.getByLabel("Metric").selectOption("rows");
  await expect(chart).toContainText("6,465");
  await expect(chart).not.toContainText("Lookup hit");
  await page.getByText("Measurement table", { exact: true }).click();
  const table = page.getByRole("table", { name: "Selected benchmark measurements" });
  await expect(table.getByRole("row", { name: /Graph-local equality/ })).toContainText("20");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  const data = await request.get(new URL("benchmark-data.js", docsUrl).href);
  expect(data.ok()).toBeTruthy();
});
