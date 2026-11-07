# v0.2.0

This release adds local operator observability to the MCP guardrail.

- `status` verifies the local audit chain and summarizes event counts, active approvals, and dispatches with no terminal record.
- `trace REQUEST_ID` correlates an MCP request with its approval and dispatch history. The server supplies the request ID as namespaced MCP result metadata.
- Inspection commands use an existing SQLite database in read-only mode. The release includes the archive review and updated website copy.
- The stdio demo, single-use approvals, No-Harm policies, and synthetic backend remain the tested execution path. The local suite has 19 passing tests.

This release targets local synthetic workflows. Status reports local audit state. Remote MCP gateways, external telemetry, and the deployment stack require separate integration work.
