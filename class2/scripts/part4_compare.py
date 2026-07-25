from __future__ import annotations

import argparse
import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.load_test import run_load_test


def _print_what_changed() -> None:
    print("--- What changed in Part 4 (read before you interpret the table) ---")
    print()
    print("  Arm A (Parts 2–3):  Client → Naive FastAPI + Transformers")
    print("  Arm B (Part 4):     Client → RelayServe → llama.cpp ×2")
    print()
    print("  TWO things differ — do not credit RelayServe alone:")
    print()
    print("  1. ENGINE SWAP (main load impact)")
    print("     Transformers generate() per request  →  llama.cpp inference servers")
    print("     Different KV handling, memory profile, and runtime.")
    print("     This is why OOM / error rates may improve — not because HTTP routing is magic.")
    print()
    print("  2. GATEWAY LAYER (operability)")
    print("     RelayServe adds: request queue, micro-batch window, backend routing,")
    print("     and /metrics (queue_depth, TTFT, KV stats).")
    print("     These help you SEE and SHAPE load — they do not replace a good engine.")
    print()
    print("  Counterfactual: RelayServe → same naive Transformers = same OOM at same concurrency.")
    print()


def _print_reflection_prompts() -> None:
    print("--- Reflection (split gateway vs engine — required for Part 7) ---")
    print()
    print("  Q1. Which improvements came from the llama.cpp ENGINE?")
    print("      (KV memory, inference loop, surviving concurrency, tok/s)")
    print()
    print("  Q2. Which improvements came from the RelayServe GATEWAY?")
    print("      (queue_depth, queue_ms, routing across :8081/:8082, /metrics visibility)")
    print()
    print("  Q3. What would still break if the gateway routed to the naive server?")
    print("      (This is the Part 7 punchline: gateway ≠ engine.)")
    print()


async def compare(naive_url: str, relay_url: str, concurrency: int) -> None:
    print("Part 4 — Naive server vs RelayServe + llama.cpp")
    print(f"Concurrency: {concurrency}")
    print(f"Arm A:       {naive_url}")
    print(f"Arm B:       {relay_url}\n")

    _print_what_changed()

    print("Running load test — Arm A (naive Transformers)...")
    naive = await run_load_test(base_url=naive_url, concurrency=concurrency, num_requests=concurrency)

    print("\nRunning load test — Arm B (RelayServe → llama.cpp)...")
    relay = await run_load_test(base_url=relay_url, concurrency=concurrency, num_requests=concurrency)

    rows = [
        {
            "arm": "A — naive",
            "stack": "FastAPI + Transformers",
            "completed": naive.completed,
            "errors": naive.errors,
            "oom": naive.oom_errors,
            "avg_ttft_ms": round(naive.avg_ttft_ms, 1),
            "p95_ttft_ms": round(naive.p95_ttft_ms, 1),
            "avg_tok_s": round(naive.avg_tokens_per_sec, 1),
        },
        {
            "arm": "B — relay",
            "stack": "RelayServe → llama.cpp ×2",
            "completed": relay.completed,
            "errors": relay.errors,
            "oom": relay.oom_errors,
            "avg_ttft_ms": round(relay.avg_ttft_ms, 1),
            "p95_ttft_ms": round(relay.p95_ttft_ms, 1),
            "avg_tok_s": round(relay.avg_tokens_per_sec, 1),
        },
    ]

    print("\n--- Comparison table (include in your submission) ---")
    print(pd.DataFrame(rows).to_markdown(index=False))
    print()
    print("While interpreting: check curl http://127.0.0.1:8080/metrics for queue_depth and queue_ms.")
    print("Those are gateway signals. Surviving the load test is mostly the engine swap.")
    print()
    _print_reflection_prompts()


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 4 — compare naive vs RelayServe + llama.cpp")
    parser.add_argument("--naive", default="http://127.0.0.1:8000/v1", help="Arm A — naive server URL")
    parser.add_argument("--relay", default="http://127.0.0.1:8080/v1", help="Arm B — RelayServe URL")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent requests (try 8)")
    args = parser.parse_args()
    asyncio.run(compare(args.naive, args.relay, args.concurrency))


if __name__ == "__main__":
    main()
