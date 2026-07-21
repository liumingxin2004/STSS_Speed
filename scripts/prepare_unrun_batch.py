#!/usr/bin/env python3
"""Create a deterministic STSS workspace while excluding prior manifests."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


ACCESSION_RE = re.compile(r"^(GC[AF]_\d+\.\d+)")


def read_excluded_names(paths: list[Path]) -> set[str]:
    names: set[str] = set()
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = csv.DictReader(handle, delimiter="\t")
            if not rows.fieldnames or "fna_filename" not in rows.fieldnames:
                raise ValueError(f"Manifest lacks fna_filename: {path}")
            names.update(row["fna_filename"] for row in rows if row["fna_filename"])
    return names


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-fna-dir", type=Path, required=True)
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--exclude-manifest", type=Path, action="append", default=[])
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args(argv)

    if args.test_root.exists():
        raise FileExistsError(f"Test root already exists: {args.test_root}")
    excluded_names = read_excluded_names(args.exclude_manifest)
    candidates = sorted(args.source_fna_dir.glob("*.fna"), key=lambda path: path.name)
    source_names = {path.name for path in candidates}
    selected = [path for path in candidates if path.name not in excluded_names][: args.count]
    if len(selected) != args.count:
        raise ValueError(f"Requested {args.count} eligible FNA files, found {len(selected)}")

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

    staged_dir = args.test_root / "input" / f"fna_{args.count}"
    batch_dir = args.test_root / "download" / "accession_batches"
    staged_dir.mkdir(parents=True)
    batch_dir.mkdir(parents=True)
    for relative in (
        "download/jobs",
        "staging/split_partials",
        "cache/shared_GenBank_files",
        "stss_runs/batch_inputs",
        "stss_runs/logs",
        "reports",
        "config",
    ):
        (args.test_root / relative).mkdir(parents=True)

    manifest_path = args.test_root / "input" / "fna_manifest.tsv"
    fields = ["sample_index", "assembly_accession", "fna_filename", "source_path", "staged_path", "size_bytes"]
    with manifest_path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        for index, accession, source in rows:
            staged = staged_dir / source.name
            staged.symlink_to(source.resolve())
            writer.writerow([index, accession, source.name, source.resolve(), staged, source.stat().st_size])

    assemblies = args.test_root / "input" / f"assemblies_{args.count}.txt"
    assemblies.write_text("".join(f"{accession}\n" for _, accession, _ in rows), encoding="utf-8")
    for offset in range(0, len(rows), args.batch_size):
        number = offset // args.batch_size + 1
        accessions = [accession for _, accession, _ in rows[offset : offset + args.batch_size]]
        (batch_dir / f"batch_{number:03d}.txt").write_text(
            "".join(f"{accession}\n" for accession in accessions), encoding="utf-8"
        )

    selected_names = {source.name for _, _, source in rows}
    overlap = selected_names & excluded_names
    if overlap:
        raise RuntimeError(f"Selected/excluded overlap: {len(overlap)}")
    summary = args.test_root / "config" / "selection_summary.tsv"
    with summary.open("x", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t", lineterminator="\n").writerows(
            [
                ["field", "value"],
                ["source_fna_count", len(candidates)],
                ["excluded_unique_filenames", len(excluded_names)],
                ["excluded_files_present_in_source", len(excluded_names & source_names)],
                ["sample_count", len(rows)],
                ["selected_excluded_overlap", len(overlap)],
                ["unique_assembly_accessions", len(seen_accessions)],
                ["batch_size", args.batch_size],
                ["batch_count", (len(rows) + args.batch_size - 1) // args.batch_size],
                ["selected_bytes", sum(source.stat().st_size for _, _, source in rows)],
            ]
        )
    print(f"test_root={args.test_root}")
    print(f"samples={len(rows)} batches={(len(rows) + args.batch_size - 1) // args.batch_size}")
    print(f"excluded={len(excluded_names)} overlap={len(overlap)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
