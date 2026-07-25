
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.client_utils import DEFAULT_BASE_URL, make_client, print_timing, timed_chat_completion


def main() -> None:
    base_url = os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL)
    client = make_client(base_url)
    messages = [{"role": "user", "content": "What is KV cache in LLM inference? Answer in 2 sentences."}]

    print("Part 1 — Anatomy of an LLM call")
    print(f"Endpoint: {base_url}\n")

    print("Run 1: non-streaming (wait for the full response)")
    non_stream = timed_chat_completion(client, messages, stream=False, max_tokens=48)
    print_timing("non-stream", non_stream)
    print()

    print("Run 2: streaming (tokens arrive one at a time)")
    stream = timed_chat_completion(client, messages, stream=True, max_tokens=48)
    print()
    print_timing("stream", stream)
    print()

    print("Compare the two runs:")
    print(f"  Non-stream total_ms: {non_stream.total_ms:.0f} ms (ttft_ms not measured)")
    print(f"  Stream ttft_ms:      {stream.ttft_ms:.0f} ms")
    print(f"  Stream total_ms:     {stream.total_ms:.0f} ms")
    print()
    print("Look for:")
    print("  • Non-streaming: only total_ms — no separate ttft_ms.")
    print("  • Streaming: ttft_ms is much lower than total_ms.")
    print("  • The gap between ttft_ms and total_ms is mostly decode.")
    print()
    print("Write down: Which number would a user care about most? (ttft_ms vs total_ms)")


if __name__ == "__main__":
    main()
