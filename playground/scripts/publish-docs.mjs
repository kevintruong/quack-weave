import { copyFile, mkdir } from "node:fs/promises";

const source = new URL("../../docs/", import.meta.url);
const destination = new URL("../dist/docs/", import.meta.url);

await mkdir(destination, { recursive: true });
for (const file of ["index.html", "styles.css", "evidence.json"]) {
  await copyFile(new URL(file, source), new URL(file, destination));
}
