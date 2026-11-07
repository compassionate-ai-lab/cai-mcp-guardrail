"""Repeatable end-to-end synthetic MCP scenario."""

from datetime import timedelta
import json
import os
import shlex
import subprocess
import sys

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .transport import TRACE_META_KEY, command_for


async def run(store, *, manual=False):
    arguments = {"incident_id": "INC-001", "channel": "demo-response-team"}
    async with stdio_client(command_for(store.root, "serve", "--principal", "scripted-demo")) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as session:
            hello = await session.initialize()
            print(f"MCP revision: {hello.protocolVersion}")
            tools = await session.list_tools()
            print("Exposed tools:", ", ".join(tool.name for tool in tools.tools))

            async def call(tool, args, expected):
                reply = await session.call_tool(tool, args)
                data = reply.structuredContent or {}
                actual = data.get("status")
                print(f"{tool}: {actual}")
                if actual != expected:
                    raise RuntimeError(f"Expected {expected}, received {actual}.")
                return data, (reply.meta or {}).get(TRACE_META_KEY)

            await call("read_incident", {"incident_id": "INC-001"}, "read")
            await call("delete_incident", {"incident_id": "INC-001"}, "denied")
            pending, _ = await call("send_notification", arguments, "approval_required")
            item = next(row for row in store.pending() if row["id"] == pending["approval_id"])
            print("Pending synthetic action:")
            print(json.dumps(item["envelope"], indent=2))
            command = command_for(store.root, "approve", item["id"], "--action-hash", item["action_hash"])
            if manual:
                print("Review the action in a second terminal, then approve it if appropriate:")
                argv = [sys.executable, *command.args]
                print(shlex.join(argv) if os.name == "posix" else subprocess.list2cmdline(argv))
                input("Press Enter after recording the approval: ")
            else:
                print("Scripted demo operator grants the synthetic approval.")
                subprocess.run([sys.executable, *command.args], check=True, capture_output=True, text=True)
            await call("send_notification", {**arguments, "channel": "demo-supervisor"}, "approval_required")
            _, request_id = await call("send_notification", arguments, "simulated_notification_queued")
            print(f"Approved notification request ID: {request_id}")
            await call("send_notification", arguments, "approval_required")
    summary = store.audit()
    print(f"Verified audit chain: {summary['count']} entries; tip {summary['tip']}")
