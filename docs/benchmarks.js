"use strict";

const data = globalThis.quackWeaveBenchmarks;
const repo = "https://github.com/kevintruong/quack-weave";
const tracker = `${repo}/tree/main/benchmarks/provider_comparison/tracker`;
const counts = new Intl.NumberFormat("en-US");
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const ms = (ns) => (ns / 1_000_000).toFixed(3);
const get = (id) => document.getElementById(id);
const provider = get("provider");
const metric = get("metric");
const runControl = get("run");
const buttons = [...document.querySelectorAll("[data-suite]")];
const cases = {
  micro_creator_selective: "Selective creator join",
  micro_message_selective: "Selective message join",
  micro_creator_message: "Creator and message join",
  micro_creator_broad: "Over-cap creator join",
  lookup: "Lookup hit",
  lookup_miss: "Lookup miss",
  fanout: "Creator fanout",
  graph_table_where: "Graph-local equality",
  outer_where: "Outer SQL equality",
  view_where: "Equality through a view",
  values_watchlist: "Literal watchlist",
  table_watchlist: "Table watchlist",
  full_scan_aggregate: "Full scalar aggregate",
  cold: "Cold keys",
  mixed: "Mixed keys",
  hot: "Hot keys",
};
const routeNames = {
  direct_cypher: "Direct Cypher",
  qw_cypher: "Quack Weave Cypher",
  qw_gql: "Quack Weave GQL",
  qw_pgq_host: "Host-only join",
  qw_pgq: "Runtime prefilter enabled",
};
const suites = {
  micro: {
    subtitle: "CM-LDBC adaptation · LSQB creator projection",
    cases: ["micro_creator_selective", "micro_message_selective", "micro_creator_message", "micro_creator_broad"],
    routes: ["qw_pgq_host", "qw_pgq"],
    note: "Both routes use the same DuckDB join. The over-cap case falls back to the full graph scan.",
    method: "Warm ADBC submit and full Arrow fetch. Four blocks with five timed repetitions per series. The tracker checked both providers against the CSV oracle and ran SQLLogic before saving the snapshot.",
    links: [["CM-LDBC method and workload SQL", `${tracker}#cm-ldbc-workloads`]],
  },
  sf1: {
    subtitle: "Archived full SF1 creator projection · Protocol 1",
    cases: ["lookup", "lookup_miss", "fanout", "graph_table_where", "outer_where", "view_where",
      "values_watchlist", "table_watchlist", "full_scan_aggregate"],
    routes: ["direct_cypher", "qw_cypher", "qw_gql", "qw_pgq"],
    note: "Direct-client timing is available for the standalone cases. The GRAPH_TABLE cases measure warm hybrid SQL.",
    method: "Historical warm-client baseline. Four blocks with five timed repetitions per series. The tracker checked each fetch against the fixture CSV. This archive used the protocol 1 RelateDB reader.",
    links: [["Full SF1 methodology", `${tracker}#full-sf1-baseline`], ["Archived snapshot", `${tracker}/sf1.json`.replace("/tree/", "/blob/")]],
  },
  fanout: {
    subtitle: "Synthetic creator graph · 16 exact keys per timed case",
    cases: ["cold", "mixed", "hot"],
    routes: ["qw_pgq_host", "qw_pgq"],
    note: "Each run alternates 24 host/prefilter pairs and 24 host/host controls. Select either run to see how timings vary.",
    method: "Native DuckDB execution and result materialization on one macOS ARM64 host. Both routes retained the same hash join and matched every CSV-derived SQL result bag. A separate contiguous-key control kept the host scan on both providers.",
    links: [["Runtime prefilter control", `${repo}/blob/main/test/relate/watchlist_scan_control.test`]],
  },
};

let suiteKey = "micro";
const currentRun = () => data[suiteKey][suiteKey === "fanout" ? Number(runControl.value) : 0];
const routeName = (route) => suiteKey === "sf1" && route === "qw_pgq" ? "GRAPH_TABLE" : routeNames[route];

function node(tag, className, content) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (content != null) el.textContent = content;
  return el;
}

function lookup(run, providerId, workload, route) {
  return run.series.find((s) => s.provider === providerId && s.case === workload && s.route === route);
}

function highlightResults() {
  const micro = data.micro[0];
  const lookupMs = (run, providerId, workload, route) => lookup(run, providerId, workload, route).p50_ns;
  const microHost = lookupMs(micro, "relate", "micro_creator_selective", "qw_pgq_host");
  const microFilter = lookupMs(micro, "relate", "micro_creator_selective", "qw_pgq");
  const hotHost = lookupMs(data.fanout[1], "ladybug", "hot", "qw_pgq_host");
  const hotFilter = lookupMs(data.fanout[1], "ladybug", "hot", "qw_pgq");
  get("creator-speedup").textContent = `${(microHost / microFilter).toFixed(1)}×`;
  get("hot-slowdown").textContent = `${(hotFilter / hotHost).toFixed(1)}×`;
  get("sf1-edges").textContent = compact.format(data.sf1[0].edges);
}

function formatRows([low, high]) {
  return low === high ? counts.format(high) : `${counts.format(low)}–${counts.format(high)}`;
}

function chartScale(values, log) {
  const max = Math.max(...values);
  if (!log) {
    if (max === 0) return { position: () => 0, ticks: [0, 1] };
    const step = 10 ** Math.floor(Math.log10(max / 4));
    const end = Math.ceil(max / (4 * step)) * 4 * step;
    return { position: (v) => v / end, ticks: [0, end / 4, end / 2, 3 * end / 4, end] };
  }
  const low = Math.floor(Math.log10(Math.min(...values)));
  const high = Math.max(low + 1, Math.ceil(Math.log10(max)));
  return {
    position: (v) => (Math.log10(v) - low) / (high - low),
    ticks: Array.from({ length: high - low + 1 }, (_, i) => 10 ** (low + i)),
  };
}

function legend(rows, routes) {
  return routes.filter((route) => rows.some((r) => r.route === route)).map((route) => {
    const item = node("span", "", routeName(route));
    item.dataset.route = route;
    const marker = node("i");
    marker.setAttribute("aria-hidden", "true");
    item.prepend(marker);
    return item;
  });
}

function seriesMark(row, plotValue, scale, log, rowMetric) {
  const label = rowMetric ? formatRows(row.rows) : ms(row[`${metric.value}_ns`]);
  const item = node("div", "chart-series");
  item.dataset.route = row.route;
  item.setAttribute("role", "group");
  item.setAttribute("aria-label", routeName(row.route));
  const track = node("div", log ? "chart-track log" : "chart-track");
  track.setAttribute("aria-hidden", "true");
  track.style.setProperty("--divisions", scale.ticks.length - 1);
  const mark = node("span", "chart-mark");
  mark.style.setProperty("--position", `${100 * scale.position(plotValue(row))}%`);
  track.append(mark);
  item.append(track, node("span", "chart-value", label));
  return item;
}

function renderDetails(rows) {
  const table = rows.map((row) => {
    const tr = node("tr");
    const header = node("th", "", cases[row.case]);
    header.scope = "row";
    tr.append(header);
    for (const value of [routeName(row.route), ms(row.p50_ns), ms(row.p95_ns),
      counts.format(row.n), row.rows ? formatRows(row.rows) : "—"]) {
      tr.append(node("td", "", value));
    }
    return tr;
  });
  get("measurements").replaceChildren(...table);
}

function renderSource(run, suite) {
  get("source-method").textContent = suite.method;
  const entries = [[`Revision ${run.revision.slice(0, 8)}`, `${repo}/commit/${run.revision}`], ...suite.links];
  const links = get("source-links");
  links.replaceChildren();
  for (const [title, href] of entries) {
    if (links.firstChild) links.append(" · ");
    const link = node("a", "", title);
    link.href = href;
    links.append(link);
  }
  const hashes = get("hashes");
  hashes.replaceChildren();
  for (const [label, value] of [
    ["Extension SHA-256", run.extension_sha256], ["DuckDB library SHA-256", run.library_sha256],
    ["Fixture CSV SHA-256", run.csv_sha256], ["Source report SHA-256", run.source_sha256],
  ]) {
    const description = node("dd");
    description.append(node("code", "", value));
    hashes.append(node("dt", "", label), description);
  }
}

function render() {
  const suite = suites[suiteKey];
  const run = currentRun();
  const rowMetric = metric.value === "rows";
  const log = suiteKey === "sf1" && !rowMetric;
  const value = (row) => rowMetric ? row.rows[1] : row[`${metric.value}_ns`] / 1_000_000;
  const rows = suite.cases.flatMap((name) =>
    suite.routes.map((route) => lookup(run, provider.value, name, route)).filter(Boolean));
  const plotted = rowMetric ? rows.filter((row) => row.rows) : rows;

  get("chart-title").textContent = rowMetric ? "Rows delivered to DuckDB" : "Latency by workload";
  get("chart-context").textContent = `${suite.subtitle}${run.date ? ` · ${run.date}` : ""}`;
  get("chart-units").textContent = `${counts.format(run.edges)} graph edges · ${
    rowMetric ? "Graph rows · linear scale" : `${metric.value} elapsed time (ms) · ${log ? "log" : "linear"} scale`}`;
  get("legend").replaceChildren(...legend(plotted, suite.routes));
  get("axis").replaceChildren();
  get("plot").replaceChildren();
  if (plotted.length) renderPlot(plotted, suite, value, log, rowMetric);
  else get("plot").append(node("p", "", "This run has no observations for the selected provider and metric."));
  get("measurement-note").textContent = rowMetric
    ? "Measured at the graph scan. When counts vary, the bar shows the maximum and the label shows the range."
    : suite.note;
  get("run-control").hidden = suiteKey !== "fanout";
  renderDetails(plotted);
  renderSource(run, suite);
}

function renderPlot(plotted, suite, value, log, rowMetric) {
  const scale = chartScale(plotted.map(value), log);
  const ticks = node("div", "axis-labels");
  for (const tick of scale.ticks) {
    const label = node("span", "", tick < 1 ? String(tick) : compact.format(tick));
    label.style.setProperty("--position", `${100 * scale.position(tick)}%`);
    ticks.append(label);
  }
  get("axis").replaceChildren(ticks);
  const groups = suite.cases.flatMap((name) => {
    const workload = plotted.filter((r) => r.case === name);
    if (!workload.length) return [];
    const group = node("div", "chart-group");
    const bars = node("div", "chart-bars");
    bars.append(...workload.map((r) => seriesMark(r, value, scale, log, rowMetric)));
    group.append(node("h4", "", cases[name]), bars);
    return [group];
  });
  get("plot").replaceChildren(...groups);
}

for (const button of buttons) {
  button.addEventListener("click", () => {
    suiteKey = button.dataset.suite;
    metric.value = "p50";
    for (const tab of buttons) tab.setAttribute("aria-pressed", String(tab === button));
    render();
  });
}
for (const select of [provider, metric, runControl]) select.addEventListener("change", render);
get("download").addEventListener("click", () => {
  const url = URL.createObjectURL(new Blob([JSON.stringify(currentRun(), null, 2)], { type: "application/json" }));
  const link = node("a");
  link.href = url;
  link.download = `quack-weave-${suiteKey}${suiteKey === "fanout" ? `-run-${Number(runControl.value) + 1}` : ""}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
});

highlightResults();
render();
