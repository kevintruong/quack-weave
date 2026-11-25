#!/usr/bin/env python3
"""Run the Neo4j SQLLogic cases against a local Query API v2 TLS fixture."""

import argparse
import base64
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
from threading import Thread


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "stabilization"))
from run_sqllogictest import PIN_PROBE_SQL, report_artifact, run_cases


USERNAME = "fixture-user"
PASSWORD = "fixture-password"
AUTHORIZATION = "Basic " + base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
MEDIA_TYPE = "application/vnd.neo4j.query.v1.2"
DATA_PATH = "/db/neo4j/query/v2"


def rows(fields, values):
    return {"data": {"fields": fields, "values": values}}


def scalar(type_name, value):
    return {"$type": type_name, "_value": value}


RESPONSES = {
    "RETURN 9007199254740993 AS id, 'fixture' AS title, 2.5 AS score, true AS ready, null AS missing": rows(
        ["id", "title", "score", "ready", "missing"],
        [[scalar("Integer", "9007199254740993"), scalar("String", "fixture"),
          scalar("Float", "2.5"), scalar("Boolean", True), scalar("Null", None)]],
    ),
    "MATCH (n:Missing) RETURN n.id AS id": rows(["id"], []),
    "RETURN 1 AS rejected": {"errors": [{"code": "Neo.ClientError.Statement.SyntaxError",
                                          "message": "Synthetic failure for SQLLogicTest"}]},
    "RETURN 1 AS wrong_type": rows(["wrong_type"], [[scalar("String", "1")]]),
    "RETURN 'large' AS oversized": rows(["oversized"], [[scalar("String", "x" * 4096)]]),
}


def prepare_certificates(scratch):
    ca, leaf = scratch / "ca.pem", scratch / "server.pem"
    ca_key, leaf_key = scratch / "ca.key", scratch / "server.key"
    request, config = scratch / "server.csr", scratch / "tls.conf"
    config.write_text(
        "[req]\ndistinguished_name=dn\nprompt=no\n[dn]\nCN=QuackWeave SQLLogic fixture\n"
        "[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n"
        "[server]\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n",
        encoding="ascii",
    )
    for command in (
        ["req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "2",
         "-config", config, "-extensions", "ca", "-keyout", ca_key, "-out", ca],
        ["req", "-newkey", "rsa:2048", "-nodes", "-config", config,
         "-keyout", leaf_key, "-out", request],
        ["x509", "-req", "-in", request, "-CA", ca, "-CAkey", ca_key,
         "-CAcreateserial", "-days", "2", "-sha256", "-extfile", config,
         "-extensions", "server", "-out", leaf],
    ):
        subprocess.run(["openssl", *command], check=True, timeout=30, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    return ca, leaf, leaf_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duckdb-unittest", required=True, type=Path)
    parser.add_argument("--extension", required=True, type=Path)
    args = parser.parse_args()
    unittest = args.duckdb_unittest.resolve(strict=True)
    extension = args.extension.resolve(strict=True)
    seen = Counter()
    unexpected = []

    class QueryAPI(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reject(self, reason):
            unexpected.append(reason)
            self.send_error(400)

        def do_GET(self):
            self.reject("expected POST")

        def do_POST(self):
            if self.path != DATA_PATH or self.headers.get("Authorization") != AUTHORIZATION:
                self.reject("wrong path or test authorization")
                return
            if self.headers.get("Accept") != MEDIA_TYPE:
                self.reject("missing Typed JSON Accept header")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("unsupported request shape")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request.get("parameters", {}), dict):
                    raise ValueError("invalid parameters")
                statement = request["statement"]
                response = RESPONSES[statement]
            except (AttributeError, KeyError, TypeError, ValueError):
                self.reject("unexpected query request")
                return
            seen[statement] += 1
            payload = json.dumps(response, separators=(",", ":")).encode()
            self.send_response(202)
            self.send_header("Content-Type", MEDIA_TYPE)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    with tempfile.TemporaryDirectory(prefix="qw-neo4j-") as folder:
        scratch = Path(folder).resolve()
        run_cases(unittest, scratch, {}, stdin=PIN_PROBE_SQL)
        ca, leaf, leaf_key = prepare_certificates(scratch)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(leaf, leaf_key)
        with ThreadingHTTPServer(("127.0.0.1", 0), QueryAPI) as server:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
            endpoint = f"https://127.0.0.1:{server.server_port}"
            server_thread = Thread(target=server.serve_forever)
            server_thread.start()
            try:
                report_artifact(extension)
                run_cases(unittest, scratch, {
                    "QW_EXT": extension,
                    "QW_NEO4J_FIXTURE_ENDPOINT": endpoint,
                    "QW_NEO4J_FIXTURE_CA": ca,
                    "QW_NEO4J_FIXTURE_USERNAME": USERNAME,
                    "QW_NEO4J_FIXTURE_PASSWORD": PASSWORD,
                }, sorted((HERE / "sqllogic").glob("*.test")))
            finally:
                server.shutdown()
                server_thread.join()

        if unexpected or seen != Counter(dict.fromkeys(RESPONSES, 1)):
            raise AssertionError(
                f"Unexpected fixture traffic: {unexpected}; expected {len(RESPONSES)} requests, "
                f"saw {sum(seen.values())}"
            )


if __name__ == "__main__":
    main()
