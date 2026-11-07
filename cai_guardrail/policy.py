"""Fixed, bounded tool contracts for the synthetic incident demo."""

from hashlib import sha256
import json

from jsonschema import Draft202012Validator


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return sha256(canonical(value).encode("ascii")).hexdigest()


def schema(**properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


INCIDENT = {"type": "string", "enum": ["INC-001", "INC-002"]}
CHANNEL = {"type": "string", "enum": ["demo-response-team", "demo-supervisor"]}
BACKEND = "synthetic-incident-server-v1"
POLICY_VERSION = "no-harm-demo-v1"
TOOLS = {
    "read_incident": {
        "decision": "allow",
        "description": "Read a synthetic incident record.",
        "schema": schema(incident_id=INCIDENT),
    },
    "send_notification": {
        "decision": "require_approval",
        "description": "Queue a simulated notification after local operator approval.",
        "schema": schema(incident_id=INCIDENT, channel=CHANNEL),
    },
    "delete_incident": {
        "decision": "deny",
        "description": "Permanently delete a synthetic incident record. Blocked by the guardrail.",
        "schema": schema(incident_id=INCIDENT),
    },
}
POLICY_HASH = digest({"version": POLICY_VERSION, "backend": BACKEND, "tools": TOOLS})
VALIDATORS = {name: Draft202012Validator(rule["schema"]) for name, rule in TOOLS.items()}


def evaluate(name, arguments):
    rule = TOOLS.get(name)
    if rule is None:
        return "deny", "unknown_tool"
    if not VALIDATORS[name].is_valid(arguments):
        return "deny", "invalid_arguments"
    if rule["decision"] == "deny":
        return "deny", "irreversible_action"
    return rule["decision"], "policy_match"


def action_envelope(principal, session, tool, arguments):
    return {
        "principal": principal,
        "session": session,
        "backend": BACKEND,
        "policy_hash": POLICY_HASH,
        "tool": tool,
        "arguments": arguments,
    }
