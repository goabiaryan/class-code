
from __future__ import annotations

import argparse
import asyncio
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.client_utils import DEFAULT_BASE_URL
from lib.load_test import LoadResult, print_load_result, run_load_test, sweep_concurrency


def _row(phase: str, result: LoadResult) -> dict:
    return {
        "phase": phase,
        "concurrency": result.concurrency,
        "completed": result.completed,
        "errors": result.errors,
        "oom": result.oom_errors,
        "avg_ttft_ms": round(result.avg_ttft_ms, 1),
        "p95_ttft_ms": round(result.p95_ttft_ms, 1),
        "avg_tok_s": round(result.avg_tokens_per_sec, 1),
    }


async def main_async(base_url: str, *, sweep_only: bool) -> None:
    rows = []

    print("Part 3 — Break the server")
    print(f"Target: {base_url}\n")

    if not sweep_only:
        print("Step 1/3 — Baseline (1 request, normal prompt)")
        baseline = await run_load_test(base_url=base_url, concurrency=1, num_requests=1)
        print_load_result("baseline", baseline)
        rows.append(_row("baseline", baseline))

        print("\nStep 2/3 — Long context (1 request, ~1500 tokens)")
        long_ctx = await run_load_test(
            base_url=base_url, concurrency=1, num_requests=1, long_context=True
        )
        print_load_result("long-context", long_ctx)
        rows.append(_row("long-context", long_ctx))

        print("\nStep 3/3 — Concurrency sweep (4 → 8 → 16 → 32)")
        print("Start part5_observability.py now if you have not already.\n")
    else:
        print("Concurrency sweep only (4 → 8 → 16 → 32)\n")

    sweep = await sweep_concurrency(base_url, [4, 8, 16, 32])
    for level, result in zip([4, 8, 16, 32][: len(sweep)], sweep):
        rows.append(_row(f"conc-{level}", result))

    df = pd.DataFrame(rows)
    print("\n--- Your results (save this table) ---")
    print(df.to_markdown(index=False))
    print()
    print("Also capture (during the sweep, while part5_observability.py is polling):")
    print("  • Screenshot of /metrics with active_requests > 0")
    print("  • nvidia-smi showing GPU memory climbing")
    print()
    print("Questions to answer:")
    print("  1. At what concurrency did TTFT spike or errors appear?")
    print("  2. Did GPU memory keep climbing even if utilization stayed low?")
    print("  3. What failed first — latency or OOM?")


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 3 — break the naive server")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("TARGET_URL", DEFAULT_BASE_URL),
        help="OpenAI-compatible base URL (default: http://127.0.0.1:8000/v1)",
    )
    parser.add_argument(
        "--sweep-only",
        action="store_true",
        help="Skip baseline + long-context single requests; run concurrency sweep only",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args.base_url, sweep_only=args.sweep_only))


if __name__ == "__main__":
    main()
