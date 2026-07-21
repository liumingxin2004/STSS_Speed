#!/usr/bin/env python3
"""Run checkpoint workspaces sequentially and stop on the first failure."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_STSS_DIR = Path(__file__).resolve().parents[1] / ".stss_speed" / "upstream"


def read_tsv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def write_event(events: Path, checkpoint: str, state: str, payload: dict):
    path = events / f"{stamp()}_{checkpoint}_{state}.json"
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--run-batch", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument(
        "--stss-dir",
        type=Path,
        default=DEFAULT_STSS_DIR,
        help=f"STSS source directory (default: {DEFAULT_STSS_DIR})",
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cpus-per-worker", type=int, default=5)
    parser.add_argument("--events-dir", type=Path)
    args = parser.parse_args(argv)

    checkpoints = read_tsv(args.master)
    if not checkpoints:
        raise ValueError("Checkpoint manifest is empty")
    run_root = args.master.parents[2]
    events = args.events_dir or (run_root / "work" / "stss_checkpoint_events")
    if events.exists():
        raise FileExistsError(events)
    events.mkdir(parents=True)

    analyzed_total = 0
    for row in checkpoints:
        checkpoint = row["checkpoint"]
        expected_samples = int(row["sample_count"])
        test_root = Path(row["test_root"])
        output_root = Path(row["output_root"])
        if output_root.exists():
            raise FileExistsError(output_root)
        status_path = test_root / "stss_runs" / "batch_status.tsv"
        if status_path.exists():
            raise FileExistsError(status_path)
        stdout_path = test_root / "reports" / "orchestrator.stdout.log"
        stderr_path = test_root / "reports" / "orchestrator.stderr.log"
        command = [
            str(args.python),
            str(args.run_batch),
            "--test-root",
            str(test_root),
            "--output-root",
            str(output_root),
            "--python",
            str(args.python),
            "--wrapper",
            str(args.wrapper),
            "--stss-dir",
            str(args.stss_dir),
            "--workers",
            str(args.workers),
            "--cpus-per-worker",
            str(args.cpus_per_worker),
        ]
        started = datetime.now(timezone.utc).isoformat()
        write_event(events, checkpoint, "started", {"checkpoint": checkpoint, "started_at": started, "command": command})
        print(f"{checkpoint} started", flush=True)
        with stdout_path.open("x", encoding="utf-8") as stdout_handle, stderr_path.open(
            "x", encoding="utf-8"
        ) as stderr_handle:
            completed = subprocess.run(command, stdout=stdout_handle, stderr=stderr_handle, check=False)

        statuses = read_tsv(status_path) if status_path.is_file() else []
        analyzed = sum(int(item["analyzed_genomes"]) for item in statuses) if statuses else 0
        hits = sum(int(item["self_target_hits"]) for item in statuses) if statuses else 0
        failed_workers = sum(item["exit_code"] != "0" for item in statuses)
        network_violations = sum(
            any(item[key] != "0" for key in ("entrez_requests", "cdd_network_requests", "phaster_requests", "other_http_requests"))
            for item in statuses
        )
        payload = {
            "checkpoint": checkpoint,
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "exit_code": completed.returncode,
            "status_rows": len(statuses),
            "analyzed_genomes": analyzed,
            "self_target_hits": hits,
            "failed_workers": failed_workers,
            "network_violations": network_violations,
        }
        success = (
            completed.returncode == 0
            and len(statuses) == args.workers
            and analyzed == expected_samples
            and failed_workers == 0
            and network_violations == 0
        )
        write_event(events, checkpoint, "completed" if success else "failed", payload)
        print(
            f"{checkpoint} exit={completed.returncode} analyzed={analyzed} hits={hits} "
            f"failed_workers={failed_workers} network_violations={network_violations}",
            flush=True,
        )
        if not success:
            return 1
        analyzed_total += analyzed

    print(f"all_checkpoints_completed={len(checkpoints)} analyzed_genomes={analyzed_total}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
