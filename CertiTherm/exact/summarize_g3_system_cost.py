#!/usr/bin/env python3
"""Summarize runtime/RSS/certificate size from a G3 suite artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize system cost from G3 artifact")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    artifact = _load(args.artifact.resolve())
    entries = artifact.get("entries", [])
    rows = []
    wall_times = []
    rss_values = []
    cert_sizes = []
    for entry in entries:
        query_id = entry["query_id"]
        for variant, record in entry["variants"].items():
            run = record.get("run", {})
            result = record.get("result", {})
            wall = float(run.get("wall_time_s", 0.0))
            rss = int(run.get("peak_rss_kb", 0))
            cert_size = len(json.dumps(result, separators=(",", ":"), sort_keys=True).encode("utf-8"))
            wall_times.append(wall)
            rss_values.append(rss)
            cert_sizes.append(cert_size)
            rows.append(
                {
                    "query_id": query_id,
                    "variant": variant,
                    "status": result.get("status"),
                    "wall_time_s": wall,
                    "peak_rss_kb": rss,
                    "certificate_size_bytes": cert_size,
                }
            )

    summary = {
        "schema_version": "certitherm.g3-system-cost-summary.v1",
        "artifact_path": str(args.artifact.resolve()),
        "variant_count": len(rows),
        "wall_time_s": {
            "min": min(wall_times) if wall_times else 0.0,
            "max": max(wall_times) if wall_times else 0.0,
            "avg": (sum(wall_times) / len(wall_times)) if wall_times else 0.0,
            "total": sum(wall_times),
        },
        "peak_rss_kb": {
            "min": min(rss_values) if rss_values else 0,
            "max": max(rss_values) if rss_values else 0,
            "avg": (sum(rss_values) / len(rss_values)) if rss_values else 0.0,
        },
        "certificate_size_bytes": {
            "min": min(cert_sizes) if cert_sizes else 0,
            "max": max(cert_sizes) if cert_sizes else 0,
            "avg": (sum(cert_sizes) / len(cert_sizes)) if cert_sizes else 0.0,
        },
        "rows": rows,
    }
    _write(args.output.resolve(), summary)
    print(f"Wrote system cost summary: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
