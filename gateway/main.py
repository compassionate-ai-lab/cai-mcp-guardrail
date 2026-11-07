import os
import logging
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any, Optional
from arize.phoenix.otel import register
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

tracer_provider = register(
    project_name=os.getenv("OTEL_SERVICE_NAME", "cai-contextforge-gateway"),
    endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://phoenix:6006/v1/traces"),
    auto_instrument=True,
    batch=True
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cai-gateway")

app = FastAPI(title="CAI ContextForge Gateway", version="1.0.0")
FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)

class ToolCallRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Any] = 1
    method: str
    params: Dict[str, Any]

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "cai-contextforge-gateway"}

@app.post("/v1/mcp")
async def mcp_router(payload: ToolCallRequest):
    logger.info(f"Received MCP method execution: {payload.method}")
    if payload.method == "tools/call":
        args = payload.params.get("arguments", {})
        if "rm -rf" in str(args).lower() or "drop table" in str(args).lower():
            return {
                "jsonrpc": "2.0",
                "id": payload.id,
                "error": {
                    "code": -32004,
                    "message": "CAI Gateway Floor Veto: Destructive operation blocked.",
                    "data": {"motto": 4, "severity": "CRITICAL"}
                }
            }
    return {
        "jsonrpc": "2.0",
        "id": payload.id,
        "result": {"status": "EXECUTED", "tool": payload.params.get("name")}
    }
