"""A read-only, range-capable loopback object store for native Ladybug tests."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import re
from threading import Event, Thread
from time import monotonic
from typing import Literal
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Object:
    data: bytes
    key_id: str
    secret: str
    token: str | None = None
    wal: bytes | Literal[403, 404] = 404
    hold_wal_head: Event | None = None


def signed_request_matches(method, path, headers, obj):
    authorization = headers.get("Authorization", "")
    if headers.get("x-amz-security-token") != obj.token:
        return False

    match = re.fullmatch(
        r"AWS4-HMAC-SHA256 Credential=([^/]+)/(\d{8}/[^/]+/s3/aws4_request), "
        r"SignedHeaders=([a-z;0-9-]+), Signature=([0-9a-f]{64})",
        authorization,
    )
    if match is None or match[1] != obj.key_id:
        return False
    scope, signed_headers, signature = match[2], match[3], match[4]
    required = ["host", "x-amz-content-sha256", "x-amz-date"]
    if obj.token is not None:
        required.append("x-amz-security-token")
    if signed_headers != ";".join(required) or any(name not in headers for name in required):
        return False
    date = headers["x-amz-date"]
    if not re.fullmatch(r"\d{8}T\d{6}Z", date) or scope[:8] != date[:8]:
        return False

    canonical_headers = "\n".join(f"{name}:{headers[name]}" for name in required)
    canonical = "\n".join(
        (method, path, "", canonical_headers, "", signed_headers, headers["x-amz-content-sha256"])
    )
    to_sign = "\n".join(("AWS4-HMAC-SHA256", date, scope, sha256(canonical.encode()).hexdigest()))
    key = ("AWS4" + obj.secret).encode()
    for component in scope.split("/"):
        key = hmac.digest(key, component.encode(), "sha256")
    expected = hmac.digest(key, to_sign.encode(), "sha256").hex()
    return hmac.compare_digest(expected, signature)


class Store(ThreadingHTTPServer):
    def __init__(self, objects):
        self.objects = objects
        self.requests = Counter()
        self.range_lengths = Counter()
        self.held_wal_heads = {}
        self.unexpected = []
        super().__init__(("127.0.0.1", 0), ReadOnlyRequest)
        self.endpoint = f"127.0.0.1:{self.server_port}"


class ReadOnlyRequest(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def parse_request(self):
        if not super().parse_request():
            return False
        if self.command in {"HEAD", "GET"}:
            return True
        self.reject(405, "mutating or unsupported method")
        return False

    def reject(self, status, reason):
        self.server.unexpected.append((self.command, urlsplit(self.path).path, reason))
        self.respond(status)

    def respond(self, status, *, length=0, content_range=None):
        self.server.requests[self.command, urlsplit(self.path).path, status] += 1
        self.send_response(status)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if content_range is not None:
            self.send_header("Content-Range", content_range)
        self.end_headers()

    def do_HEAD(self):
        self.serve_object()

    def do_GET(self):
        self.serve_object()

    def serve_object(self):
        target = urlsplit(self.path)
        if target.query:
            self.reject(400, "unexpected query string")
            return

        path = target.path
        obj = self.server.objects.get(path)
        sidecar = path.endswith(".wal")
        if obj is None and sidecar:
            obj = self.server.objects.get(path.removesuffix(".wal"))
        if obj is None:
            self.reject(404, "unknown object")
            return

        if not signed_request_matches(self.command, path, self.headers, obj):
            self.reject(403, "unexpected fixture credentials")
            return
        if sidecar and self.command == "HEAD" and obj.hold_wal_head is not None:
            self.server.held_wal_heads.setdefault(path, monotonic())
            if obj.hold_wal_head.wait(timeout=2):
                return
        data = obj.wal if sidecar else obj.data
        if isinstance(data, int):
            if self.command != "HEAD":
                self.reject(data, "attempt to read inaccessible sidecar")
                return
            self.respond(data)
            return

        size = len(data)
        if self.command == "HEAD":
            self.respond(200, length=size)
            return

        requested = re.fullmatch(r"bytes=(\d+)-(\d*)", self.headers.get("Range", ""))
        if requested is None:
            self.reject(400, "object GET must carry one byte range")
            return
        start = int(requested[1])
        end = min(int(requested[2]), size - 1) if requested[2] else size - 1
        if start > end:
            self.reject(416, "range outside the fixture")
            return

        length = end - start + 1
        self.server.range_lengths[path, length] += 1
        self.respond(206, length=length, content_range=f"bytes {start}-{end}/{size}")
        self.wfile.write(data[start : end + 1])


@contextmanager
def read_only_store(objects):
    with Store(objects) as server:
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join()
