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
