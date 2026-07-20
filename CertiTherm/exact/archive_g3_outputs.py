#!/usr/bin/env python3
"""Archive external G3 output JSON files into a content-bound repository folder."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = Path("/tmp/certitherm_g3_real_outputs")
DEFAULT_ARCHIVE_ROOT = REPO_ROOT / "CertiTherm" / "evidence" / "g3_2x2x2_real_archive"

FILES = [
    "g3_suite_artifact.json",
    "g3_suite_receipt.json",
    "g3_case_query_artifact_receipts.json",
    "g3_case_matrix_index.json",
    "g3_independent_hotspot_witness_replay.json",
    "g3_independent_dual_backend_replay.json",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive G3 output files from /tmp into repository")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    archive_root = args.archive_root.resolve()
    archive_root.mkdir(parents=True, exist_ok=True)

    manifest_files = []
    for name in FILES:
        src = output_root / name
        if not src.is_file():
            raise SystemExit(f"missing output file: {src}")
        dst = archive_root / name
        shutil.copy2(src, dst)
        manifest_files.append(
            {
                "path": name,
                "sha256": _sha256(dst),
                "size_bytes": dst.stat().st_size,
            }
        )

    manifest = {
        "schema_version": "certitherm.g3-output-archive.v1",
        "source_output_root": str(output_root),
        "repository_commit": _git_commit(REPO_ROOT),
        "files": manifest_files,
    }
    _write_json(archive_root / "manifest.json", manifest)
    print(f"Archived {len(manifest_files)} files to {archive_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
