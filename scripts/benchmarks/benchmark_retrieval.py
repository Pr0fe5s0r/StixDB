#!/usr/bin/env python3
"""Benchmark vector-only vs graph-aware retrieval latency."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SDK_SRC = ROOT / "sdk" / "src"
for path in (ROOT, SDK_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from stixdb_sdk import StixDBClient  # noqa: E402


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[int(position)])
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower))


def summarize_samples(
    *,
    server_latencies_ms: list[float],
    wall_latencies_ms: list[float],
    result_counts: list[int],
    top_ids: list[list[str]],
) -> dict[str, Any]:
    return {
        "count": len(server_latencies_ms),
        "server_ms": {
            "p50": round(percentile(server_latencies_ms, 50), 2),
            "p95": round(percentile(server_latencies_ms, 95), 2),
            "mean": round(sum(server_latencies_ms) / max(1, len(server_latencies_ms)), 2),
        },
        "wall_ms": {
            "p50": round(percentile(wall_latencies_ms, 50), 2),
            "p95": round(percentile(wall_latencies_ms, 95), 2),
            "mean": round(sum(wall_latencies_ms) / max(1, len(wall_latencies_ms)), 2),
        },
        "results": {
            "min": min(result_counts) if result_counts else 0,
            "max": max(result_counts) if result_counts else 0,
            "mean": round(sum(result_counts) / max(1, len(result_counts)), 2),
        },
        "top_ids": top_ids[-1] if top_ids else [],
    }


def benchmark_mode(
    client: StixDBClient,
    *,
    collection: str,
    query: str,
    top_k: int,
    threshold: float,
    iterations: int,
    warmup: int,
    mode: str,
    graph_depth: int,
) -> dict[str, Any]:
    if mode == "vector_only":
        call = lambda: client.query.retrieve_vector_only(
            collection,
            query=query,
            top_k=top_k,
            threshold=threshold,
        )
    else:
        call = lambda: client.query.retrieve(
            collection,
            query=query,
            top_k=top_k,
            threshold=threshold,
            depth=graph_depth,
        )

    for _ in range(max(0, warmup)):
        call()

    server_latencies_ms: list[float] = []
    wall_latencies_ms: list[float] = []
    result_counts: list[int] = []
    top_ids: list[list[str]] = []

    for _ in range(iterations):
        start = perf_counter()
        response = call()
        wall_ms = (perf_counter() - start) * 1000.0
        raw_latency = response.get("latency_ms")
        server_ms = float(raw_latency) if raw_latency is not None else wall_ms
        results = response.get("results", [])

        server_latencies_ms.append(server_ms)
        wall_latencies_ms.append(wall_ms)
        result_counts.append(int(response.get("count", len(results))))
        top_ids.append([str(item.get("id") or item.get("node_id") or "") for item in results[:5]])

    return {
        "mode": mode,
        "collection": collection,
        "query": query,
        "top_k": top_k,
        "threshold": threshold,
        "iterations": iterations,
        "warmup": warmup,
        "graph_depth": graph_depth,
        "summary": summarize_samples(
            server_latencies_ms=server_latencies_ms,
            wall_latencies_ms=wall_latencies_ms,
            result_counts=result_counts,
            top_ids=top_ids,
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:4020")
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--collection", default="main")
    parser.add_argument("--query", default="StixDB retrieval benchmark")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--graph-depth", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of human-readable output.")
    return parser


def main() -> int:
    args = build_parser().parse_args()

    with StixDBClient(
        base_url=args.base_url,
        api_key=args.api_key,
        timeout=args.timeout,
    ) as client:
        vector_only = benchmark_mode(
            client,
            collection=args.collection,
            query=args.query,
            top_k=args.top_k,
            threshold=args.threshold,
            iterations=args.iterations,
            warmup=args.warmup,
            mode="vector_only",
            graph_depth=0,
        )
        graph_aware = benchmark_mode(
            client,
            collection=args.collection,
            query=args.query,
            top_k=args.top_k,
            threshold=args.threshold,
            iterations=args.iterations,
            warmup=args.warmup,
            mode=f"graph_depth_{args.graph_depth}",
            graph_depth=args.graph_depth,
        )

    payload = {
        "vector_only": vector_only,
        "graph_aware": graph_aware,
        "delta": {
            "server_ms_p50": round(
                graph_aware["summary"]["server_ms"]["p50"] - vector_only["summary"]["server_ms"]["p50"],
                2,
            ),
            "server_ms_p95": round(
                graph_aware["summary"]["server_ms"]["p95"] - vector_only["summary"]["server_ms"]["p95"],
                2,
            ),
            "wall_ms_p50": round(
                graph_aware["summary"]["wall_ms"]["p50"] - vector_only["summary"]["wall_ms"]["p50"],
                2,
            ),
            "wall_ms_p95": round(
                graph_aware["summary"]["wall_ms"]["p95"] - vector_only["summary"]["wall_ms"]["p95"],
                2,
            ),
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print("Vector-only retrieval (depth=0)")
    print(
        f"  server p50={vector_only['summary']['server_ms']['p50']}ms "
        f"p95={vector_only['summary']['server_ms']['p95']}ms "
        f"mean={vector_only['summary']['server_ms']['mean']}ms"
    )
    print(
        f"  wall   p50={vector_only['summary']['wall_ms']['p50']}ms "
        f"p95={vector_only['summary']['wall_ms']['p95']}ms "
        f"mean={vector_only['summary']['wall_ms']['mean']}ms"
    )
    print()
    print(f"Graph-aware retrieval (depth={args.graph_depth})")
    print(
        f"  server p50={graph_aware['summary']['server_ms']['p50']}ms "
        f"p95={graph_aware['summary']['server_ms']['p95']}ms "
        f"mean={graph_aware['summary']['server_ms']['mean']}ms"
    )
    print(
        f"  wall   p50={graph_aware['summary']['wall_ms']['p50']}ms "
        f"p95={graph_aware['summary']['wall_ms']['p95']}ms "
        f"mean={graph_aware['summary']['wall_ms']['mean']}ms"
    )
    print()
    print(
        "Delta (graph-aware - vector-only): "
        f"server p50={payload['delta']['server_ms_p50']}ms, "
        f"server p95={payload['delta']['server_ms_p95']}ms, "
        f"wall p50={payload['delta']['wall_ms_p50']}ms, "
        f"wall p95={payload['delta']['wall_ms_p95']}ms"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
