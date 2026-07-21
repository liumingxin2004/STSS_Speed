#!/usr/bin/env python3
"""Run isolated offline STSS workers and aggregate their TXT/CSV results."""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_STSS_DIR = Path(__file__).resolve().parents[1] / ".stss_speed" / "upstream"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_tsv_dict(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def metadata(path: Path):
    if not path.is_file():
        return {}
    return {row["field"]: row["value"] for row in read_tsv_dict(path)}


def guard_values(path: Path):
    if not path.is_file():
        return {}
    return {row["metric"]: row["value"] for row in read_tsv_dict(path)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path, required=True)
    parser.add_argument(
        "--stss-dir",
        type=Path,
        default=DEFAULT_STSS_DIR,
        help=f"STSS source directory (default: {DEFAULT_STSS_DIR})",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cpus-per-worker", type=int, default=0)
    args = parser.parse_args(argv)

    if args.output_root.exists():
        raise FileExistsError(f"Output root already exists: {args.output_root}")
    if not (args.stss_dir / "STSS.py").is_file():
        raise FileNotFoundError(args.stss_dir / "STSS.py")
    runtime_bin = args.stss_dir.resolve().parent / "bin"
    args.output_root.mkdir(parents=True)
    status_path = args.test_root / "stss_runs" / "batch_status.tsv"
    if status_path.exists():
        raise FileExistsError(f"Status file already exists: {status_path}")

    manifest = read_tsv_dict(args.test_root / "input" / "fna_manifest.tsv")
    available_cpus = sorted(os.sched_getaffinity(0))
    usable_cpu_count = max(1, len(available_cpus) - 2)
    cpus_per_worker = args.cpus_per_worker or max(1, usable_cpu_count // args.workers)
    if args.workers * cpus_per_worker > len(available_cpus):
        raise ValueError("workers * cpus-per-worker exceeds available CPU affinity")
    input_root = args.test_root / "stss_runs" / "batch_inputs"
    workers = []
    started_clock = time.perf_counter()
    for worker_index in range(args.workers):
        worker_name = f"worker_{worker_index + 1:02d}"
        worker_input = input_root / worker_name
        worker_input.mkdir()
        assigned = manifest[worker_index:: args.workers]
        for sample in assigned:
            (worker_input / sample["fna_filename"]).symlink_to(Path(sample["source_path"]))
        run_dir = args.output_root / worker_name
        stdout_path = args.test_root / "stss_runs" / "logs" / f"{worker_name}.stdout.log"
        stderr_path = args.test_root / "stss_runs" / "logs" / f"{worker_name}.stderr.log"
        stdout_handle = stdout_path.open("x", encoding="utf-8")
        stderr_handle = stderr_path.open("x", encoding="utf-8")
        prefix = f"stss500_w{worker_index + 1:02d}"
        command = [
            str(args.python),
            str(args.wrapper),
            "--input-dir",
            str(worker_input),
            "--cache-dir",
            str(args.test_root / "cache" / "shared_GenBank_files"),
            "--run-dir",
            str(run_dir),
            "--prefix",
            prefix,
        ]
        child_env = os.environ.copy()
        existing_pythonpath = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = str(args.stss_dir) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        child_env["PYTHONUNBUFFERED"] = "1"
        if runtime_bin.is_dir():
            child_env["STSS_SPEED_RUNTIME_BIN"] = str(runtime_bin)
        process = subprocess.Popen(command, stdout=stdout_handle, stderr=stderr_handle, env=child_env)
        cpu_start = worker_index * cpus_per_worker
        worker_cpus = available_cpus[cpu_start : cpu_start + cpus_per_worker]
        os.sched_setaffinity(process.pid, set(worker_cpus))
        workers.append(
            {
                "worker": worker_name,
                "assigned_samples": len(assigned),
                "prefix": prefix,
                "run_dir": run_dir,
                "process": process,
                "stdout_handle": stdout_handle,
                "stderr_handle": stderr_handle,
                "started_at": utc_now(),
                "cpu_affinity": ",".join(str(cpu) for cpu in worker_cpus),
            }
        )

    status_rows = []
    for worker in workers:
        exit_code = worker["process"].wait()
        worker["stdout_handle"].close()
        worker["stderr_handle"].close()
        run_meta = metadata(worker["run_dir"] / "run_metadata.tsv")
        guard = guard_values(worker["run_dir"] / "network_guard_report.tsv")
        status_rows.append(
            {
                "worker": worker["worker"],
                "assigned_samples": worker["assigned_samples"],
                "exit_code": exit_code,
                "status": run_meta.get("status", "missing_metadata"),
                "analyzed_genomes": run_meta.get("analyzed_genomes", "0"),
                "self_target_hits": run_meta.get("self_target_hits", "0"),
                "wall_seconds": run_meta.get("wall_seconds", ""),
                "cpu_affinity": worker["cpu_affinity"],
                "entrez_requests": guard.get("Entrez requests", "missing"),
                "cdd_network_requests": guard.get("CDD network requests", "missing"),
                "phaster_requests": guard.get("PHASTER requests", "missing"),
                "other_http_requests": guard.get("other HTTP requests", "missing"),
                "started_at": worker["started_at"],
                "finished_at": utc_now(),
                "run_dir": str(worker["run_dir"]),
            }
        )
        print(
            f"{worker['worker']} exit={exit_code} genomes={run_meta.get('analyzed_genomes', '0')} "
            f"hits={run_meta.get('self_target_hits', '0')}",
            flush=True,
        )

    fields = list(status_rows[0].keys())
    with status_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(status_rows)

    combined_txt = args.output_root / "stss500_Spacers_no_PHASTER_analysis.txt"
    combined_csv = args.output_root / "stss500_Spacers_no_PHASTER_analysis.csv"
    header = None
    body = []
    for worker in workers:
        result_path = worker["run_dir"] / f"{worker['prefix']}_Spacers_no_PHASTER_analysis.txt"
        if not result_path.is_file():
            continue
        lines = result_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            continue
        if header is None:
            header = lines[0]
        elif lines[0] != header:
            raise ValueError(f"Result header mismatch in {result_path}")
        body.extend(line for line in lines[1:] if line.strip())
    if header is None:
        header = ""
    combined_txt.write_text("\n".join([header, *body]) + "\n", encoding="utf-8")
    with combined_csv.open("x", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        for line in [header, *body]:
            writer.writerow(line.split("\t"))

    elapsed = time.perf_counter() - started_clock
    analyzed = sum(int(row["analyzed_genomes"]) for row in status_rows)
    hits = len(body)
    report_path = args.test_root / "reports" / "stss_500_run_summary.tsv"
    with report_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(
            [
                ["field", "value"],
                ["workers", args.workers],
                ["assigned_samples", len(manifest)],
                ["analyzed_genomes", analyzed],
                ["self_target_hits", hits],
                ["total_wall_seconds", f"{elapsed:.6f}"],
                ["genomes_per_second", f"{analyzed / elapsed:.6f}" if elapsed else "0"],
                ["output_root", args.output_root],
                ["combined_txt", combined_txt],
                ["combined_csv", combined_csv],
            ]
        )

    failed = sum(row["exit_code"] != 0 for row in status_rows)
    sample_count_mismatches = sum(
        int(row["assigned_samples"]) != int(row["analyzed_genomes"])
        for row in status_rows
    )
    network_violations = sum(
        any(row[key] != "0" for key in ["entrez_requests", "cdd_network_requests", "phaster_requests", "other_http_requests"])
        for row in status_rows
    )
    print(
        f"analyzed={analyzed} hits={hits} wall_seconds={elapsed:.3f} "
        f"failed_workers={failed} sample_count_mismatches={sample_count_mismatches}"
    )
    print(f"network_violations={network_violations} output_root={args.output_root}")
    return 1 if failed or network_violations or sample_count_mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
