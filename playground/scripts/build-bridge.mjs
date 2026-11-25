import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
mkdirSync(new URL("../public/", import.meta.url), { recursive: true });
execFileSync("rustc", [
  "--edition=2024",
  "--crate-type=cdylib",
  "--target=wasm32-unknown-unknown",
  "-C", "opt-level=s",
  "-C", "panic=abort",
  "-C", "strip=symbols",
  "-o", "public/bridge.wasm",
  "schema-bridge.rs",
], { cwd: root, stdio: "inherit" });
