#!/usr/bin/env python3
"""Validate and aggregate completed STSS checkpoints into final TXT/CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ZERO_METRICS = (
    "Entrez requests",
    "CDD network requests",
    "PHASTER requests",
    "other HTTP requests",
    "GBK cache misses",
    "GBK cache invalid",
)


def read_tsv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_key_values(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle, delimiter="\t"))
    return {row[0]: row[1] for row in rows[1:]}


def file_hash(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", type=Path, required=True)
    parser.add_argument("--final-root", type=Path, required=True)
    parser.add_argument("--output-prefix", default="faststss")
    parser.add_argument("--events-dir", type=Path)
    args = parser.parse_args(argv)
    if args.final_root.exists():
        raise FileExistsError(args.final_root)

    checkpoints = read_tsv(args.master)
    if not checkpoints:
        raise ValueError("Checkpoint manifest is empty")
    header = None
    body = []
    checkpoint_rows = []
    worker_count = 0
    analyzed_total = 0
    worker_hits_total = 0
    checkpoint_wall_sum = 0.0
    guard_totals = {metric: 0 for metric in ZERO_METRICS}
    guard_totals.update({"CDD disabled calls": 0, "GBK cache hits": 0})

    for item in checkpoints:
        checkpoint = item["checkpoint"]
        expected = int(item["sample_count"])
        test_root = Path(item["test_root"])
        output_root = Path(item["output_root"])
        txt_path = output_root / "stss500_Spacers_no_PHASTER_analysis.txt"
        csv_path = output_root / "stss500_Spacers_no_PHASTER_analysis.csv"
        txt_lines = txt_path.read_text(encoding="utf-8").splitlines()
        if not txt_lines:
            raise ValueError(f"Empty TXT: {txt_path}")
        if header is None:
            header = txt_lines[0]
        elif txt_lines[0] != header:
            raise ValueError(f"Header mismatch: {txt_path}")
        checkpoint_body = [line for line in txt_lines[1:] if line.strip()]
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            csv_rows = list(csv.reader(handle))
        if len(csv_rows) - 1 != len(checkpoint_body) or csv_rows[0] != header.split("\t"):
            raise ValueError(f"TXT/CSV mismatch: {checkpoint}")

        statuses = read_tsv(test_root / "stss_runs" / "batch_status.tsv")
        analyzed = sum(int(row["analyzed_genomes"]) for row in statuses)
        worker_hits = sum(int(row["self_target_hits"]) for row in statuses)
        if analyzed != expected or worker_hits != len(checkpoint_body):
            raise ValueError(f"Worker/result mismatch: {checkpoint}")
        if any(row["exit_code"] != "0" for row in statuses):
            raise ValueError(f"Worker failure: {checkpoint}")
        if any(
            row[key] != "0"
            for row in statuses
            for key in ("entrez_requests", "cdd_network_requests", "phaster_requests", "other_http_requests")
        ):
            raise ValueError(f"Network violation: {checkpoint}")

        for status in statuses:
            guard = read_key_values(Path(status["run_dir"]) / "network_guard_report.tsv")
            for metric in ZERO_METRICS:
                value = int(guard[metric])
                guard_totals[metric] += value
                if value:
                    raise ValueError(f"Guard violation {metric}: {status['run_dir']}")
            guard_totals["CDD disabled calls"] += int(guard["CDD disabled calls"])
            guard_totals["GBK cache hits"] += int(guard["GBK cache hits"])

        summary = read_key_values(test_root / "reports" / "stss_500_run_summary.tsv")
        wall = float(summary["total_wall_seconds"])
        checkpoint_wall_sum += wall
        checkpoint_rows.append(
            {
                "checkpoint": checkpoint,
                "analyzed_genomes": analyzed,
                "self_target_hits": worker_hits,
                "wall_seconds": f"{wall:.6f}",
            }
        )
        worker_count += len(statuses)
        analyzed_total += analyzed
        worker_hits_total += worker_hits
        body.extend(checkpoint_body)

    if worker_hits_total != len(body):
        raise ValueError("Aggregate hit mismatch")
    run_root = args.master.parents[2]
    events_dir = args.events_dir or (run_root / "work" / "stss_checkpoint_events")
    completed_events = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(events_dir.glob("*_completed.json"))
    ]
    if len(completed_events) != len(checkpoints):
        raise ValueError("Completed event count does not match checkpoints")
    started_at = min(datetime.fromisoformat(row["started_at"]) for row in completed_events)
    finished_at = max(datetime.fromisoformat(row["finished_at"]) for row in completed_events)
    wall_seconds = (finished_at - started_at).total_seconds()

    args.final_root.mkdir(parents=True)
    txt_output = args.final_root / f"{args.output_prefix}_Spacers_no_PHASTER_analysis.txt"
    csv_output = args.final_root / f"{args.output_prefix}_Spacers_no_PHASTER_analysis.csv"
    checkpoint_output = args.final_root / "checkpoint_summary.tsv"
    summary_output = args.final_root / "completion_summary.tsv"
    report_output = args.final_root / "FASTSTSS_COMPLETION_REPORT.md"
    with txt_output.open("x", encoding="utf-8", newline="") as handle:
        handle.write("\n".join([header or "", *body]) + "\n")
    with csv_output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for line in [header or "", *body]:
            writer.writerow(line.split("\t"))
    with checkpoint_output.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(checkpoint_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(checkpoint_rows)
    with summary_output.open("x", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
            [
                ["field", "value"],
                ["analyzed_genomes", analyzed_total],
                ["checkpoints", len(checkpoints)],
                ["workers", worker_count],
                ["self_target_hits", len(body)],
                ["orchestrator_wall_seconds", f"{wall_seconds:.6f}"],
                ["checkpoint_wall_seconds_sum", f"{checkpoint_wall_sum:.6f}"],
                ["genomes_per_minute", f"{analyzed_total / wall_seconds * 60:.6f}"],
                *[[metric, value] for metric, value in guard_totals.items()],
                ["combined_txt", txt_output],
                ["combined_csv", csv_output],
            ]
        )
    txt_sha256 = file_hash(txt_output)
    csv_sha256 = file_hash(csv_output)
    with report_output.open("x", encoding="utf-8", newline="") as handle:
        handle.write(
            "# fastSTSS completion report\n\n"
            f"- Analyzed genomes: {analyzed_total}\n"
            f"- Checkpoints/workers: {len(checkpoints)}/{worker_count}\n"
            f"- Self-target hits: {len(body)}\n"
            f"- STSS wall time: {wall_seconds:.3f} seconds\n"
            f"- Throughput: {analyzed_total / wall_seconds * 60:.3f} genomes/minute\n"
            "- Entrez/CDD-network/PHASTER/other-HTTP: 0/0/0/0\n"
            "- GBK cache misses/invalid: 0/0\n"
            f"- TXT SHA256: {txt_sha256}\n"
            f"- CSV SHA256: {csv_sha256}\n"
            f"- TXT: {txt_output}\n"
            f"- CSV: {csv_output}\n"
        )
    print(
        json.dumps(
            {
                "analyzed_genomes": analyzed_total,
                "self_target_hits": len(body),
                "workers": worker_count,
                "wall_seconds": wall_seconds,
                "genomes_per_minute": analyzed_total / wall_seconds * 60,
                "guard_totals": guard_totals,
                "txt_sha256": txt_sha256,
                "csv_sha256": csv_sha256,
                "final_root": str(args.final_root),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
