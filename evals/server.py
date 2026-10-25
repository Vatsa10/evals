"""A loopback JSON API for local trace ingestion and monitoring."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlsplit

from evals.adapters import reject_constant
from evals.monitoring import record_trace
from evals.storage import Store


def make_server(host="127.0.0.1", port=8765, *, store=None, policy=None, root=None):
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("The local monitoring server binds to 127.0.0.1 or localhost")
    store = store or Store()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def respond(self, status, value):
            data = json.dumps(value, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlsplit(self.path)
            parts = url.path.strip("/").split("/")
            try:
                if url.path == "/health":
                    return self.respond(200, {"status": "ok", "counts": store.counts()})
                if len(parts) not in {2, 3} or parts[0] != "api" or parts[1] not in {"runs", "traces", "alerts"}:
                    return self.respond(404, {"error": "Not found"})
                if len(parts) == 3:
                    record = store.get(parts[1], parts[2])
                    return self.respond(200 if record else 404, record or {"error": "Not found"})
                query = parse_qs(url.query)
                records = store.list(parts[1], int(query.get("limit", ["50"])[0]),
                                     query.get("thread_id", [None])[0])
                return self.respond(200, {"items": records})
            except (ValueError, TypeError) as exc:
                return self.respond(400, {"error": str(exc)})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/traces":
                return self.respond(404, {"error": "Not found"})
            # Browser origins are unnecessary for SDK/CLI ingestion; reject them.
            if self.headers.get("Origin"):
                return self.respond(403, {"error": "Browser-origin trace ingestion is disabled"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2_000_000:
                    return self.respond(413, {"error": "Trace body must be 1..2000000 bytes"})
                self.connection.settimeout(10)
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError("Incomplete request body")
                record = json.loads(body, parse_constant=reject_constant)
                return self.respond(201, record_trace(record, store, policy, root))
            except (ValueError, TypeError, KeyError, OSError) as exc:
                return self.respond(400, {"error": str(exc)})

    return ThreadingHTTPServer((host, port), Handler)
