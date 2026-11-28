"""Exercise the packaged Xet filesystem against deterministic HTTPS responses."""

from contextlib import contextmanager
import csv
import json
import os
from pathlib import Path
import re
import shlex
import ssl
import subprocess
from threading import Thread
from urllib.parse import urlsplit

from fixture import ReadOnlyRequest, Store


REVISION = "0123456789abcdef0123456789abcdef01234567"
CASES = {
    "snapshot": "",
    "missing": "invalid path",
    "denied_wal": "HTTP 403",
    "dirty_wal": "non-empty wal",
    "http_redirect": "Unsafe Xet redirect",
    "redirect_loop": "Too many Xet redirects",
    "full_body": "Unexpected HTTP 200 from range GET",
    "wrong_range": "Unexpected HTTP Content-Range",
    "short_body": "Incomplete HTTP range response",
    "untrusted_tls": "SSL server verification failed",
}


class XetRequest(ReadOnlyRequest):
    def serve_object(self):
        target = urlsplit(self.path)
        file = target.path.rsplit("/", 1)[-1]
        case = file.removesuffix(".wal").removesuffix(".lbdb")
        if case not in CASES or any(key in self.headers for key in ("Authorization", "Proxy-Authorization", "Cookie")):
            self.reject(400, "unexpected Xet path or credentials")
            return
        blob = target.path.startswith("/blob/")
        resolve = f"/datasets/team/graphs/resolve/{REVISION}/{file}"
        if target.path != (f"/blob/{file}" if blob else resolve) or target.query != ("fixture=1" if blob else ""):
            self.reject(400, "unexpected Xet resolve path")
            return

        data = self.server.graph
        if self.command == "HEAD":
            if case == "missing":
                self.respond(404)
            elif file.endswith(".wal"):
                if case == "denied_wal" and not blob:
                    self.redirect(f"https://127.0.0.1:{self.server.server_port}/blob/{file}?fixture=1", linked_size=0)
                else:
                    code, length = {"denied_wal": (403, 0), "dirty_wal": (200, 8)}.get(case, (404, 0))
                    self.respond(code, length=length)
            elif blob:
                self.respond(200, length=len(data))
            else:
                self.redirect(f"https://127.0.0.1:{self.server.server_port}/blob/{file}?fixture=1", linked_size=len(data))
            return

        if not blob:
            if case == "http_redirect":
                self.redirect(f"http://127.0.0.1:{self.server.server_port}/blob/{file}?fixture=1")
            elif case == "redirect_loop":
                self.redirect(resolve)
            else:
                self.redirect(f"https://127.0.0.1:{self.server.server_port}/blob/{file}?fixture=1")
            return
        requested = re.fullmatch(r"bytes=(\d+)-(\d+)", self.headers.get("Range", ""))
        if requested is None:
            self.reject(400, "range required")
            return
        start, end = map(int, requested.groups())
        if not 0 <= start <= end < len(data):
            self.reject(416, "range outside the fixture")
            return
        body = data[start:end + 1]
        if case == "short_body":
            self.server.requests[self.command, target.path, 206] += 1
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            # Cleanly end a response before it supplies the requested range.
            self.wfile.write(b"0\r\n\r\n")
            return
        content_range = f"bytes {start}-{end}/{len(data)}"
        if case == "wrong_range":
            content_range = f"bytes 0-0/{len(data)}"
        self.respond(200 if case == "full_body" else 206, length=len(body), content_range=content_range)
        self.wfile.write(body)

    def redirect(self, location, *, linked_size=None):
        self.server.requests[self.command, urlsplit(self.path).path, 302] += 1
        self.send_response(302)
        self.send_header("Location", location)
        if linked_size is not None:
            self.send_header("x-linked-size", str(linked_size))
        self.send_header("Content-Length", "0")
        self.end_headers()


@contextmanager
def tls_store(scratch, graph):
    cert, key = scratch / "fixture-cert.pem", scratch / "fixture-key.pem"
    config = scratch / "fixture-tls.cnf"
    config.write_text(
        "[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=ext\n"
        "[dn]\nCN=localhost\n[ext]\nsubjectAltName=DNS:localhost,IP:127.0.0.1\n",
        encoding="ascii",
    )
    subprocess.run(
        ["openssl", "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-config", config, "-keyout", key, "-out", cert],
        check=True, capture_output=True,
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    with Store({}) as server:
        server.RequestHandlerClass = XetRequest
        server.graph = graph
        server.socket = context.wrap_socket(server.socket, server_side=True)
        worker = Thread(target=server.serve_forever)
        worker.start()
        try:
            yield server, cert
        finally:
            server.shutdown()
            worker.join()


def relink_fixture_shell(lbug, scratch, port):
    # Compile the same implementation with only its initial origin changed.
    build = lbug.parents[2]
    commands = json.loads((build / "compile_commands.json").read_text())
    command = next(entry for entry in commands if entry["file"].endswith("/xetfs.cpp"))
    original = Path(command["file"]).read_text()
    origin = '"https://huggingface.co/"'
    if original.count(origin) != 1:
        raise ValueError("Packaged Xet filesystem origin changed")
    source = scratch / "xetfs.cpp"
    source.write_text(original.replace(origin, f'"https://localhost:{port}/"'))
    obj = scratch / "xetfs.cpp.o"
    compile_args = shlex.split(command["command"])
    compile_args[compile_args.index("-o") + 1] = str(obj)
    compile_args[compile_args.index("-c") + 1] = str(source)
    subprocess.run(compile_args, cwd=command["directory"], check=True)
    shell = scratch / "lbug-xet-fixture"
    link_args, directory = fixture_link_command(lbug, build)
    output = link_args.index("-o")
    link_args[output + 1] = str(shell)
    link_args.insert(output, str(obj))
    subprocess.run(link_args, cwd=directory, check=True)
    return shell


def fixture_link_command(lbug, build):
    link_file = lbug.parent / "CMakeFiles/lbug_shell.dir/link.txt"
    if link_file.is_file():
        return shlex.split(link_file.read_text()), lbug.parent
    cache = (build / "CMakeCache.txt").read_text().splitlines()
    ninja = next((line.partition("=")[2] for line in cache if line.startswith("CMAKE_MAKE_PROGRAM:FILEPATH=")), None)
    if "CMAKE_GENERATOR:INTERNAL=Ninja" not in cache or not ninja:
        raise ValueError("The Xet engine fixture needs a Makefiles or Ninja Ladybug build")
    commands = subprocess.check_output(
        [ninja, "-t", "commands", lbug.relative_to(build)], cwd=build, text=True,
    )
    link = shlex.split(commands.splitlines()[-1])
    if link[:2] == [":", "&&"] and link[-2:] == ["&&", ":"]:
        link = link[2:-2]
    if any(part in {"&&", ";", "|"} for part in link):
        raise ValueError("Unexpected shell operators in the Ladybug Ninja link command")
    return link, build


def check_xet(lbug, unittest, scratch, graph, query, run_cases):
    receipts = scratch / "xet.csv"
    with tls_store(scratch, graph) as (server, cert), receipts.open("w", newline="", encoding="utf-8") as report:
        cli = relink_fixture_shell(lbug, scratch, server.server_port)
        environment = {k: v for k, v in os.environ.items() if not k.startswith(("HTTP_", "HF_"))}
        environment.update(SSL_CERT_FILE=str(cert), HF_TOKEN="loopback-token-that-must-not-be-sent")
        writer = csv.writer(report)
        writer.writerow(("scenario", "result", "wal_status", "blob_read", "only_read_requests"))
        for case, error in CASES.items():
            server.requests.clear()
            server.unexpected.clear()
            uri = f"xet://datasets/team/graphs/{REVISION}/{case}.lbdb"
            sql = f"CALL HTTP_CACHE_FILE=false;\nATTACH '{uri}' AS snapshot (DBTYPE lbug);\n{query}"
            result = subprocess.run(
                [cli, "-m", "jsonlines", "-s", "-b", "-p", scratch, ":memory:"], input=sql,
                text=True, capture_output=True,
                env=({**environment, "SSL_CERT_FILE": str(scratch / "untrusted.pem")}
                     if case == "untrusted_tls" else environment),
                timeout=15,
            )
            rows = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            edges = [(row["src"], row["dst"]) for row in rows if "src" in row and "dst" in row]
            detail = result.stderr + result.stdout
            expected = "10:20" if not error else "rejected"
            passed = (edges == [(10, 20)] and not result.stderr and not result.returncode
                      if not error else not edges and error in detail)
            wal_status = next(
                (status for method, path, status in server.requests
                 if method == "HEAD" and path.endswith(".wal") and status in (200, 403, 404)),
                0,
            )
            blob_read = any(method == "GET" and path.startswith("/blob/") for method, path, _ in server.requests)
            writer.writerow((case, expected if passed else "failed", wal_status, blob_read, not server.unexpected))
            if not passed or server.unexpected:
                print(f"Xet {case}: {detail.rstrip()} HTTP {server.requests}, unexpected {server.unexpected}", flush=True)
    run_cases(unittest, scratch, {"QW_XET_ENGINE_OBSERVATIONS": receipts}, [Path(__file__).with_name("engine_xet.test")])
