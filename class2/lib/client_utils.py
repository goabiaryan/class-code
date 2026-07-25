from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx
from openai import OpenAI


DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://127.0.0.1:8000/v1")
DEFAULT_API_KEY = os.environ.get("OPENAI_API_KEY", "local-dev-key")
DEFAULT_MODEL = os.environ.get("MODEL_ID", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")


def make_client(base_url: str = DEFAULT_BASE_URL, api_key: str = DEFAULT_API_KEY) -> OpenAI:
    return OpenAI(base_url=base_url, api_key=api_key)


@dataclass
class TimingResult:
    request_id: str
    stream: bool
    ttft_ms: float
    total_ms: float
    completion_tokens: int
    prompt_tokens: int
    tokens_per_sec: float
    error: Optional[str] = None
    status_code: Optional[int] = None


def timed_chat_completion(
    client: OpenAI,
    messages: List[Dict[str, str]],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 64,
    stream: bool = False,
    temperature: float = 0.7,
) -> TimingResult:
    t0 = time.perf_counter()
    ttft_ms: Optional[float] = None
    completion_tokens = 0
    prompt_tokens = 0
    request_id = ""

    if stream:
        first = True
        stream_resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for event in stream_resp:
            if first and (event.choices[0].delta.content or event.choices[0].delta.role):
                ttft_ms = (time.perf_counter() - t0) * 1000
                first = False
            if event.choices[0].delta.content:
                completion_tokens += 1
            if event.id:
                request_id = event.id
        total_ms = (time.perf_counter() - t0) * 1000
    else:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        total_ms = (time.perf_counter() - t0) * 1000
        request_id = resp.id
        if resp.usage:
            prompt_tokens = resp.usage.prompt_tokens or 0
            completion_tokens = resp.usage.completion_tokens or 0

    total_s = max(total_ms / 1000, 1e-6)
    return TimingResult(
        request_id=request_id,
        stream=stream,
        ttft_ms=ttft_ms,
        total_ms=total_ms,
        completion_tokens=completion_tokens,
        prompt_tokens=prompt_tokens,
        tokens_per_sec=completion_tokens / total_s,
    )


async def fetch_metrics(base_url: str) -> Dict[str, Any]:
    """Fetch /metrics from naive server or RelayServe (strip /v1 suffix if present)."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3]
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{root}/metrics")
        resp.raise_for_status()
        return resp.json()


def print_timing(label: str, result: TimingResult) -> None:
    status = result.error or "ok"
    if result.stream and result.ttft_ms is not None:
        print(
            f"[{label}] stream={result.stream} ttft_ms={result.ttft_ms:.1f} "
            f"total_ms={result.total_ms:.1f} tok/s={result.tokens_per_sec:.1f} status={status}"
        )
    else:
        print(
            f"[{label}] stream={result.stream} total_ms={result.total_ms:.1f} "
            f"(ttft_ms not measured — non-streaming) "
            f"tok/s={result.tokens_per_sec:.1f} status={status}"
        )


def long_context_prompt(target_tokens: int = 1500) -> str:
    """Repeat a paragraph until we approximate target token count."""
    paragraph = (
        "In transformer inference, prefill processes the entire prompt in parallel while "
        "decode generates one token at a time and stores key-value activations in a cache. "
        "Under concurrent load, each in-flight request retains its own KV cache, which is "
        "why memory grows with concurrency even when GPU utilization looks low. "
    )
    text = paragraph
    while len(text.split()) < target_tokens:
        text += paragraph
    return text[: target_tokens * 6]  # rough char cap


def dump_sse_line(raw_line: str) -> None:
    if raw_line.startswith("data: ") and raw_line.strip() != "data: [DONE]":
        payload = json.loads(raw_line.removeprefix("data: ").strip())
        delta = payload.get("choices", [{}])[0].get("delta", {})
        content = delta.get("content")
        if content:
            print(content, end="", flush=True)
