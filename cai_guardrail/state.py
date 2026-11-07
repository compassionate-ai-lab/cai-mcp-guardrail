"""Transactional approvals and a redacted, hash-chained audit trail."""

from collections import Counter
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import sqlite3
import time
from uuid import uuid4

from .policy import canonical, digest, POLICY_HASH, TOOLS

GENESIS = "0" * 64
APPROVAL_WINDOW = 300
APPROVED_WINDOW = 60


class Store:
    def __init__(self, root, *, clock=time.time, initialize=True):
        self.root = Path(root).expanduser()
        if initialize:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("State directory must not be a symlink.")
        stat = self.root.stat()
        if os.name == "posix" and (stat.st_uid != os.getuid() or stat.st_mode & 0o077):
            raise ValueError("State directory must be owned by this user with no group or other permissions.")
        self.root = self.root.resolve()
        self.path = self.root / "state.sqlite3"
        if self.path.is_symlink():
            raise ValueError("State database must not be a symlink.")
        self.clock = clock
        if not initialize:
            if not self.path.is_file():
                raise ValueError("No initialized guardrail state database exists.")
            return
        with closing(self.connect()) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY, action_hash TEXT NOT NULL, envelope TEXT NOT NULL,
                    expires REAL NOT NULL, status TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS approval_action ON approvals(action_hash, status, expires);
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY, event TEXT NOT NULL, hash TEXT NOT NULL
                );
            """)

    def connect(self, *, read_only=False):
        target = self.path.as_uri() + "?mode=ro" if read_only else self.path
        conn = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def transaction(self):
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def _append(self, conn, event, *, tool, reason, request_id=None, approval_id=None, principal=None):
        last = conn.execute("SELECT seq, hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        seq, previous = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS)
        entry = {
            "event": event,
            "time": self.clock(),
            "tool": tool if tool in TOOLS else "unknown",
            "reason": reason,
            "request_id": request_id,
            "approval_id": approval_id,
            "principal": principal,
            "policy_hash": POLICY_HASH,
        }
        record_hash = digest({"seq": seq, "previous": previous, "entry": entry})
        conn.execute("INSERT INTO audit VALUES (?, ?, ?)", (seq, canonical(entry), record_hash))

    def record(self, event, **fields):
        with self.transaction() as conn:
            self._append(conn, event, **fields)

    def _expire(self, conn, now):
        conn.execute(
            "UPDATE approvals SET status='expired', envelope='{}' "
            "WHERE status IN ('pending','approved','rejected') AND expires <= ?", (now,)
        )

    def authorize(self, envelope, request_id):
        """Issue/reuse a pending request, or atomically consume a matching grant."""
        action_hash = digest(envelope)
        fields = {"tool": envelope["tool"], "principal": envelope["principal"], "request_id": request_id}
        with self.transaction() as conn:
            now = self.clock()
            self._expire(conn, now)
            active = conn.execute(
                "SELECT id, status FROM approvals WHERE action_hash=? AND status IN ('pending','approved','rejected')",
                (action_hash,),
            ).fetchone()
            if active and active["status"] == "approved":
                approval_id = active["id"]
                conn.execute("UPDATE approvals SET status='used', envelope='{}' WHERE id=?", (approval_id,))
                self._append(conn, "dispatch_authorized", reason="approval_consumed", approval_id=approval_id, **fields)
                return "allow", approval_id
            if active and active["status"] == "rejected":
                self._append(conn, "denied", reason="approval_rejected", approval_id=active["id"], **fields)
                return "approval_rejected", active["id"]
            approval_id = active["id"] if active else uuid4().hex
            if active is None:
                conn.execute(
                    "INSERT INTO approvals VALUES (?, ?, ?, ?, 'pending')",
                    (approval_id, action_hash, canonical(envelope), now + APPROVAL_WINDOW),
                )
            self._append(conn, "approval_required", reason="operator_review", approval_id=approval_id, **fields)
            return "approval_required", approval_id

    def pending(self):
        with self.transaction() as conn:
            self._expire(conn, self.clock())
            rows = conn.execute("SELECT id, action_hash, envelope, expires FROM approvals WHERE status='pending'").fetchall()
            return [{**dict(row), "envelope": json.loads(row["envelope"])} for row in rows]

    def decide(self, approval_id, expected_hash, approve):
        with self.transaction() as conn:
            now = self.clock()
            self._expire(conn, now)
            row = conn.execute(
                "SELECT * FROM approvals WHERE id=? AND status='pending'", (approval_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Pending approval is unavailable or has expired.")
            envelope = json.loads(row["envelope"])
            if expected_hash != row["action_hash"] or digest(envelope) != expected_hash:
                raise ValueError("The supplied action hash does not match the stored request.")
            if envelope["policy_hash"] != POLICY_HASH:
                raise ValueError("The request was generated under a different policy.")
            status = "approved" if approve else "rejected"
            conn.execute(
                "UPDATE approvals SET status=?, expires=?, envelope=? WHERE id=?",
                (status, (min(row["expires"], now + APPROVED_WINDOW) if approve else row["expires"]),
                 row["envelope"] if approve else "{}", approval_id),
            )
            self._append(conn, status, tool=envelope["tool"], reason="operator_decision",
                         approval_id=approval_id, principal=envelope["principal"])

    @staticmethod
    def _verified_audit(conn, expected_tip=None):
        rows = conn.execute("SELECT * FROM audit ORDER BY seq")
        tip = GENESIS
        entries = []
        for seq, row in enumerate(rows, 1):
            entry = json.loads(row["event"])
            computed = digest({"seq": seq, "previous": tip, "entry": entry})
            if seq != row["seq"] or computed != row["hash"]:
                raise ValueError(f"Audit chain mismatch at position {seq}.")
            tip = computed
            entries.append({"seq": seq, **entry, "hash": tip})
        if expected_tip is not None and tip != expected_tip:
            raise ValueError("Audit tip differs from the supplied checkpoint.")
        return {"count": len(entries), "tip": tip, "entries": entries}


    def audit(self, expected_tip=None):
        with closing(self.connect(read_only=True)) as conn:
            return self._verified_audit(conn, expected_tip)

    def status(self):
        """Count verified audit events and unexpired approvals at one snapshot."""
        with closing(self.connect(read_only=True)) as conn, conn:
            conn.execute("BEGIN")
            report = self._verified_audit(conn)
            queue = dict(conn.execute(
                "SELECT status, count(*) FROM approvals "
                "WHERE status IN ('pending','approved') AND expires > ? GROUP BY status",
                (self.clock(),),
            ).fetchall())
        entries = report["entries"]
        events = Counter(entry["event"] for entry in entries)
        authorized = {entry["request_id"] for entry in entries if entry["event"] == "dispatch_authorized"}
        terminal = {
            entry["request_id"] for entry in entries
            if entry["event"] in {"backend_returned", "outcome_unknown"}
        }
        return {
            "state": "verified",
            "audit": {"count": report["count"], "tip": report["tip"]},
            "event_counts": dict(sorted(events.items())),
            "approvals": {
                "unexpired_pending": queue.get("pending", 0),
                "unexpired_approved": queue.get("approved", 0),
            },
            "dispatches_without_terminal_record": len(authorized - terminal),
        }

    def trace(self, request_id):
        """Return verified redacted entries linked by request or approval ID."""
        report = self.audit()
        entries = report["entries"]
        direct = [entry for entry in entries if entry["request_id"] == request_id]
        if not direct:
            raise ValueError("Request ID was not found in the verified audit log.")
        approvals = {entry["approval_id"] for entry in direct if entry["approval_id"] is not None}
        return {
            "request_id": request_id,
            "audit_tip": report["tip"],
            "entries": [
                entry for entry in entries
                if entry["request_id"] == request_id or entry["approval_id"] in approvals
            ],
        }
