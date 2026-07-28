
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.client_utils import make_client, print_timing, timed_chat_completion


def main() -> None:
    base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000/v1")
    client = make_client(base_url, 'Bearer sk-class2-demo')
    messages = [{"role": "user", "content": "In one sentence: what does an inference gateway do?"}]

    print("Part 6 — LiteLLM gateway (optional)")
    print(f"Endpoint: {base_url}\n")

    result = timed_chat_completion(client, messages, model="naive-local", stream=True, max_tokens=32)
    print()
    print_timing("litellm → naive server", result)
    print()
    print("You've now seen three layers:")
    print("  Part 2–3: naive server (engine + server in one process)")
    print("  Part 4:   RelayServe → llama.cpp (minimal gateway + real engine)")
    print("  Part 6:   LiteLLM → naive server (full-featured gateway)")
    print()
    print("Optional reflection: What would LiteLLM give you that RelayServe doesn't?")


if __name__ == "__main__":
    main()
