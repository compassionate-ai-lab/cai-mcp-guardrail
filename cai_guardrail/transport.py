"""MCP stdio façade and the built-in, no-network incident simulator."""

from datetime import timedelta
import os
import sqlite3
import sys

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import __version__
from .core import Guardrail
from .policy import TOOLS, evaluate


def make_server(name, handler):
    server = Server(name, version=__version__)

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(name=tool, description=rule["description"], inputSchema=rule["schema"])
            for tool, rule in TOOLS.items()
        ]

    server.call_tool(validate_input=False)(handler)
    return server


async def stdio(server):
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


MESSAGES = {
    "denied": "The guardrail blocked the tool call before execution.",
    "approval_required": "The guardrail did not execute this call. Ask the operator to review the pending approval, then retry the same arguments in this session after approval.",
    "approval_rejected": "The operator rejected this action. The tool was not executed.",
    "outcome_unknown": "The outcome is unknown. Reconcile the mock backend state before proposing any retry.",
    "guardrail_unavailable": "The guardrail could not authorize this request. No retry was attempted.",
}


TRACE_META_KEY = "com.amitray/guardrail-request-id"


def failure(status, **data):
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=MESSAGES[status])],
        isError=True,
        _meta={TRACE_META_KEY: data["request_id"]} if "request_id" in data else None,
        structuredContent={"status": status, **data},
    )


def command_for(state_dir, action, *args):
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "cai_guardrail.cli", "--state-dir", os.fspath(state_dir), action, *args],
    )


async def serve(store, principal):
    async with stdio_client(command_for(store.root, "_mock-backend")) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=8)) as upstream:
            await upstream.initialize()

            async def dispatch(tool, arguments):
                return await upstream.call_tool(tool, arguments)

            guardrail = Guardrail(store, principal, dispatch)

            async def handle(tool, arguments):
                try:
                    outcome = await guardrail.call(tool, arguments)
                except (sqlite3.Error, ValueError):
                    return failure("guardrail_unavailable")
                if outcome.status == "dispatched":
                    metadata = {**(outcome.result.meta or {}), TRACE_META_KEY: outcome.request_id}
                    return outcome.result.model_copy(update={"meta": metadata})
                data = {"reason": outcome.reason, "request_id": outcome.request_id}
                if outcome.approval_id is not None:
                    data["approval_id"] = outcome.approval_id
                return failure(outcome.status, **data)

            await stdio(make_server("cai-mcp-guardrail", handle))


async def mock_backend(store):
    events = store.root / "mock-effects.jsonl"
    if events.is_symlink():
        raise ValueError("Mock event file must not be a symlink.")

    async def handle(tool, arguments):
        from .policy import canonical
        decision, reason = evaluate(tool, arguments)
        if reason in {"invalid_arguments", "unknown_tool"}:
            return failure("denied", reason=reason)
        event = {"tool": tool, **arguments}
        # The raw backend deliberately logs any valid direct invocation, even delete.
        # This makes the absence of denied effects observable in integration tests.
        fd = os.open(events, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "ab") as stream:
                stream.write((canonical(event) + "\n").encode("ascii"))
        except OSError:
            return failure("outcome_unknown", reason="mock_event_write_failed")
        if decision == "allow":
            return {"status": "read", "incident_id": arguments["incident_id"], "synthetic": True}
        if tool == "send_notification":
            return {"status": "simulated_notification_queued", "synthetic": True}
        return {"status": "simulated_deletion", "synthetic": True}

    await stdio(make_server("cai-synthetic-incident-backend", handle))
