#!/usr/bin/env python3
"""Read-only health probe for download, cache-split, or STSS phases."""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


def processes():
    tokens = ("datasets download", "datasets rehydrate", "split_gbff.py", "run_batch.py", "offline_stss_wrapper")
    rows = []
    for cmdline in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            command = cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace").strip()
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
        if any(token in command for token in tokens):
            rows.append({"pid": int(cmdline.parent.name), "command": command})
    return sorted(rows, key=lambda row: row["pid"])


def error_logs(root: Path, limit=8):
    rows = []
    for path in sorted(root.rglob("*.stderr.log")):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            continue
        if not size:
            continue
        with path.open("rb") as handle:
            handle.seek(max(0, size - 1200))
            tail = handle.read().decode("utf-8", errors="replace").strip()
        rows.append({"path": str(path), "bytes": size, "tail": tail})
    return rows[-limit:]


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--phase", choices=("download", "split", "stss"), required=True)
    args = parser.parse_args(argv)
    disk = shutil.disk_usage(args.test_root)
    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "phase": args.phase,
        "load_average": Path("/proc/loadavg").read_text(encoding="utf-8").split()[:3],
        "disk_free_bytes": disk.free,
        "active_processes": processes(),
    }
    if args.phase == "download":
        payload.update(
            {
                "job_directories": len(list((args.test_root / "download" / "jobs").glob("batch_*"))),
                "gbff_files": len(list(args.test_root.rglob("*.gbff"))),
                "status_exists": (args.test_root / "download" / "download_status.tsv").is_file(),
                "nonempty_error_logs": error_logs(args.test_root / "download"),
            }
        )
    elif args.phase == "split":
        payload.update(
            {
                "gbff_files": len(list(args.test_root.rglob("*.gbff"))),
                "published_gb_files": len(list((args.test_root / "cache" / "shared_GenBank_files").glob("*.gb"))),
                "cache_manifest_exists": (args.test_root / "cache" / "cache_manifest.tsv").is_file(),
                "coverage_summary_exists": (args.test_root / "cache" / "cache_coverage_summary.tsv").is_file(),
            }
        )
    else:
        payload.update(
            {
                "worker_stdout_logs": len(list((args.test_root / "stss_runs" / "logs").glob("*.stdout.log"))),
                "worker_stderr_logs": len(list((args.test_root / "stss_runs" / "logs").glob("*.stderr.log"))),
                "nonempty_error_logs": error_logs(args.test_root / "stss_runs" / "logs"),
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
