#!/usr/bin/env python3
"""Create immutable STSS checkpoint workspaces backed by one shared cache."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args(argv)

    main_work = args.run_root / "work"
    manifest_path = main_work / "input" / "fna_manifest.tsv"
    cache_path = main_work / "cache" / "shared_GenBank_files"
    checkpoints_root = args.run_root / "stss_checkpoints"
    master_path = main_work / "config" / "stss_checkpoints.tsv"
    if checkpoints_root.exists():
        raise FileExistsError(checkpoints_root)
    if master_path.exists():
        raise FileExistsError(master_path)
    if not cache_path.is_dir():
        raise FileNotFoundError(cache_path)

    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not rows:
        raise ValueError("Input manifest is empty")

    checkpoints_root.mkdir(parents=True)
    master_rows = []
    for offset in range(0, len(rows), args.chunk_size):
        number = offset // args.chunk_size + 1
        checkpoint = f"checkpoint_{number:03d}"
        checkpoint_root = checkpoints_root / checkpoint
        test_root = checkpoint_root / "work"
        for relative in ("input", "cache", "stss_runs/batch_inputs", "stss_runs/logs", "reports", "config"):
            (test_root / relative).mkdir(parents=True)
        (test_root / "cache" / "shared_GenBank_files").symlink_to(cache_path, target_is_directory=True)
        chunk = rows[offset : offset + args.chunk_size]
        with (test_root / "input" / "fna_manifest.tsv").open("x", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(chunk)
        with (test_root / "config" / "checkpoint_summary.tsv").open(
            "x", encoding="utf-8", newline=""
        ) as handle:
            csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
                [
                    ["field", "value"],
                    ["checkpoint", checkpoint],
                    ["sample_count", len(chunk)],
                    ["first_sample_index", chunk[0]["sample_index"]],
                    ["last_sample_index", chunk[-1]["sample_index"]],
                    ["shared_cache", cache_path],
                ]
            )
        master_rows.append(
            {
                "checkpoint": checkpoint,
                "sample_count": len(chunk),
                "first_sample_index": chunk[0]["sample_index"],
                "last_sample_index": chunk[-1]["sample_index"],
                "test_root": test_root,
                "output_root": checkpoint_root / "results",
            }
        )

    with master_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(master_rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(master_rows)
    print(f"checkpoints={len(master_rows)} samples={sum(row['sample_count'] for row in master_rows)}")
    print(f"master={master_path}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
