"""Framework-independent dispatch gate. Adapters own transport and identity."""

import asyncio
from dataclasses import dataclass
import sqlite3
from uuid import uuid4

from .policy import action_envelope, evaluate


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    request_id: str
    approval_id: str | None = None
    result: object = None


class Guardrail:
    def __init__(self, store, principal, dispatch):
        self.store = store
        self.principal = principal
        self.session = uuid4().hex
        self.dispatch = dispatch

    async def call(self, tool, arguments):
        request_id = uuid4().hex
        fields = {"tool": tool, "principal": self.principal, "request_id": request_id}
        decision, reason = evaluate(tool, arguments)
        if decision == "deny":
            self.store.record("denied", reason=reason, **fields)
            return Outcome("denied", reason, request_id)
        # Validated contracts contain only strings. Copy before any async boundary.
        arguments = dict(arguments)
        approval_id = None
        if decision == "require_approval":
            envelope = action_envelope(self.principal, self.session, tool, arguments)
            decision, approval_id = self.store.authorize(envelope, request_id)
            if decision != "allow":
                return Outcome(decision, decision, request_id, approval_id)
        else:
            self.store.record("dispatch_authorized", reason=reason, **fields)
        fields["approval_id"] = approval_id
        try:
            result = await self.dispatch(tool, arguments)
        except asyncio.CancelledError:
            self._record_after_dispatch("outcome_unknown", "cancelled_during_dispatch", fields)
            raise
        except Exception:
            self._record_after_dispatch("outcome_unknown", "backend_failure_or_timeout", fields)
            return Outcome("outcome_unknown", "backend_failure_or_timeout", request_id, approval_id)
        if not self._record_after_dispatch("backend_returned", "received_backend_result", fields):
            return Outcome("outcome_unknown", "result_audit_unavailable", request_id, approval_id)
        return Outcome("dispatched", "backend_returned", request_id, approval_id, result)

    def _record_after_dispatch(self, event, reason, fields):
        try:
            self.store.record(event, reason=reason, **fields)
        except sqlite3.Error:
            # Authorization was already recorded. A later storage failure cannot
            # prove that the backend failed to apply the authorized action.
            return False
        return True
