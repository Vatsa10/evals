"""A local HTTP/SQLite tool service with real transactional writes and fault injection."""

from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from evals import span


class ToolError(RuntimeError):
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
        super().__init__(f"HTTP {status}: {payload.get('error', 'tool failed')}")


class Backend:
    def __init__(self, path, fault=None):
        self.path, self.fault = Path(path), fault
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("""
                CREATE TABLE orders(id TEXT PRIMARY KEY, customer TEXT, total INTEGER);
                INSERT INTO orders VALUES ('O-100', 'customer-a', 10000), ('O-200', 'customer-b', 10000);
                CREATE TABLE refunds(key TEXT PRIMARY KEY, order_id TEXT, customer TEXT, amount INTEGER);
                CREATE TABLE faults(name TEXT PRIMARY KEY);
            """)

    def refund(self, customer, body):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            order = db.execute("SELECT customer,total FROM orders WHERE id=?", (body.get("order_id"),)).fetchone()
            if not order or order[0] != customer:
                return 403, {"error": "order_access_denied"}
            if self.fault == "outage":
                return 503, {"error": "dependency_unavailable"}
            amount, key = body.get("amount_cents"), body.get("key")
            if type(amount) is not int or amount <= 0 or not isinstance(key, str) or not key:
                return 400, {"error": "invalid_request"}
            existing = db.execute("SELECT order_id,customer,amount FROM refunds WHERE key=?", (key,)).fetchone()
            if existing:
                if existing != (body["order_id"], customer, amount):
                    return 409, {"error": "idempotency_conflict"}
                return 200, {"status": "refunded", "replayed": True}
            total = db.execute("SELECT COALESCE(SUM(amount),0) FROM refunds WHERE order_id=?", (body["order_id"],)).fetchone()[0]
            if total + amount > order[1]:
                return 409, {"error": "exceeds_order_total"}
            db.execute("INSERT INTO refunds VALUES (?,?,?,?)", (key, body["order_id"], customer, amount))
            if self.fault == "commit_then_503" and not db.execute("SELECT 1 FROM faults").fetchone():
                db.execute("INSERT INTO faults VALUES ('committed')")
                return 503, {"error": "response_lost_after_commit"}
            return 200, {"status": "refunded", "replayed": False}

    def ledger(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            return [{"key": r[0], "order_id": r[1], "customer": r[2], "amount_cents": r[3]}
                    for r in db.execute("SELECT key,order_id,customer,amount FROM refunds ORDER BY rowid")]


@contextmanager
def tool_service(path, fault=None):
    backend = Backend(path, fault)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != "/refunds":
                self.send_error(404)
                return
            size = int(self.headers.get("Content-Length", "0"))
            if size > 16384:
                self.send_error(413)
                return
            try:
                body = json.loads(self.rfile.read(size))
                # Synthetic credentials only; identity is supplied by the app, never the model.
                customer = {"Bearer fixture-a": "customer-a", "Bearer fixture-b": "customer-b"}.get(self.headers.get("Authorization"))
                status, result = backend.refund(customer, body) if customer else (401, {"error": "unauthorized"})
            except (ValueError, TypeError, AttributeError):
                status, result = 400, {"error": "invalid_json"}
            data = json.dumps(result).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}", backend
        finally:
            server.shutdown()
            thread.join(3)


def refund_request(url, customer, body):
    # Credentials never enter a recorded span.
    with span("refund.http", kind="tool", input=body) as current:
        token = {"customer-a": "fixture-a", "customer-b": "fixture-b"}.get(customer, "invalid")
        request = Request(url + "/refunds", data=json.dumps(body).encode(),
                          headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
        try:
            with urlopen(request, timeout=5) as response:
                value = json.load(response)
        except HTTPError as exc:
            value = json.loads(exc.read())
            current.set_output({"http_status": exc.code, **value})
            raise ToolError(exc.code, value) from exc
        current.set_output({"http_status": 200, **value})
        return value
