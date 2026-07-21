#!/usr/bin/env python3
"""Non-destructive smoke test for selection, download verification, and checkpoints."""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path


def read_tsv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def run(command):
    completed = subprocess.run(command, check=False)
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {command}")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--scratch-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.scratch_root.exists():
        raise FileExistsError(args.scratch_root)

    repo = Path(__file__).resolve().parents[1]
    source = args.scratch_root / "source"
    source.mkdir(parents=True)
    filenames = []
    for number in range(1, 7):
        name = f"GCA_{number:09d}.1_ASM{number}_genomic.fna"
        filenames.append(name)
        with (source / name).open("x", encoding="utf-8") as handle:
            handle.write(f">contig_{number}\nACGTACGTACGT\n")

    exclude = args.scratch_root / "completed_manifest.tsv"
    with exclude.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["fna_filename"])
        writer.writerow([filenames[0]])

    run_root = args.scratch_root / "run"
    test_root = run_root / "work"
    run(
        [
            sys.executable,
            str(repo / "scripts" / "prepare_unrun_batch.py"),
            "--source-fna-dir",
            str(source),
            "--test-root",
            str(test_root),
            "--exclude-manifest",
            str(exclude),
            "--count",
            "4",
            "--batch-size",
            "2",
        ]
    )
    manifest = read_tsv(test_root / "input" / "fna_manifest.tsv")
    if len(manifest) != 4 or filenames[0] in {row["fna_filename"] for row in manifest}:
        raise AssertionError("Selection/exclusion validation failed")

    for row in manifest:
        gbff = test_root / "download" / "synthetic" / "ncbi_dataset" / "data" / row["assembly_accession"] / "genomic.gbff"
        gbff.parent.mkdir(parents=True)
        with gbff.open("x", encoding="utf-8") as handle:
            handle.write("synthetic smoke-test placeholder\n")
    status = test_root / "download" / "download_status.tsv"
    with status.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["batch", "status", "requested_accessions", "gbff_files", "missing_gbff"])
        writer.writerow(["synthetic", "downloaded", 4, 4, 0])
    run([sys.executable, str(repo / "scripts" / "verify_download.py"), "--test-root", str(test_root)])

    run(
        [
            sys.executable,
            str(repo / "scripts" / "prepare_checkpoints.py"),
            "--run-root",
            str(run_root),
            "--chunk-size",
            "2",
        ]
    )
    checkpoints = read_tsv(test_root / "config" / "stss_checkpoints.tsv")
    if len(checkpoints) != 2 or sum(int(row["sample_count"]) for row in checkpoints) != 4:
        raise AssertionError("Checkpoint validation failed")
    print(f"smoke_test=passed scratch_root={args.scratch_root}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
