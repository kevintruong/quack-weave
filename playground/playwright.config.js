import { defineConfig } from "@playwright/test";

const publishedUrl = process.env.PLAYGROUND_URL;

export default defineConfig({
  testDir: "./test",
  use: {
    baseURL: publishedUrl || "http://127.0.0.1:4173/quack-weave/",
    launchOptions: { executablePath: process.env.PLAYGROUND_CHROME || undefined },
  },
  webServer: publishedUrl ? undefined : {
    command: "npm run preview -- --base /quack-weave/ --host 127.0.0.1 --strictPort",
    url: "http://127.0.0.1:4173/quack-weave/",
  },
});
