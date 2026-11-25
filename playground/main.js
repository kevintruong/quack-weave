import "./styles.css";
import { examples } from "./examples.js";
import { startEngines } from "./engines.js";

const get = id => document.getElementById(id);
const editor = get("editor");
const exampleList = get("examples");
const engineStatus = document.querySelector(".engine-status");
const resultPanel = document.querySelector(".results-panel");
const modeButtons = [...document.querySelectorAll("[data-mode]")];
const runButton = get("run-query");
const copyButton = get("copy-query");
const displayLimit = 200;
const drafts = { sql: examples[1].sql, cypher: examples[0].sql };
let selectedExample = 0;
let mode = "cypher";
let engines;
let running = false;

function switchMode(next) {
  drafts[mode] = editor.value;
  mode = next;
  editor.value = drafts[mode];
  for (const button of modeButtons) {
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
  }
}

function selectExample(index) {
  selectedExample = index;
  get("example-description").textContent = examples[index].detail;
  for (const [position, button] of Array.from(exampleList.children).entries()) {
    button.setAttribute("aria-pressed", String(position === index));
  }
}

examples.forEach((example, index) => {
  const button = document.createElement("button");
  button.className = "example";
  const engine = document.createElement("small");
  engine.textContent = index === 2 ? "SQL + Cypher" : example.mode === "sql" ? "SQL" : "Cypher";
  const number = document.createElement("span");
  number.className = "step";
  number.textContent = index + 1;
  number.setAttribute("aria-hidden", "true");
  const label = document.createElement("span");
  label.append(document.createTextNode(example.title), engine);
  button.append(number, label);
  button.setAttribute("aria-label", example.title);
  button.addEventListener("click", () => selectExample(index));
  exampleList.append(button);
});

editor.value = drafts[mode];
switchMode(mode);
selectExample(selectedExample);
for (const button of modeButtons) {
  button.addEventListener("click", () => switchMode(button.dataset.mode));
}
get("load-query").addEventListener("click", () => {
  const example = examples[selectedExample];
  switchMode(example.mode);
  editor.value = example.sql;
  editor.focus();
});
copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(editor.value);
    copyButton.textContent = "Copied";
  } catch {
    editor.select();
    copyButton.textContent = "Text selected";
  }
});
editor.addEventListener("input", () => { copyButton.textContent = "Copy query"; });
get("reset-workspace").addEventListener("click", () => window.location.reload());
if (/Mac|iPhone|iPad/.test(navigator.platform)) get("shortcut-label").textContent = "⌘";

function display(value) {
  if (value === null || value === undefined) return "NULL";
  if (typeof value === "object") {
    return JSON.stringify(value, (_, nested) => typeof nested === "bigint" ? String(nested) : nested);
  }
  return String(value);
}

function cell(tag, value) {
  const element = document.createElement(tag);
  element.textContent = display(value);
  if (value === null) element.className = "null";
  return element;
}

function showRows(result, elapsed) {
  const header = get("result-summary");
  const count = document.createElement("span");
  count.textContent = `${result.rows.length.toLocaleString()} ${result.rows.length === 1 ? "row" : "rows"}`;
  const engine = document.createElement("span");
  engine.className = "engine-chip";
  engine.textContent = result.engine;
  const timing = document.createElement("span");
  timing.textContent = `${Math.round(elapsed)} ms`;
  header.replaceChildren(engine, count, timing);

  const table = document.createElement("table");
  table.setAttribute("aria-label", "Query results");
  const headings = table.createTHead().insertRow();
  for (const name of result.columns) {
    const heading = cell("th", name);
    heading.scope = "col";
    headings.append(heading);
  }
  const body = table.createTBody();
  for (const values of result.rows.slice(0, displayLimit)) {
    const row = body.insertRow();
    row.append(...values.map(value => cell("td", value)));
  }
  if (result.columns.length) get("result-table").append(table);
  const info = get("result-empty");
  if (result.rows.length > displayLimit) {
    info.textContent = `Showing the first ${displayLimit} rows.`;
    info.hidden = false;
  } else if (!result.rows.length) {
    info.textContent = result.columns.length ? "The query returned no rows." : "Query completed.";
    info.hidden = false;
  }
  if (result.arrowBytes !== undefined && result.engine === "Ladybug → DuckDB") {
    const transfer = get("result-transfer");
    transfer.hidden = false;
    transfer.textContent = `Arrow data transferred · ${result.arrowRows.toLocaleString()} rows · ${result.arrowBytes.toLocaleString()} bytes`;
  }
}

function showError(error) {
  const element = get("query-error");
  element.hidden = false;
  element.textContent = error instanceof Error ? error.message : String(error);
}

async function runQuery() {
  if (!engines || running) return;
  const query = editor.value.trim();
  get("query-error").hidden = true;
  get("result-empty").hidden = true;
  get("result-transfer").hidden = true;
  get("result-table").replaceChildren();
  get("result-summary").textContent = "";
  if (!query) {
    showError("Enter a query to run.");
    editor.focus();
    return;
  }
  running = true;
  runButton.disabled = true;
  resultPanel.setAttribute("aria-busy", "true");
  get("result-summary").textContent = "Running query…";
  const start = performance.now();
  try {
    showRows(await engines.run(mode, query), performance.now() - start);
  } catch (error) {
    get("result-summary").textContent = "";
    showError(error);
  } finally {
    running = false;
    runButton.disabled = false;
    resultPanel.setAttribute("aria-busy", "false");
  }
}

runButton.addEventListener("click", runQuery);
editor.addEventListener("keydown", event => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    void runQuery();
  }
});

startEngines().then(result => {
  engines = result;
  runButton.disabled = false;
  engineStatus.dataset.state = "ready";
  engineStatus.textContent = "Engines ready";
}).catch(error => {
  engineStatus.dataset.state = "error";
  engineStatus.textContent = "Startup failed";
  get("result-empty").hidden = true;
  showError(error);
});
