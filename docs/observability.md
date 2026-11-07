# Operator observability

Use the same private state directory as the running guardrail:

```bash
cai-guardrail --state-dir .demo-state status
cai-guardrail --state-dir .demo-state trace REQUEST_ID
cai-guardrail --state-dir .demo-state audit --expected-tip CHECKPOINT
```

All three commands require an existing state database. The inspection path opens it read-only. It checks the whole hash chain before reporting a summary or filtered entries. Missing state, missing request IDs, or verification failures exit with an error.

## Status fields

- `audit.count` and `audit.tip` identify the verified snapshot.
- `event_counts` counts recorded events by type. Approval request counts can include repeated attempts for one approval.
- `approvals` counts unexpired pending requests and unspent approvals across the local database. A record can outlive its MCP session until expiry. Its grant remains bound to the original session.
- `dispatches_without_terminal_record` counts authorized requests with neither a backend response nor a recorded unknown outcome. These can be in progress or interrupted. Reconcile the backend before retrying.

Status describes local state and chain consistency. It does not probe a running backend, assert service readiness, or establish that a backend result produced its intended effect.

## Request trace

Audited MCP tool results expose the server-generated ID in `_meta["com.amitray/guardrail-request-id"]`. A policy error also exposes `structuredContent.request_id` for clients that display structured tool errors. A transport error or failure before an audit record is written may have no trace ID.

The trace reports the requested ID, the audit tip at inspection, and entries connected through its request or approval IDs. A successful notification retry can therefore show the earlier proposal, operator decision, dispatch authorization, and backend response. Trace entries omit raw arguments and backend output. Use the operator-only `pending` command to see a currently pending synthetic action before reviewing it.

The hash chain detects changes relative to its stored history. Keep an independently trusted tip if you need to detect truncation or a rewritten history. The CLI emits JSON for local scripting. It uses no telemetry collector and exposes no HTTP endpoint.
