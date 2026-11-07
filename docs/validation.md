# Validation for v0.2.0

The local release was tested on Linux x86_64 with Python 3.12.14 and MCP SDK 1.29.0. The SDK negotiated MCP revision 2025-11-25. The repository includes a GitHub Actions matrix for Python 3.11 and 3.12. Its hosted runs begin after the workflow is uploaded.

## Acceptance checks

Run `python -m unittest discover -s tests -v`. The local suite passed 19 tests. It checks tool policy, argument validation, trusted approval binding, expiry, rejection, concurrent grant consumption, audit changes, and uncertain dispatch outcomes.

The end-to-end test starts the guardrail and a separate mock backend. The mock records every call it receives. The test expects exactly two backend effects across a longer sequence: one allowed read and one approved notification. The forbidden deletion, unknown tool, forged approval flag, modified notification, and repeated notification without a fresh approval are absent from the backend's effects file.

The new tests check read-only state inspection, approval counts without changing the database, request-to-approval correlation, and refusal to report through a damaged audit chain. The end-to-end test also checks that a real MCP response carries the same request ID that the trace uses.

## Local timing

Run `python -m tests.benchmark --samples 120`. The included [raw JSON summary](benchmark-results.json) measures serial MCP read round trips against the direct mock and the guarded route. Both paths use the same backend behavior. There are 10 warm-ups per path. The guarded path includes a second stdio hop and local SQLite audit transactions.

| Path | Median | 95th percentile |
| --- | ---: | ---: |
| Direct mock | 0.427 ms | 0.562 ms |
| Through guardrail | 1.378 ms | 1.724 ms |

The observed p95 difference was **1.162 ms** on this run. The sample excludes process startup, operator review, network latency, and concurrent traffic. It is a reproducible local baseline, with no inference about production latency or attack coverage.
