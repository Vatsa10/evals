"""Local SQLite persistence for evaluation runs, traces, and alerts."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import uuid


KINDS = {"runs", "traces", "alerts"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get("EVALS_STORE", ".evals/evals.db")).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS records (
                kind TEXT NOT NULL, id TEXT NOT NULL, created_at TEXT NOT NULL,
                thread_id TEXT, status TEXT, name TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(kind, id))""")
            db.execute("CREATE INDEX IF NOT EXISTS records_time ON records(kind, created_at DESC)")
            db.execute("CREATE INDEX IF NOT EXISTS records_thread ON records(kind, thread_id, created_at)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, kind, payload):
        if kind not in KINDS or not isinstance(payload, dict):
            raise ValueError("Invalid record kind or payload")
        record = dict(payload)
        record.setdefault("id", uuid.uuid4().hex)
        record.setdefault("created_at", utc_now())
        if not isinstance(record["id"], str) or not record["id"]:
            raise ValueError("Record id must be a nonempty string")
        serialized = json.dumps(record, allow_nan=False)
        with self.connect() as db:
            try:
                db.execute("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (kind, record["id"], record["created_at"], record.get("thread_id"),
                            record.get("status"), record.get("name", record.get("suite")), serialized))
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Duplicate {kind} record: {record['id']}") from exc
        return record

    def get(self, kind, record_id):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, kind, limit=50, thread_id=None):
        if kind not in KINDS or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Unknown record kind or invalid limit (1..1000)")
        query = "SELECT payload FROM records WHERE kind=?"
        parameters = [kind]
        if thread_id is not None:
            query += " AND thread_id=?"
            parameters.append(thread_id)
        query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
        parameters.append(limit)
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute(query, parameters).fetchall()]

    def counts(self):
        with self.connect() as db:
            found = dict(db.execute("SELECT kind, COUNT(*) FROM records GROUP BY kind").fetchall())
        return {kind: found.get(kind, 0) for kind in sorted(KINDS)}
