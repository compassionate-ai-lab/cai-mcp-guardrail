import json
import logging
from typing import Dict, Any, Tuple

class CAIMiddlewareGuardrail:
    def __init__(self, harm_threshold: float = 0.85):
        self.harm_threshold = harm_threshold
        logging.basicConfig(level=logging.INFO)

    def evaluate_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        arg_str = json.dumps(arguments).lower()
        destructive_keywords = ["rm -rf", "drop database", "overwrite_backup", "terminate_safety"]
        if any(kw in arg_str for kw in destructive_keywords):
            return False, "MOTTO_4_VIOLATION: Irreversible destructive action detected.", arguments

        if tool_name in ["automated_decision_engine", "user_access_revoke"]:
            if not arguments.get("human_in_loop_override", False):
                arguments["human_in_loop_override"] = True
                arguments["challenge_window_seconds"] = 86400
                logging.info("MOTTO_5_ADAPTATION: Injected human override mechanism into call.")

        if arguments.get("resource_intensity", "low") == "extreme":
            arguments["eco_mode_enabled"] = True
            logging.info("MOTTO_6_ADAPTATION: Enabled eco-mode throttling for high-compute call.")

        if arguments.get("context_type") == "humanitarian_crisis":
            arguments["execution_priority"] = "URGENT_P0"
            logging.info("MOTTO_3_BOOST: Priority escalated for life-safety context.")

        return True, "APPROVED", arguments

    def intercept_mcp_request(self, json_rpc_payload: dict) -> dict:
        method = json_rpc_payload.get("method")
        if method == "tools/call":
            params = json_rpc_payload.get("params", {})
            tool_name = params.get("name")
            args = params.get("arguments", {})
            approved, reason, updated_args = self.evaluate_tool_call(tool_name, args)
            if not approved:
                return {
                    "jsonrpc": "2.0",
                    "id": json_rpc_payload.get("id"),
                    "error": {
                        "code": -32004,
                        "message": f"CAI Middleware Veto: {reason}",
                        "data": {"motto_violated": 4, "severity": "CRITICAL"}
                    }
                }
            json_rpc_payload["params"]["arguments"] = updated_args
        return json_rpc_payload
