# Compassionate AI MCP Guardrail

A local reference implementation from **Compassionate AI Lab**, founded by **Dr. Sri Amit Ray**. It applies Ahimsa and human oversight to a specific question: should an AI agent be allowed to execute this tool call?

**v0.2.0** runs a synthetic incident scenario through a real MCP stdio client, guardrail server, and separate mock backend. All runtime effects stay local.

| MCP tool | Policy | Demonstrated result |
| --- | --- | --- |
| `read_incident` | Allow validated arguments | Returns a synthetic incident record |
| `send_notification` | Require operator approval | Queues a simulated notification after one exact, approved retry |
| `delete_incident` | Deny | Produces no backend call |
| Unknown tools or unexpected arguments | Deny | Produces no backend call |

## Run the demo

Use Python 3.11 or later. These commands assume a POSIX shell and an extracted or cloned project.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install .
cai-guardrail --state-dir .demo-state demo
cai-guardrail --state-dir .demo-state status
cai-guardrail --state-dir .demo-state audit --events
```

On Windows PowerShell, activate with `.\.venv\Scripts\Activate.ps1`, or invoke the executable in `.venv\Scripts` directly. On Windows, choose a user-private state directory. Linux with Python 3.12 is the locally tested environment.

The scripted demo uses an explicitly simulated operator. To approve the call yourself, run `cai-guardrail --state-dir .demo-state demo --manual`. While the demo waits, run the following in a second terminal from the same project directory and environment.

```bash
cai-guardrail --state-dir .demo-state pending
cai-guardrail --state-dir .demo-state approve APPROVAL_ID --action-hash ACTION_HASH
```

Replace the placeholders with values from `pending` after reviewing the action. The approval expires within 60 seconds of the operator decision, and the original pending request expires after five minutes. Return to the first terminal and press Enter. The demo checks that changed arguments still require review and that a used approval cannot be replayed. For a custom client flow, `reject` uses the same arguments as `approve`.

## Inspect a request

The demo prints the request ID of the approved notification. Pass that ID to:

```bash
cai-guardrail --state-dir .demo-state trace REQUEST_ID
```

`trace` links the request to its approval and dispatch records without showing tool arguments. `status` checks the local audit chain and reports event counts, the unexpired approval queue, and dispatches without terminal records. Both commands read existing state and use no network. See [operator observability](docs/observability.md) for the output contract.

## Connect an MCP client

Configure a local stdio MCP server with your installed Python executable and a private absolute state directory. The exact configuration wrapper depends on the host. The following shows the server entry in a host using `command` and `args`.

```json
{
  "command": "/absolute/path/to/.venv/bin/python",
  "args": [
    "-m", "cai_guardrail.cli",
    "--state-dir", "/absolute/path/to/private-state",
    "serve", "--principal", "local-demo"
  ]
}
```

The tested client is the official Python MCP SDK 1.29.0, negotiating protocol revision `2025-11-25`. Keep the connection open through approval and retry. Configure the guardrail as the only tool route for this experiment. A host or process that can directly launch the mock backend can bypass it.

## Test and measure

```bash
python -m unittest discover -s tests -v
python -m tests.benchmark --samples 120
```

The end-to-end test checks actual backend effects, not just policy responses. See [validation](docs/validation.md) for the measured run, [design and integration](docs/design.md) for the adapter contract, and [security model](SECURITY.md) for the trust boundary.

## Publish the project

[Release instructions](docs/release.md) cover a new GitHub repository, a test release, and the website demo. Open [docs/index.html](docs/index.html) in a browser for a self-contained simulation that does not execute MCP or send requests.

Licensed under [MIT](LICENSE).
