from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, List, Optional

import torch
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer, TextIteratorStreamer

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MODEL_ID = os.environ.get("MODEL_ID", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
HOST = os.environ.get("NAIVE_SERVER_HOST", "0.0.0.0")
PORT = int(os.environ.get("NAIVE_SERVER_PORT", "8000"))
TORCH_DTYPE = os.environ.get("TORCH_DTYPE", "auto")
FORCE_CPU = os.environ.get("FORCE_CPU", "0") == "1"
MAX_NEW_TOKENS_DEFAULT = int(os.environ.get("MAX_NEW_TOKENS", "64"))


def resolve_device() -> torch.device:
    if FORCE_CPU:
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Metrics (simple in-process collector — Part 5 extends this)
# ---------------------------------------------------------------------------

@dataclass
class RequestRecord:
    request_id: str
    total_ms: float
    prompt_tokens: int
    completion_tokens: int
    tokens_per_sec: float
    stream: bool
    ttft_ms: Optional[float] = None  # streaming only — time to first output token
    error: Optional[str] = None


@dataclass
class ServerMetrics:
    active_requests: int = 0
    total_requests: int = 0
    total_errors: int = 0
    recent: Deque[RequestRecord] = field(default_factory=lambda: deque(maxlen=200))

    def snapshot(self) -> Dict[str, Any]:
        records = list(self.recent)
        ok = [r for r in records if r.error is None]
        ttfts = [r.ttft_ms for r in ok if r.stream and r.ttft_ms is not None]
        totals = [r.total_ms for r in ok]
        tps = [r.tokens_per_sec for r in ok if r.completion_tokens > 0]
        return {
            "active_requests": self.active_requests,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "recent_count": len(records),
            "avg_ttft_ms": sum(ttfts) / len(ttfts) if ttfts else None,
            "p95_ttft_ms": _percentile(ttfts, 95) if ttfts else None,
            "avg_total_ms": sum(totals) / len(totals) if totals else 0.0,
            "p95_total_ms": _percentile(totals, 95) if totals else 0.0,
            "avg_tokens_per_sec": sum(tps) / len(tps) if tps else 0.0,
            "gpu": gpu_memory_snapshot(),
        }


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * pct / 100))
    return ordered[idx]


def gpu_memory_snapshot() -> Dict[str, Any]:
    if not torch.cuda.is_available():
        return {"available": False}
    return {
        "available": True,
        "allocated_mb": torch.cuda.memory_allocated() / (1024 ** 2),
        "reserved_mb": torch.cuda.memory_reserved() / (1024 ** 2),
        "max_allocated_mb": torch.cuda.max_memory_allocated() / (1024 ** 2),
    }


METRICS = ServerMetrics()
METRICS_LOCK = threading.Lock()
MODEL_LOCK = threading.Lock()  # serializes generate — still bad; we expose the lock for teaching


def _log_record(record: RequestRecord) -> None:
    ttft = "n/a" if record.ttft_ms is None else f"{record.ttft_ms:.1f}"
    err = f" error={record.error}" if record.error else ""
    print(
        f"[naive-server] {record.request_id} stream={record.stream} "
        f"ttft_ms={ttft} total_ms={record.total_ms:.1f} "
        f"tok/s={record.tokens_per_sec:.1f}{err}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Model holder
# ---------------------------------------------------------------------------

class ModelBundle:
    def __init__(self) -> None:
        self.device = resolve_device()
        self.model_id = MODEL_ID
        self.tokenizer: Optional[Any] = None
        self.model: Optional[Any] = None

    def load(self) -> None:
        if TORCH_DTYPE == "auto":
            load_kwargs = {"dtype": "auto"}
        else:
            dtype = getattr(torch, TORCH_DTYPE, None)
            if dtype is None:
                raise ValueError(f"TORCH_DTYPE inválido o no soportado por torch: {TORCH_DTYPE}")
            load_kwargs = {"dtype": dtype}

        print(f"[naive-server] Loading {self.model_id} on {self.device} dtype={TORCH_DTYPE}")
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token
            
        try:
            self.model = AutoModelForCausalLM.from_pretrained(self.model_id, **load_kwargs)
            self.model.to(self.device)
            self.model.eval()
        except Exception as e:
            raise RuntimeError(f"Error cargando el modelo con torch_dtype={TORCH_DTYPE} en dispositivo {self.device}: {e}")
            
        print(f"[naive-server] Ready. GPU mem: {gpu_memory_snapshot()}")


BUNDLE = ModelBundle()


# ---------------------------------------------------------------------------
# OpenAI-shaped request models
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = Field(default=MODEL_ID)
    messages: List[ChatMessage]
    max_tokens: Optional[int] = Field(default=None, alias="max_tokens")
    temperature: float = 0.7
    stream: bool = False


def messages_to_prompt(messages: List[ChatMessage]) -> str:
    """Minimal chat template — good enough for TinyLlama / Phi-2 demos."""
    parts: List[str] = []
    for msg in messages:
        role = msg.role.lower()
        if role == "system":
            parts.append(f"<|system|>\n{msg.content}</s>")
        elif role == "assistant":
            parts.append(f"<|assistant|>\n{msg.content}</s>")
        else:
            parts.append(f"<|user|>\n{msg.content}</s>")
    parts.append("<|assistant|>\n")
    return "\n".join(parts)


def count_tokens(text: str) -> int:
    assert BUNDLE.tokenizer is not None
    return len(BUNDLE.tokenizer.encode(text, add_special_tokens=False))


def run_generate(
    prompt: str,
    max_new_tokens: int,
    temperature: float,
    stream: bool,
) -> tuple[str, Optional[float], float, int]:
    assert BUNDLE.model is not None and BUNDLE.tokenizer is not None
    inputs = BUNDLE.tokenizer(prompt, return_tensors="pt").to(BUNDLE.device)
    prompt_len = inputs["input_ids"].shape[-1]

    gen_kwargs = {
        "max_new_tokens": max_new_tokens,
        "do_sample": temperature > 0,
        "temperature": max(temperature, 1e-5),
        "pad_token_id": BUNDLE.tokenizer.pad_token_id,
        "eos_token_id": BUNDLE.tokenizer.eos_token_id,
    }

    t0 = time.perf_counter()
    ttft_ms = 0.0

    if stream:
        streamer = TextIteratorStreamer(BUNDLE.tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs["streamer"] = streamer

        def _generate() -> None:
            with MODEL_LOCK, torch.inference_mode():
                BUNDLE.model.generate(**inputs, **gen_kwargs)

        thread = threading.Thread(target=_generate, daemon=True)
        thread.start()
        chunks: List[str] = []
        first = True
        for piece in streamer:
            if first:
                ttft_ms = (time.perf_counter() - t0) * 1000
                first = False
            chunks.append(piece)
        thread.join()
        text = "".join(chunks)
    else:
        with MODEL_LOCK, torch.inference_mode():
            outputs = BUNDLE.model.generate(**inputs, **gen_kwargs)
        new_tokens = outputs[0][prompt_len:]
        text = BUNDLE.tokenizer.decode(new_tokens, skip_special_tokens=True)
        ttft_ms = None

    total_ms = (time.perf_counter() - t0) * 1000
    completion_tokens = max(1, count_tokens(text))
    return text, ttft_ms, total_ms, completion_tokens


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start model load in background so /healthz responds during Modal cold start."""
    threading.Thread(target=BUNDLE.load, daemon=True).start()
    yield


app = FastAPI(
    title="Naive Inference Server",
    description="Intentionally minimal — no batching, no queue, no backpressure.",
    lifespan=lifespan,
)


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    if BUNDLE.model is None:
        return {"status": "loading", "model": BUNDLE.model_id}
    return {"status": "ok", "model": BUNDLE.model_id}


@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": BUNDLE.model_id, "object": "model", "owned_by": "naive-server"}],
    }


@app.get("/metrics")
async def metrics() -> JSONResponse:
    with METRICS_LOCK:
        body = METRICS.snapshot()
    body["server"] = "naive"
    body["model_id"] = BUNDLE.model_id
    body["device"] = str(BUNDLE.device)
    return JSONResponse(body)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Any:
    try:
        payload = await request.json()
        req = ChatCompletionRequest.model_validate(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    request_id = request.headers.get("X-Request-ID") or f"chatcmpl-{uuid.uuid4().hex[:12]}"
    prompt = messages_to_prompt(req.messages)
    max_new = req.max_tokens or MAX_NEW_TOKENS_DEFAULT

    with METRICS_LOCK:
        METRICS.active_requests += 1
        METRICS.total_requests += 1

    started = time.perf_counter()
    try:
        if BUNDLE.model is None:
            await asyncio.to_thread(BUNDLE.load)

        if req.stream:
            # active_requests decremented when the stream finishes
            return StreamingResponse(
                _stream_response(request_id, prompt, max_new, req.temperature),
                media_type="text/event-stream",
            )

        # Naive pattern: blocking generate inside async route (blocks event loop)
        text, ttft_ms, total_ms, completion_tokens = await asyncio.to_thread(
            run_generate, prompt, max_new, req.temperature, False
        )
        tokens_per_sec = completion_tokens / max(total_ms / 1000, 1e-6)

        record = RequestRecord(
            request_id=request_id,
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            prompt_tokens=count_tokens(prompt),
            completion_tokens=completion_tokens,
            tokens_per_sec=tokens_per_sec,
            stream=False,
        )
        with METRICS_LOCK:
            METRICS.recent.append(record)
        _log_record(record)

        return {
            "id": request_id,
            "object": "chat.completion",
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": record.prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": record.prompt_tokens + completion_tokens,
            },
            "metrics": {
                "ttft_ms": ttft_ms,
                "total_ms": total_ms,
                "tokens_per_sec": tokens_per_sec,
            },
        }
    except torch.cuda.OutOfMemoryError as exc:
        with METRICS_LOCK:
            METRICS.total_errors += 1
            METRICS.recent.append(
                RequestRecord(
                    request_id=request_id,
                    ttft_ms=None,
                    total_ms=(time.perf_counter() - started) * 1000,
                    prompt_tokens=count_tokens(prompt),
                    completion_tokens=0,
                    tokens_per_sec=0,
                    stream=req.stream,
                    error="CUDA OOM",
                )
            )
        raise HTTPException(status_code=503, detail="CUDA out of memory") from exc
    except Exception as exc:
        with METRICS_LOCK:
            METRICS.total_errors += 1
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if not req.stream:
            with METRICS_LOCK:
                METRICS.active_requests = max(0, METRICS.active_requests - 1)


async def _stream_response(
    request_id: str,
    prompt: str,
    max_new_tokens: int,
    temperature: float,
) -> AsyncIterator[str]:
    assert BUNDLE.model is not None and BUNDLE.tokenizer is not None
    inputs = BUNDLE.tokenizer(prompt, return_tensors="pt").to(BUNDLE.device)
    streamer = TextIteratorStreamer(BUNDLE.tokenizer, skip_prompt=True, skip_special_tokens=True)
    gen_kwargs = {
        "max_new_tokens": max_new_tokens,
        "do_sample": temperature > 0,
        "temperature": max(temperature, 1e-5),
        "pad_token_id": BUNDLE.tokenizer.pad_token_id,
        "eos_token_id": BUNDLE.tokenizer.eos_token_id,
        "streamer": streamer,
    }

    def _generate() -> None:
        with MODEL_LOCK, torch.inference_mode():
            BUNDLE.model.generate(**inputs, **gen_kwargs)

    t0 = time.perf_counter()
    thread = threading.Thread(target=_generate, daemon=True)
    thread.start()

    first = True
    completion_tokens = 0
    ttft_ms = 0.0
    try:
        for piece in streamer:
            if first:
                ttft_ms = (time.perf_counter() - t0) * 1000
                first = False
            completion_tokens += 1
            chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "model": BUNDLE.model_id,
                "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        thread.join()
        total_ms = (time.perf_counter() - t0) * 1000
        record = RequestRecord(
            request_id=request_id,
            ttft_ms=ttft_ms,
            total_ms=total_ms,
            prompt_tokens=count_tokens(prompt),
            completion_tokens=completion_tokens,
            tokens_per_sec=completion_tokens / max(total_ms / 1000, 1e-6),
            stream=True,
        )
        with METRICS_LOCK:
            METRICS.recent.append(record)
            METRICS.active_requests = max(0, METRICS.active_requests - 1)
        _log_record(record)


def main() -> None:
    uvicorn.run(
        "naive_server.server:app",
        host=HOST,
        port=PORT,
        log_level="info",
        workers=1,  # intentional: multiple workers would duplicate model weights
    )


if __name__ == "__main__":
    main()
