import hashlib
import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


def uid(prefix):
    return f"{prefix}_{secrets.token_hex(12)}"


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.path = self.root / "state.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
        with self.tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, expires REAL NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, state TEXT NOT NULL,
                    created REAL NOT NULL, data TEXT NOT NULL);
            """)
        secret = self.root / "signing.key"
        if not secret.exists():
            secret.write_text(secrets.token_hex(32))
            secret.chmod(0o600)
        self.signing_key = secret.read_text().encode()

    @contextmanager
    def tx(self):
        with self.lock:
            db = sqlite3.connect(self.path, timeout=30)
            db.row_factory = sqlite3.Row
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
            finally:
                db.close()

    def project(self, db, pid):
        row = db.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
        return (row, json.loads(row["data"])) if row else (None, None)

    def save(self, db, pid, data):
        db.execute("UPDATE projects SET data=? WHERE id=?", (json.dumps(data), pid))

    def job(self, db, jid):
        row = db.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_job(self, db, job):
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,data=excluded.data",
            (job["id"], job["project_id"], job["state"], job["created"], json.dumps(job)),
        )

    def enqueue(self, db, pid, kind, payload):
        job = {
            "id": uid("job"),
            "project_id": pid,
            "state": "queued",
            "stage": kind,
            "progress": 0,
            "created": time.time(),
            "kind": kind,
            "payload": payload,
            "result": None,
            "error": None,
        }
        self.put_job(db, job)
        return job

    def directory(self, pid):
        return self.root / "projects" / pid
