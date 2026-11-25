import { expect, test } from "@playwright/test";

test("the Playground links to the capability guide and its evidence", async ({ page, request, baseURL }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./");
  await page.getByRole("link", { name: "Documentation" }).click();

  const docsUrl = new URL("docs/", baseURL);
  await expect(page).toHaveURL(docsUrl.href);
  await expect(page.getByRole("heading", { name: "Quack Weave documentation" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "SQLLogic evidence" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);

  const evidence = await request.get(new URL("evidence.json", docsUrl).href);
  expect(evidence.ok()).toBeTruthy();
  const manifest = await evidence.json();
  expect(manifest.suites.some(({ id }) => id === "neo4j-tls")).toBeTruthy();
  await page.getByRole("link", { name: "Playground", exact: true }).click();
  await expect(page).toHaveURL(baseURL);
});
