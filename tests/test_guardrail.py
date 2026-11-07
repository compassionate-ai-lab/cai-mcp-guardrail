import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from cai_guardrail.core import Guardrail
from cai_guardrail.policy import action_envelope, evaluate
from cai_guardrail.state import Store
from cai_guardrail.transport import TRACE_META_KEY, command_for

READ = {"incident_id": "INC-001"}
SEND = {**READ, "channel": "demo-response-team"}


class Fixture:
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = 1000
        self.store = Store(self.root, clock=lambda: self.now)

    def approve(self, approval_id, approve=True):
        item = next(row for row in self.store.pending() if row["id"] == approval_id)
        self.store.decide(approval_id, item["action_hash"], approve)


class PolicyTests(unittest.TestCase):
    def test_known_policy(self):
        self.assertEqual(evaluate("read_incident", READ)[0], "allow")
        self.assertEqual(evaluate("send_notification", SEND)[0], "require_approval")
        self.assertEqual(evaluate("delete_incident", READ), ("deny", "irreversible_action"))
        self.assertEqual(evaluate("delete_all_records", {}), ("deny", "unknown_tool"))

    def test_reject_malformed_and_self_authorizing_arguments(self):
        for args in [None, [], {"incident_id": 1}, {"incident_id": "INC-123"},
                     {**READ, "human_in_loop_override": True}, {**READ, "execution_priority": "URGENT_P0"}]:
            with self.subTest(args=args):
                self.assertEqual(evaluate("read_incident", args), ("deny", "invalid_arguments"))


class StateTests(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.envelope = action_envelope("tester", "session-1", "send_notification", SEND)

    def test_concurrent_consumption_dispatches_once(self):
        _, approval_id = self.store.authorize(self.envelope, "first")
        self.approve(approval_id)
        with ThreadPoolExecutor(max_workers=8) as pool:
            decisions = list(pool.map(lambda i: self.store.authorize(self.envelope, str(i))[0], range(8)))
        self.assertEqual(decisions.count("allow"), 1)
        self.assertEqual(decisions.count("approval_required"), 7)

    def test_expired_approval_requires_fresh_review(self):
        _, first_id = self.store.authorize(self.envelope, "first")
        self.approve(first_id)
        self.now += 61
        decision, new_id = self.store.authorize(self.envelope, "second")
        self.assertEqual(decision, "approval_required")
        self.assertNotEqual(new_id, first_id)

    def test_expired_pending_cannot_be_approved(self):
        _, approval_id = self.store.authorize(self.envelope, "first")
        item = self.store.pending()[0]
        self.now += 301
        with self.assertRaises(ValueError):
            self.store.decide(approval_id, item["action_hash"], True)
        self.assertEqual(self.store.pending(), [])

    def test_rejected_action_cannot_be_requeued_until_expiry(self):
        _, approval_id = self.store.authorize(self.envelope, "first")
        self.approve(approval_id, False)
        self.assertEqual(self.store.authorize(self.envelope, "retry"), ("approval_rejected", approval_id))
        self.assertEqual(self.store.pending(), [])
        self.now += 301
        self.assertEqual(self.store.authorize(self.envelope, "later")[0], "approval_required")

    def test_operator_cannot_approve_wrong_digest(self):
        _, approval_id = self.store.authorize(self.envelope, "first")
        with self.assertRaises(ValueError):
            self.store.decide(approval_id, "0"*64, True)
        self.assertEqual(self.store.pending()[0]["id"], approval_id)

    def test_audit_detects_edit(self):
        self.store.authorize(self.envelope, "first")
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("UPDATE audit SET event='{}' WHERE seq=1")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.store.audit()

    def test_read_only_inspection_does_not_initialize_state(self):
        empty = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            Store(empty, initialize=False)
        self.assertFalse(empty.exists())
        empty.mkdir(mode=0o700)
        with self.assertRaises(ValueError):
            Store(empty, initialize=False)
        self.assertEqual(list(empty.iterdir()), [])

    def test_status_counts_queue_and_dispatches_without_mutating_state(self):
        _, approval_id = self.store.authorize(self.envelope, "proposal")
        observer = Store(self.root, initialize=False, clock=lambda: self.now)
        self.assertEqual(observer.status()["approvals"]["unexpired_pending"], 1)
        self.approve(approval_id)
        self.assertEqual(observer.status()["approvals"]["unexpired_approved"], 1)
        self.assertEqual(self.store.authorize(self.envelope, "dispatch")[0], "allow")
        self.assertEqual(observer.status()["dispatches_without_terminal_record"], 1)
        self.store.record("outcome_unknown", tool="send_notification", reason="timeout", request_id="dispatch")
        self.assertEqual(observer.status()["dispatches_without_terminal_record"], 0)
        self.assertEqual(observer.status()["event_counts"]["outcome_unknown"], 1)
        self.store.authorize(self.envelope, "new-proposal")
        self.now += 301
        snapshot = observer.status()
        self.assertEqual(snapshot["approvals"]["unexpired_pending"], 0)
        with sqlite3.connect(self.store.path) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM approvals WHERE status='pending'").fetchone()[0], 1)

    def test_trace_correlates_and_redacts_exact_approval_lineage(self):
        _, approval_id = self.store.authorize(self.envelope, "proposal")
        self.approve(approval_id)
        self.store.authorize(self.envelope, "retry")
        self.store.record("backend_returned", tool="send_notification", reason="received",
                          request_id="retry", approval_id=approval_id)
        self.store.record("denied", tool="delete_incident", reason="irreversible_action", request_id="other")
        result = self.store.trace("retry")
        self.assertEqual([event["event"] for event in result["entries"]],
                         ["approval_required", "approved", "dispatch_authorized", "backend_returned"])
        self.assertNotIn("INC-001", json.dumps(result))
        self.assertNotIn("demo-response-team", json.dumps(result))
        with self.assertRaises(ValueError):
            self.store.trace("missing")

    def test_status_and_trace_reject_corrupted_audit(self):
        self.store.authorize(self.envelope, "proposal")
        self.store.record("denied", tool="delete_incident", reason="blocked", request_id="other")
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("UPDATE audit SET event='{}' WHERE seq=2")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.store.status()
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.store.trace("proposal")

    def test_saved_tip_detects_truncation(self):
        self.store.authorize(self.envelope, "first")
        tip = self.store.audit()["tip"]
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("DELETE FROM audit")
        with self.assertRaisesRegex(ValueError, "checkpoint"):
            self.store.audit(tip)


class CoreTests(Fixture, unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_failure_is_indeterminate_and_consumes_grant(self):
        calls = []

        async def dispatch(tool, args):
            calls.append((tool, args))
            raise TimeoutError

        core = Guardrail(self.store, "tester", dispatch)
        first = await core.call("send_notification", SEND)
        self.approve(first.approval_id)
        result = await core.call("send_notification", SEND)
        self.assertEqual(result.status, "outcome_unknown")
        self.assertEqual((await core.call("send_notification", SEND)).status, "approval_required")
        self.assertEqual(len(calls), 1)

    async def test_audit_failure_before_dispatch_fails_closed(self):
        async def dispatch(tool, args):
            self.fail("dispatch must not run when the audit prewrite fails")

        core = Guardrail(self.store, "tester", dispatch)
        with sqlite3.connect(self.store.path) as conn:
            conn.execute("DROP TABLE audit")
        with self.assertRaises(sqlite3.Error):
            await core.call("read_incident", READ)

    async def test_audit_failure_after_dispatch_keeps_outcome_unknown(self):
        async def dispatch(tool, args):
            with sqlite3.connect(self.store.path) as conn:
                conn.execute("DROP TABLE audit")
            raise TimeoutError

        core = Guardrail(self.store, "tester", dispatch)
        self.assertEqual((await core.call("read_incident", READ)).status, "outcome_unknown")

    async def test_cancelled_dispatch_is_recorded_as_unknown(self):
        async def dispatch(tool, args):
            raise asyncio.CancelledError

        core = Guardrail(self.store, "tester", dispatch)
        with self.assertRaises(asyncio.CancelledError):
            await core.call("read_incident", READ)
        self.assertEqual(self.store.audit()["entries"][-1]["event"], "outcome_unknown")

    async def test_approval_is_bound_to_session_principal_policy_and_arguments(self):
        original = action_envelope("one", "session-a", "send_notification", SEND)
        _, approval_id = self.store.authorize(original, "first")
        self.approve(approval_id)
        changes = {"principal": "two", "session": "session-b", "policy_hash": "different",
                   "arguments": {**SEND, "channel": "demo-supervisor"}}
        for key, value in changes.items():
            with self.subTest(key=key):
                self.assertEqual(self.store.authorize({**original, key: value}, "changed")[0], "approval_required")
        self.assertEqual(self.store.authorize(original, "exact")[0], "allow")


class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_effects_and_retry_flow(self):
        with TemporaryDirectory() as root:
            store = Store(root)
            async with stdio_client(command_for(root, "serve")) as (reader, writer):
                async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
                    hello = await session.initialize()
                    self.assertEqual(hello.protocolVersion, "2025-11-25")
                    self.assertEqual(len((await session.list_tools()).tools), 3)
                    for name, args, reason in [
                        ("delete_incident", READ, "irreversible_action"),
                        ("send_notification", {**SEND, "human_in_loop_override": True}, "invalid_arguments"),
                        ("delete_all_records", {}, "unknown_tool"),
                    ]:
                        denied = await session.call_tool(name, args)
                        self.assertTrue(denied.isError)
                        self.assertEqual(denied.structuredContent["reason"], reason)
                        self.assertEqual(denied.meta[TRACE_META_KEY], denied.structuredContent["request_id"])
                    self.assertFalse((Path(root) / "mock-effects.jsonl").exists())
                    self.assertFalse((await session.call_tool("read_incident", READ)).isError)
                    blocked = await session.call_tool("send_notification", SEND)
                    self.assertTrue(blocked.isError)
                    item = store.pending()[0]
                    self.assertEqual(blocked.structuredContent["approval_id"], item["id"])
                    store.decide(item["id"], item["action_hash"], True)
                    wrong = await session.call_tool("send_notification", {**SEND, "channel": "demo-supervisor"})
                    self.assertTrue(wrong.isError)
                    exact = await session.call_tool("send_notification", SEND)
                    self.assertEqual(exact.structuredContent["status"], "simulated_notification_queued")
                    trace = store.trace(exact.meta[TRACE_META_KEY])
                    self.assertEqual([row["event"] for row in trace["entries"]],
                                     ["approval_required", "approved", "dispatch_authorized", "backend_returned"])
                    replay = await session.call_tool("send_notification", SEND)
                    self.assertEqual(replay.structuredContent["status"], "approval_required")
            events = [json.loads(line) for line in (Path(root) / "mock-effects.jsonl").read_text().splitlines()]
            self.assertEqual(events, [{"tool": "read_incident", **READ}, {"tool": "send_notification", **SEND}])
            audit = store.audit()
            self.assertGreater(audit["count"], 0)
            self.assertNotIn("demo-response-team", json.dumps(audit))
            self.assertNotIn("INC-001", json.dumps(audit))
