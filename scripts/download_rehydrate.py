#!/usr/bin/env python3
"""Download dehydrated GBFF packages and rehydrate them with bounded concurrency."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def run_logged(command, cwd: Path, stdout_path: Path, stderr_path: Path):
    with stdout_path.open("x", encoding="utf-8") as stdout_handle, stderr_path.open(
        "x", encoding="utf-8"
    ) as stderr_handle:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=stdout_handle,
            stderr=stderr_handle,
            check=False,
            env=os.environ.copy(),
        )
    return completed.returncode


def extract_new(zip_path: Path, output_dir: Path):
    output_dir.mkdir()
    with zipfile.ZipFile(zip_path) as archive:
        root = output_dir.resolve()
        for member in archive.infolist():
            destination = (output_dir / member.filename).resolve()
            if root not in destination.parents and destination != root:
                raise ValueError(f"Unsafe zip member: {member.filename}")
        archive.extractall(output_dir)


def process_batch(batch_file: Path, jobs_dir: Path, datasets: Path, rehydrate_workers: int):
    batch_id = batch_file.stem
    requested_accessions = sum(1 for line in batch_file.read_text(encoding="utf-8").splitlines() if line.strip())
    job_dir = jobs_dir / batch_id
    job_dir.mkdir()
    started = utc_now()
    started_clock = time.perf_counter()
    zip_path = job_dir / f"{batch_id}_dehydrated.zip"
    extracted_dir = job_dir / "dehydrated_package"

    download_command = [
        str(datasets),
        "download",
        "genome",
        "accession",
        "--inputfile",
        str(batch_file),
        "--include",
        "gbff",
        "--dehydrated",
        "--no-progressbar",
        "--filename",
        zip_path.name,
    ]
    download_code = run_logged(
        download_command,
        job_dir,
        job_dir / "download.stdout.log",
        job_dir / "download.stderr.log",
    )
    if download_code != 0 or not zip_path.is_file():
        return {
            "batch": batch_id,
            "status": "download_failed",
            "download_exit_code": download_code,
            "rehydrate_exit_code": "",
            "requested_accessions": requested_accessions,
            "gbff_files": 0,
            "missing_gbff": requested_accessions,
            "started_at": started,
            "finished_at": utc_now(),
            "wall_seconds": f"{time.perf_counter() - started_clock:.6f}",
            "job_dir": str(job_dir),
        }

    extract_new(zip_path, extracted_dir)
    rehydrate_command = [
        str(datasets),
        "rehydrate",
        "--directory",
        str(extracted_dir),
        "--max-workers",
        str(rehydrate_workers),
        "--no-progressbar",
    ]
    rehydrate_code = run_logged(
        rehydrate_command,
        job_dir,
        job_dir / "rehydrate.stdout.log",
        job_dir / "rehydrate.stderr.log",
    )
    gbff_files = len(list(extracted_dir.rglob("*.gbff")))
    if rehydrate_code != 0:
        status = "rehydrate_failed"
    elif gbff_files < requested_accessions:
        status = "downloaded_with_missing"
    else:
        status = "downloaded"
    return {
        "batch": batch_id,
        "status": status,
        "download_exit_code": download_code,
        "rehydrate_exit_code": rehydrate_code,
        "requested_accessions": requested_accessions,
        "gbff_files": gbff_files,
        "missing_gbff": max(0, requested_accessions - gbff_files),
        "started_at": started,
        "finished_at": utc_now(),
        "wall_seconds": f"{time.perf_counter() - started_clock:.6f}",
        "job_dir": str(job_dir),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--datasets", type=Path, required=True)
    parser.add_argument("--download-concurrency", type=int, default=2)
    parser.add_argument("--rehydrate-workers", type=int, default=5)
    args = parser.parse_args(argv)

    status_path = args.test_root / "download" / "download_status.tsv"
    if status_path.exists():
        raise FileExistsError(f"Status file already exists: {status_path}")
    if not args.datasets.is_file():
        raise FileNotFoundError(args.datasets)

    batch_files = sorted((args.test_root / "download" / "accession_batches").glob("batch_*.txt"))
    jobs_dir = args.test_root / "download" / "jobs"
    results = []
    with ThreadPoolExecutor(max_workers=args.download_concurrency) as executor:
        futures = {
            executor.submit(process_batch, batch, jobs_dir, args.datasets, args.rehydrate_workers): batch
            for batch in batch_files
        }
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"{result['batch']} status={result['status']} gbff={result['gbff_files']}", flush=True)

    results.sort(key=lambda row: row["batch"])
    fields = [
        "batch",
        "status",
        "download_exit_code",
        "rehydrate_exit_code",
        "requested_accessions",
        "gbff_files",
        "missing_gbff",
        "started_at",
        "finished_at",
        "wall_seconds",
        "job_dir",
    ]
    with status_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(results)

    failed = sum(result["status"] in {"download_failed", "rehydrate_failed"} for result in results)
    print(f"batches={len(results)} failed={failed} gbff={sum(result['gbff_files'] for result in results)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
