# Security model

## Scope and trust boundary

This release is a local reference implementation for synthetic tool calls. It runs the built-in mock backend as a child process and uses the MCP SDK on both sides. The OS account, launcher configuration, Python environment, policy code, SQLite directory, and operator terminal are trusted. The principal is a label set by that launcher. It is not an authenticated remote identity.

A caller with shell, process, database, or alternate tool access can bypass the demo. Keep operator commands and the state directory outside the agent's tool surface. Use an owner-only directory on POSIX and private user access controls on Windows. This project does not configure a sandbox, a separate operator identity, or remote authorization. Use synthetic incident IDs and channels only.

## Approval and effect semantics

The approval digest covers the principal, running session, backend identifier, policy hash, tool name, and exact validated arguments. An approval is consumed in the same transaction that records permission to dispatch. A lost response or interrupted dispatch can leave the outcome unknown. The proxy does not automatically retry. Inspect the backend state before proposing another action. An authorized dispatch entry without a terminal entry can indicate process interruption.

The audit chain omits raw argument values, prompts, and backend output. Pending approvals temporarily retain bounded synthetic arguments for operator review. The mock effects file contains synthetic IDs and channel labels. State is retained until the operator removes it. The hash chain can reveal changes to stored entries when verified, and a separately retained exact tip can expose truncation or a rewritten chain. A trusted checkpoint is needed to defend against someone who can rewrite the database and recompute hashes. The local chain is not a signed or remotely anchored log.

## Read-only operations

`status` and `trace` verify the local hash chain and read existing state without modifying it. They do not export telemetry. Their output includes operator-visible identifiers and should be handled as local operational data. A verified chain and a returned backend response do not establish independent integrity or successful real-world effects.

## Reporting

Use the repository's private vulnerability reporting feature if maintainers enable it. For a public issue, share only a synthetic reproduction and version information.
