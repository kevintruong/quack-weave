import * as duckdb from "@duckdb/duckdb-wasm";
import mvpWasm from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";
import ehWasm from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import mvpWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import ehWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import ladybug from "@ladybugdb/wasm-core";
import { Bool, Float64, Int64, Utf8, makeTable, tableToIPC, vectorFromArray } from "apache-arrow";
import graphSeed from "./data/papertrail.cypher?raw";
import papersFile from "./data/papers.parquet?url";
import { lowerGraphTables } from "./graph-table.js";

const base = new URL(import.meta.env.BASE_URL, window.location.href);
const parquetPath = "papertrail-papers.parquet";
const graphPath = "/papertrail.lbdb";

async function fetchAsset(path) {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Unable to load ${new URL(path, base).pathname} (HTTP ${response.status})`);
  return response.arrayBuffer();
}

async function startDuckDB() {
  const bundle = await duckdb.selectBundle({
    mvp: { mainModule: mvpWasm, mainWorker: mvpWorker },
    eh: { mainModule: ehWasm, mainWorker: ehWorker },
  });
  const worker = new Worker(bundle.mainWorker);
  const database = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  try {
    await database.instantiate(bundle.mainModule);
    const connection = await database.connect();
    const repository = new URL("duckdb-extensions", base);
    await connection.query(`SET custom_extension_repository = '${repository.href.replaceAll("'", "''")}';
      LOAD json;
      LOAD parquet;`);
    await database.registerFileBuffer(parquetPath, new Uint8Array(await fetchAsset(papersFile)));
    await connection.query(`CREATE TABLE papers AS SELECT * FROM read_parquet('${parquetPath}');
      SET enable_external_access = false;`);
    await database.dropFile(parquetPath);
    return { database, connection };
  } catch (error) {
    worker.terminate();
    throw error;
  }
}

async function startLadybug() {
  const workerPath = new URL("./node_modules/@ladybugdb/wasm-core/lbug_wasm_worker.js", import.meta.url);
  ladybug.setWorkerPath(workerPath.href);
  await ladybug.init();
  // The single-threaded package can open its local files but does not expose
  // a working FS.writeFile. Create the graph in its own filesystem first.
  const seedDatabase = new ladybug.Database(graphPath, 0, 1);
  const seedConnection = new ladybug.Connection(seedDatabase, 1);
  try {
    const result = await seedConnection.query(graphSeed);
    try {
      for (const statement of result) {
        if (!statement.isSuccess()) throw new Error(await statement.getErrorMessage());
      }
    } finally {
      await result.close();
    }
  } finally {
    await seedConnection.close();
    await seedDatabase.close();
  }
  const database = new ladybug.Database(graphPath, 0, 1, true, true);
  const connection = new ladybug.Connection(database, 1);
  await connection.init();
  return connection;
}

async function startSchemaParser() {
  const { instance } = await WebAssembly.instantiate(await fetchAsset(new URL("bridge.wasm", base)));
  const bridge = instance.exports;
  const encoder = new TextEncoder();
  const decoder = new TextDecoder();
  return text => {
    const data = encoder.encode(text);
    const input = bridge.schema_input(data.length);
    new Uint8Array(bridge.memory.buffer, input, data.length).set(data);
    const output = bridge.schema_parse();
    const result = decoder.decode(new Uint8Array(bridge.memory.buffer, output, bridge.schema_output_length()));
    const [status, ...lines] = result.trimEnd().split("\n");
    if (status !== "ok") throw new Error(lines.join("\n"));
    return lines.map(line => {
      const [name, type] = line.split("\t");
      return { name, type };
    });
  };
}

async function queryGraph(graph, cypher) {
  const result = await graph.query(cypher);
  try {
    if (!result.isSuccess()) throw new Error(await result.getErrorMessage());
    if (result.hasNextQueryResult()) throw new Error("Run one Cypher statement at a time.");
    const [columns, types, rows] = await Promise.all([
      result.getColumnNames(), result.getColumnTypes(), result.getAllRows(),
    ]);
    return { columns, types, rows };
  } finally {
    await result.close();
  }
}

const scalarTypes = {
  BOOLEAN: { graph: "BOOL", arrow: new Bool(), convert: value => value },
  BIGINT: { graph: "INT64", arrow: new Int64(), convert: value => BigInt(value) },
  DOUBLE: { graph: "DOUBLE", arrow: new Float64(), convert: value => value },
  VARCHAR: { graph: "STRING", arrow: new Utf8(), convert: value => value },
};

// DuckDB parses the SQL so literals, aliases, comments, and CTEs retain their SQL meanings.
function graphScans(tree, graphTables) {
  const scans = [];
  const pending = [tree];
  while (pending.length) {
    const node = pending.pop();
    if (node === null || typeof node !== "object") continue;
    const name = node.function?.function_name?.toLowerCase();
    if (node.type === "TABLE_FUNCTION" && (name === "qw_query" || graphTables.has(name))) {
      scans.push({ scan: node, cypher: graphTables.get(name) });
    } else {
      pending.push(...Object.values(node));
    }
  }
  return scans;
}

function graphArguments(scan, parseSchema) {
  const { children, catalog, schema } = scan.function;
  if (catalog || schema || scan.with_ordinality === "WITH_ORDINALITY" || children?.length !== 4) {
    throw new Error("QW_ARGUMENT: Use qw_query('kg', 'cypher', '<query>', schema := '<columns>').");
  }
  const values = children.map((child, index) => {
    const named = index === 3 ? child.alias?.toLowerCase() === "schema" : !child.alias;
    if (!named || child.class !== "CONSTANT" || typeof child.value?.value !== "string") {
      throw new Error("QW_ARGUMENT: qw_query needs string literals and an explicit schema.");
    }
    return child.value.value;
  });
  const [alias, dialect, cypher, schemaText] = values;
  if (alias !== "kg" || dialect !== "cypher") {
    throw new Error("QW_ARGUMENT: This playground accepts alias 'kg' and dialect 'cypher'.");
  }
  return { cypher, columns: parseSchema(schemaText) };
}

function inferSchema(result, parseSchema) {
  const schema = result.columns.map((name, index) => {
    const type = Object.keys(scalarTypes).find(key => scalarTypes[key].graph === result.types[index]);
    if (!type) throw new Error(`QW_SCHEMA: Unsupported GRAPH_TABLE column type ${result.types[index]}.`);
    return `${name} ${type}`;
  });
  return parseSchema(schema.join(", "));
}

function toArrow(columns, result) {
  if (columns.length !== result.columns.length || columns.some(({ name, type }, index) =>
    name !== result.columns[index] || scalarTypes[type].graph !== result.types[index]
  )) {
    throw new Error("QW_SCHEMA: The returned columns must match the schema's names, order, and types.");
  }
  const vectors = Object.fromEntries(columns.map(({ name, type }, index) => {
    const { arrow, convert } = scalarTypes[type];
    const values = result.rows.map(row => row[index] === null ? null : convert(row[index]));
    return [name, vectorFromArray(values, arrow)];
  }));
  return tableToIPC(makeTable(vectors), "stream");
}

async function executeSql({ database, connection }, graph, parseSchema, sql) {
  const temporaryTables = [];
  let arrowBytes = 0;
  let arrowRows = 0;
  try {
    const { statement, graphTables } = /\bgraph_table\b/i.test(sql)
      ? lowerGraphTables(sql, await database.tokenize(sql))
      : { statement: sql, graphTables: new Map() };
    if (graphTables.size || /\bqw_query\b/i.test(sql)) {
      const serialize = await connection.prepare("SELECT json_serialize_sql(?::VARCHAR) AS ast");
      let tree;
      try {
        tree = JSON.parse((await serialize.query(statement)).get(0).ast);
      } finally {
        await serialize.close();
      }
      if (tree.error && graphTables.size) throw new Error(tree.error_message);
      const scans = tree.error ? [] : graphScans(tree, graphTables);
      if (scans.length) {
        if (tree.statements.length !== 1) throw new Error("Run one SQL statement at a time with graph scans.");
        const queries = scans.map(({ scan, cypher }) => {
          if (!cypher) return { scan, ...graphArguments(scan, parseSchema), defaultAlias: "qw_query" };
          if (scan.with_ordinality === "WITH_ORDINALITY") {
            throw new Error("GRAPH_TABLE accepts a table alias after COLUMNS.");
          }
          return { scan, cypher, defaultAlias: "graph_table" };
        });
        for (const { scan, cypher, columns: schema, defaultAlias } of queries) {
          const result = await queryGraph(graph, cypher);
          const columns = schema ?? inferSchema(result, parseSchema);
          const bytes = toArrow(columns, result);
          const name = `qw_rows_${crypto.randomUUID().replaceAll("-", "")}`;
          const fields = columns.map(column => `"${column.name}" ${column.type}`).join(", ");
          await connection.query(`CREATE TEMP TABLE ${name} (${fields})`);
          temporaryTables.push(name);
          if (result.rows.length) {
            arrowBytes += bytes.byteLength;
            arrowRows += result.rows.length;
            await connection.insertArrowFromIPCStream(bytes, { name, create: false });
          }
          const { alias, column_name_alias, query_location } = scan;
          delete scan.function;
          delete scan.with_ordinality;
          Object.assign(scan, {
            type: "BASE_TABLE",
            alias: alias || defaultAlias,
            column_name_alias,
            query_location,
            catalog_name: "temp",
            schema_name: "main",
            table_name: name,
          });
        }
        const deserialize = await connection.prepare("SELECT json_deserialize_sql(?::JSON) AS sql");
        try {
          sql = (await deserialize.query(JSON.stringify(tree))).get(0).sql;
        } finally {
          await deserialize.close();
        }
      }
    }
    const result = await connection.query(sql);
    return {
      columns: result.schema.fields.map(field => field.name),
      rows: Array.from(result, row => Array.from(row, ([, value]) => value)),
      engine: temporaryTables.length ? "Ladybug → DuckDB" : "DuckDB",
      arrowBytes,
      arrowRows,
    };
  } finally {
    for (const name of temporaryTables) await connection.query(`DROP TABLE IF EXISTS temp.main.${name}`);
  }
}

export async function startEngines() {
  const [sql, graph, parseSchema] = await Promise.all([startDuckDB(), startLadybug(), startSchemaParser()]);
  return {
    async run(mode, query) {
      if (mode === "cypher") return { ...await queryGraph(graph, query), engine: "Ladybug" };
      return executeSql(sql, graph, parseSchema, query);
    },
  };
}
