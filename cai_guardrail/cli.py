"""CLI for the local MCP server, operator review, and audit verification."""

import argparse
import asyncio
import json
from pathlib import Path
import re
import sqlite3
import sys

from .state import Store


def parser():
    cli = argparse.ArgumentParser(prog="cai-guardrail")
    cli.add_argument("--state-dir", type=Path, required=True, help="Private directory for synthetic demo state.")
    actions = cli.add_subparsers(dest="action", required=True)
    serve = actions.add_parser("serve", help="Run the local MCP stdio façade.")
    serve.add_argument("--principal", default="local-demo", help="Trusted launcher label for the local principal.")
    actions.add_parser("pending", help="Show the exact synthetic actions awaiting operator review.")
    for verb in ("approve", "reject"):
        decision = actions.add_parser(verb, help=f"{verb.capitalize()} one pending action.")
        decision.add_argument("approval_id")
        decision.add_argument("--action-hash", required=True)
    audit = actions.add_parser("audit", help="Verify the audit hash chain and print its checkpoint.")
    audit.add_argument("--expected-tip", help="Require an exact externally retained tip.")
    audit.add_argument("--events", action="store_true", help="Include redacted audit entries.")
    actions.add_parser("status", help="Verify local state and summarize approvals and audit events.")
    trace = actions.add_parser("trace", help="Show redacted audit entries for one request ID.")
    trace.add_argument("request_id")
    demo = actions.add_parser("demo", help="Run the synthetic flow.")
    demo.add_argument("--manual", action="store_true", help="Wait for real operator approval in a second terminal.")
    actions.add_parser("_mock-backend")
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    if args.action == "serve" and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", args.principal):
        cli.error("Principal must contain 1–64 ASCII letters, digits, hyphens, or underscores.")
    try:
        read_only = args.action in {"audit", "status", "trace"}
        store = Store(args.state_dir, initialize=not read_only)
        if args.action in {"serve", "_mock-backend"}:
            from .transport import mock_backend, serve
            asyncio.run(serve(store, args.principal) if args.action == "serve" else mock_backend(store))
        elif args.action == "demo":
            from .demo import run
            asyncio.run(run(store, manual=args.manual))
        elif args.action == "pending":
            print(json.dumps(store.pending(), indent=2))
        elif args.action == "audit":
            report = store.audit(args.expected_tip)
            if not args.events:
                report.pop("entries")
            print(json.dumps(report, indent=2))
        elif args.action == "status":
            print(json.dumps(store.status(), indent=2))
        elif args.action == "trace":
            print(json.dumps(store.trace(args.request_id), indent=2))
        else:
            store.decide(args.approval_id, args.action_hash, args.action == "approve")
            print("Approved for one matching retry." if args.action == "approve" else "Rejected.")
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"cai-guardrail: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
