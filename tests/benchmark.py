"""Measure local stdio round trips with and without the guardrail."""

import argparse
import asyncio
from datetime import timedelta
import json
import math
from pathlib import Path
import platform
import statistics
from tempfile import TemporaryDirectory
import time

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from cai_guardrail.transport import command_for


async def measure(state, command, count):
    async with stdio_client(command_for(state, command)) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=15)) as client:
            await client.initialize()
            await client.list_tools()
            times = []
            for index in range(count + 10):
                start = time.perf_counter()
                reply = await client.call_tool("read_incident", {"incident_id": "INC-001"})
                elapsed = (time.perf_counter() - start) * 1000
                if reply.isError or reply.structuredContent.get("status") != "read":
                    raise RuntimeError("Benchmark read failed.")
                if index >= 10:
                    times.append(elapsed)
    return {
        "p50_ms": round(statistics.median(times), 3),
        "p95_ms": round(sorted(times)[math.ceil(count * .95) - 1], 3),
    }


async def run(count):
    with TemporaryDirectory() as folder:
        root = Path(folder)
        baseline = await measure(root / "baseline", "_mock-backend", count)
        guarded = await measure(root / "guarded", "serve", count)
    return {
        "platform": f"{platform.system()} {platform.machine()}",
        "python": platform.python_version(),
        "samples_per_path": count,
        "warmup_per_path": 10,
        "direct_mock": baseline,
        "through_guardrail": guarded,
        "p95_difference_ms": round(guarded["p95_ms"] - baseline["p95_ms"], 3),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=120)
    args = parser.parse_args()
    if not 20 <= args.samples <= 5000:
        parser.error("samples must be between 20 and 5000")
    print(json.dumps(asyncio.run(run(args.samples)), indent=2))
