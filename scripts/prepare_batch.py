#!/usr/bin/env python3
"""Create a deterministic, non-destructive 500-FNA test workspace."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


ACCESSION_RE = re.compile(r"^(GC[AF]_\d+\.\d+)")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-fna-dir", type=Path, required=True)
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--count", type=int, default=500)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)

    if args.test_root.exists():
        raise FileExistsError(f"Test root already exists: {args.test_root}")
    candidates = sorted(args.source_fna_dir.glob("*.fna"), key=lambda path: path.name)
    if len(candidates) < args.count:
        raise ValueError(f"Requested {args.count} FNA files, found {len(candidates)}")
    selected = candidates[: args.count]

    rows = []
    seen_accessions = set()
    for index, source in enumerate(selected, start=1):
        match = ACCESSION_RE.match(source.name)
        if not match:
            raise ValueError(f"Cannot parse assembly accession from {source.name}")
        accession = match.group(1)
        if accession in seen_accessions:
            raise ValueError(f"Duplicate assembly accession: {accession}")
        seen_accessions.add(accession)
        rows.append((index, accession, source))

    staged_dir = args.test_root / "input" / "fna_500"
    batch_dir = args.test_root / "download" / "accession_batches"
    staged_dir.mkdir(parents=True)
    batch_dir.mkdir(parents=True)
    for relative in [
        "download/jobs",
        "staging/split_partials",
        "cache/shared_GenBank_files",
        "stss_runs/batch_inputs",
        "stss_runs/logs",
        "reports",
        "config",
    ]:
        (args.test_root / relative).mkdir(parents=True)

    manifest_path = args.test_root / "input" / "fna_manifest.tsv"
    with manifest_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(
            ["sample_index", "assembly_accession", "fna_filename", "source_path", "staged_path", "size_bytes"]
        )
        for index, accession, source in rows:
            staged = staged_dir / source.name
            staged.symlink_to(source.resolve())
            writer.writerow([index, accession, source.name, source.resolve(), staged, source.stat().st_size])

    assembly_path = args.test_root / "input" / "assemblies_500.txt"
    assembly_path.write_text("".join(f"{accession}\n" for _, accession, _ in rows), encoding="utf-8")

    for offset in range(0, len(rows), args.batch_size):
        batch_number = offset // args.batch_size + 1
        batch_path = batch_dir / f"batch_{batch_number:03d}.txt"
        accessions = [accession for _, accession, _ in rows[offset : offset + args.batch_size]]
        batch_path.write_text("".join(f"{accession}\n" for accession in accessions), encoding="utf-8")

    summary_path = args.test_root / "config" / "selection_summary.tsv"
    with summary_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(
            [
                ["field", "value"],
                ["selection", "first filenames in ascending ordinal order"],
                ["sample_count", len(rows)],
                ["batch_size", args.batch_size],
                ["batch_count", (len(rows) + args.batch_size - 1) // args.batch_size],
                ["first_accession", rows[0][1]],
                ["last_accession", rows[-1][1]],
                ["source_fna_dir", args.source_fna_dir.resolve()],
            ]
        )

    print(f"test_root={args.test_root}")
    print(f"samples={len(rows)} batches={(len(rows) + args.batch_size - 1) // args.batch_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
