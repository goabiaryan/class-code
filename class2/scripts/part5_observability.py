from __future__ import annotations

import argparse
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fmt_ms(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.0f}ms"


async def poll_metrics(url: str, interval: float, count: int) -> None:
    root = url.rstrip("/")
    print(f"Polling {root}/metrics every {interval}s ({count} samples)")
    print("Press Ctrl+C to stop early.\n")

    async with httpx.AsyncClient(timeout=5) as client:
        for i in range(count):
            try:
                resp = await client.get(f"{root}/metrics")
                data = resp.json()
                if "stats" in data:
                    stats = data["stats"]
                    print(
                        f"[{i+1}] queue_depth={data.get('queue_depth')} "
                        f"requests={stats.get('count')} "
                        f"avg_ttft={_fmt_ms(stats.get('avg_ttft_ms'))} "
                        f"avg_queue={stats.get('avg_queue_ms', 0):.0f}ms "
                        f"kv={data.get('kv')}"
                    )
                else:
                    print(
                        f"[{i+1}] active={data.get('active_requests')} "
                        f"avg_ttft={_fmt_ms(data.get('avg_ttft_ms'))} "
                        f"p95_ttft={_fmt_ms(data.get('p95_ttft_ms'))} "
                        f"avg_total={_fmt_ms(data.get('avg_total_ms'))} "
                        f"p95_total={_fmt_ms(data.get('p95_total_ms'))} "
                        f"tok/s={data.get('avg_tokens_per_sec', 0):.1f} "
                        f"gpu={data.get('gpu')}"
                    )
            except Exception as exc:
                print(f"[{i+1}] could not reach server: {exc}")
            await asyncio.sleep(interval)

    print("\nDone. Paste a few peak-load samples into your submission.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Part 5 — poll /metrics")
    parser.add_argument(
        "--url",
        default=os.environ.get("METRICS_URL", "http://127.0.0.1:8000"),
        help="Server root URL (no /v1 suffix)",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds between polls")
    parser.add_argument("--count", type=int, default=30, help="Number of samples")
    args = parser.parse_args()
    asyncio.run(poll_metrics(args.url, args.interval, args.count))


if __name__ == "__main__":
    main()
