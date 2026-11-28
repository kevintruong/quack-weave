const hub = "https://huggingface.co";
const commit = /^[0-9a-f]{40}$/i;
const repositoryPart = /^[\w.-]+$/;
const encode = value => encodeURIComponent(value).replaceAll("'", "%27");

function datasetLocation(input) {
  const value = input.trim();
  const invalid = () => new Error("Enter a Hugging Face dataset ID, dataset or file URL, or a pinned xet:// file URI.");
  let parts;
  let kind;
  let revision = "main";
  if (value.includes("://")) {
    const url = new URL(value);
    const xet = url.protocol === "xet:" && url.host === "datasets";
    if ((!xet && url.origin !== hub) || url.username || url.password) throw invalid();
    parts = url.pathname.replace(/^\/|\/$/g, "").split("/").map(decodeURIComponent);
    if (!xet && parts.shift() !== "datasets") throw invalid();
    if (xet) parts.splice(2, 0, "xet");
  } else {
    parts = value.split("/");
    if (parts.length !== 2) throw invalid();
  }
  const [owner, repo, route, ref, ...tail] = parts;
  if (![owner, repo].every(part => part && repositoryPart.test(part) && ![".", ".."].includes(part))) throw invalid();
  if (route !== undefined) {
    if (!["tree", "blob", "resolve", "xet"].includes(route) || !ref) throw invalid();
    if (route === "xet" && !commit.test(ref)) throw invalid();
    kind = route === "tree" ? "folder" : "file";
    revision = ref;
  }
  const path = tail.join("/");
  if (kind === "file" && !path.endsWith(".lbdb")) throw new Error("Choose a checkpointed .lbdb database file.");
  return { repo: `${owner}/${repo}`, revision, kind, path };
}

export async function discoverGraphs(input) {
  const { repo, revision, kind, path } = datasetLocation(input);
  const response = await fetch(`${hub}/api/datasets/${repo}/revision/${encode(revision)}?blobs=true`, { credentials: "omit" });
  if (!response.ok) throw new Error(`Cannot read public dataset ${repo} (HTTP ${response.status}).`);
  const { sha, siblings } = await response.json();
  if (!commit.test(sha) || !Array.isArray(siblings) || (commit.test(revision) && sha.toLowerCase() !== revision.toLowerCase())) {
    throw new Error("The Hub did not return a matching dataset revision and file list.");
  }
  const files = siblings.map(({ rfilename }) => rfilename).filter(name => name.endsWith(".lbdb") &&
    (kind === "file" ? name === path : !path || name.startsWith(path + "/")));
  if (!files.length) throw new Error(`No .lbdb file found at this location in ${repo}.`);
  return {
    repo, sha, files,
    url(file) {
      if (!files.includes(file)) throw new Error("Choose a database file from the listed revision.");
      const wal = siblings.find(entry => entry.rfilename === file + ".wal");
      if (wal && wal.size !== 0) throw new Error("This graph has a pending WAL. Choose a checkpointed .lbdb file.");
      return `${hub}/datasets/${repo}/resolve/${sha}/${file.split("/").map(encode).join("/")}`;
    },
  };
}
