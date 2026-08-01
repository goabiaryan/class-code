from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import httpx

from lib.client_utils import DEFAULT_BASE_URL, DEFAULT_MODEL, fetch_metrics, long_context_prompt


@dataclass
class LoadResult:
    concurrency: int
    completed: int
    errors: int
    oom_errors: int
    avg_ttft_ms: float
    p95_ttft_ms: float
    avg_total_ms: float
    avg_tokens_per_sec: float
    wall_ms: float
    metrics_snapshot: Optional[Dict[str, Any]] = None


async def _one_request(
    client: httpx.AsyncClient,
    base_url: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    sem: asyncio.Semaphore,
) -> Dict[str, Any]:
    import re
    # Expresión regular para eliminar códigos de escape ANSI (colores y estilos)
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')

    async with sem:
        t0 = time.perf_counter()
        ttft_ms = 0.0
        try:
            async with client.stream(
                "POST",
                f"{base_url.rstrip('/')}/chat/completions",
                json={
                    "model": DEFAULT_MODEL,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "stream": True,
                    "temperature": 0.7,
                },
                headers= {} if 'litellm' not in base_url else {'x-litellm-api-key': 'Bearer sk-class2-demo'}
                ,
                timeout=120,
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    return {
                        "ok": False,
                        "status": resp.status_code,
                        "error": ansi_escape.sub('', body.decode(errors="replace"))[:200],
                        "ttft_ms": 0,
                        "total_ms": (time.perf_counter() - t0) * 1000,
                        "tokens": 0,
                    }
                
                tokens = 0
                first = True
                full_content = ''
                
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    
                    # Limpiar códigos ANSI de la línea entrante
                    clean_line = ansi_escape.sub('', line)

                    # Si es una línea SSE estándar
                    if clean_line.startswith("data:"):
                        payload = clean_line.removeprefix("data:").strip()
                        if payload == "[DONE]":
                            break
                        # Si trae contenido válido o JSON de chunks, puedes procesarlo aquí.
                        # Asumimos incremento de tokens por cada chunk recibido si no se parsea JSON complejo
                    else:
                        # Caso para líneas que no empiezan con "data:" (texto plano o logs del servidor)
                        full_content += clean_line

                    # Registrar TTFT al recibir el primer contenido útil
                    if first:
                        ttft_ms = (time.perf_counter() - t0) * 1000
                        first = False
                    
                    tokens += 1

                total_ms = (time.perf_counter() - t0) * 1000
                tps = tokens / max(total_ms / 1000, 1e-6)
      
                return {
                    "ok": True,
                    "status": resp.status_code,
                    "ttft_ms": ttft_ms,
                    "total_ms": total_ms,
                    "tokens": tokens,
                    "tokens_per_sec": tps,
                }
        except Exception as exc:
            msg = str(exc)
            return {
                "ok": False,
                "status": None,
                "error": msg,
                "oom": "out of memory" in msg.lower() or "oom" in msg.lower(),
                "ttft_ms": 0,
                "total_ms": (time.perf_counter() - t0) * 1000,
                "tokens": 0,
            }


async def run_load_test(
    *,
    base_url: str = DEFAULT_BASE_URL,
    concurrency: int = 8,
    num_requests: Optional[int] = None,
    max_tokens: int = 64,
    long_context: bool = False,
    context_tokens: int = 1500,
) -> LoadResult:
    num_requests = num_requests or concurrency
    if long_context:
        prompt = long_context_prompt(context_tokens)
        messages = [{"role": "user", "content": prompt}]
    else:
        messages = [{"role": "user", "content": "Explain KV cache in one paragraph."}]

    sem = asyncio.Semaphore(concurrency)
    t_wall = time.perf_counter()
    async with httpx.AsyncClient() as client:
        tasks = [
            _one_request(client, base_url, messages, max_tokens, sem)
            for _ in range(num_requests)
        ]
        results = await asyncio.gather(*tasks)
        metrics_snapshot = None
        try:
            metrics_snapshot = await fetch_metrics(base_url)
        except Exception:
            pass

    ok = [r for r in results if r.get("ok")]
    errors = [r for r in results if not r.get("ok")]
    ttfts = [r["ttft_ms"] for r in ok if r["ttft_ms"] > 0]
    totals = [r["total_ms"] for r in ok]
    tps_vals = [r.get("tokens_per_sec", 0) for r in ok]

    return LoadResult(
        concurrency=concurrency,
        completed=len(ok),
        errors=len(errors),
        oom_errors=sum(1 for r in errors if r.get("oom") or r.get("status") == 503),
        avg_ttft_ms=statistics.mean(ttfts) if ttfts else 0.0,
        p95_ttft_ms=_p95(ttfts),
        avg_total_ms=statistics.mean(totals) if totals else 0.0,
        avg_tokens_per_sec=statistics.mean(tps_vals) if tps_vals else 0.0,
        wall_ms=(time.perf_counter() - t_wall) * 1000,
        metrics_snapshot=metrics_snapshot,
    )


def _p95(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return ordered[idx]


def print_load_result(label: str, result: LoadResult) -> None:
    print(f"\n=== {label} ===")
    print(f"concurrency={result.concurrency} completed={result.completed} errors={result.errors} oom={result.oom_errors}")
    print(
        f"avg_ttft={result.avg_ttft_ms:.1f}ms p95_ttft={result.p95_ttft_ms:.1f}ms "
        f"avg_total={result.avg_total_ms:.1f}ms tok/s={result.avg_tokens_per_sec:.1f} wall={result.wall_ms:.0f}ms"
    )
    if result.metrics_snapshot:
        gpu = result.metrics_snapshot.get("gpu") or result.metrics_snapshot.get("kv")
        active = result.metrics_snapshot.get("active_requests", result.metrics_snapshot.get("queue_depth"))
        print(f"metrics: active/queue={active} gpu/kv={gpu}")


async def sweep_concurrency(
    base_url: str,
    levels: List[int],
    *,
    long_context: bool = False,
) -> List[LoadResult]:
    results: List[LoadResult] = []
    for level in levels:
        result = await run_load_test(
            base_url=base_url,
            concurrency=level,
            num_requests=level,
            long_context=long_context,
        )
        print_load_result(f"concurrency={level}", result)
        results.append(result)
        if result.oom_errors or result.errors >= level // 2:
            print(f"Stopping at concurrency={level} — too many errors or OOM.")
            break
        await asyncio.sleep(2)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test an inference server")
    parser.add_argument("--base-url", default=os.environ.get("TARGET_URL", DEFAULT_BASE_URL))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("CONCURRENCY", "8")))
    parser.add_argument("--long-context", action="store_true")
    parser.add_argument("--sweep", action="store_true", help="Run 4→8→16→32 sweep")
    args = parser.parse_args()

    if args.sweep:
        asyncio.run(sweep_concurrency(args.base_url, [4, 8, 16, 32], long_context=args.long_context))
    else:
        result = asyncio.run(
            run_load_test(base_url=args.base_url, concurrency=args.concurrency, long_context=args.long_context)
        )
        print_load_result("load test", result)


if __name__ == "__main__":
    main()
