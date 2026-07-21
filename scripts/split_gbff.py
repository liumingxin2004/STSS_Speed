#!/usr/bin/env python3
"""Split assembly GBFF files into a validated, shared per-contig STSS cache."""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from Bio import SeqIO


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cache_key(accession: str):
    return re.sub(r"\.\d+$", "", accession)


def split_one(gbff_text: str, staging_root_text: str):
    gbff = Path(gbff_text)
    staging_root = Path(staging_root_text)
    assembly = gbff.parent.name
    assembly_stage = staging_root / assembly
    assembly_stage.mkdir()
    rows = []
    try:
        with gbff.open("r", encoding="utf-8") as handle:
            for record in SeqIO.parse(handle, "genbank"):
                key = cache_key(record.id)
                staged = assembly_stage / f"{key}.gb.partial"
                with staged.open("x", encoding="utf-8") as output:
                    written = SeqIO.write(record, output, "genbank")
                if written != 1:
                    raise ValueError(f"Expected one record for {record.id}, wrote {written}")
                validated = SeqIO.read(staged, "genbank")
                rows.append(
                    {
                        "assembly_accession": assembly,
                        "gbff_source_file": str(gbff),
                        "gb_record_accession": validated.id,
                        "cache_key": key,
                        "staged_path": str(staged),
                        "record_length_bp": len(validated.seq),
                        "gb_sha256": sha256(staged),
                        "worker_status": "validated",
                        "message": "",
                    }
                )
    except Exception as error:
        rows.append(
            {
                "assembly_accession": assembly,
                "gbff_source_file": str(gbff),
                "gb_record_accession": "",
                "cache_key": "",
                "staged_path": "",
                "record_length_bp": "",
                "gb_sha256": "",
                "worker_status": "invalid",
                "message": str(error),
            }
        )
    return rows


def read_manifest(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def write_table(path: Path, fieldnames, rows):
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)

    cache_dir = args.test_root / "cache" / "shared_GenBank_files"
    staging_root = args.test_root / "staging" / "split_partials"
    manifest_path = args.test_root / "cache" / "cache_manifest.tsv"
    if manifest_path.exists():
        raise FileExistsError(f"Manifest already exists: {manifest_path}")
    if any(cache_dir.iterdir()) or any(staging_root.iterdir()):
        raise FileExistsError("Cache or split staging directory is not empty")

    fna_manifest = read_manifest(args.test_root / "input" / "fna_manifest.tsv")
    fna_by_assembly = {row["assembly_accession"]: row["fna_filename"] for row in fna_manifest}
    gbff_files = sorted(args.test_root.rglob("*.gbff"))
    worker_rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(split_one, str(path), str(staging_root)) for path in gbff_files]
        for completed, future in enumerate(as_completed(futures), start=1):
            worker_rows.extend(future.result())
            if completed % 25 == 0 or completed == len(futures):
                print(f"split_files={completed}/{len(futures)}", flush=True)

    manifest_rows = []
    conflicts = []
    invalid = []
    for row in sorted(worker_rows, key=lambda item: (item["assembly_accession"], item["cache_key"])):
        if row["worker_status"] != "validated":
            invalid.append(row)
            continue
        destination = cache_dir / f"{row['cache_key']}.gb"
        status = "published"
        message = ""
        if destination.exists():
            if sha256(destination) == row["gb_sha256"]:
                status = "duplicate"
                message = "identical cache key already published"
            else:
                status = "conflict"
                message = "cache key exists with different SHA256"
                conflicts.append({**row, "cache_gb_path": str(destination), "status": status, "message": message})
        else:
            os.link(row["staged_path"], destination)
        manifest_rows.append(
            {
                "assembly_accession": row["assembly_accession"],
                "fna_filename": fna_by_assembly.get(row["assembly_accession"], ""),
                "gbff_source_file": row["gbff_source_file"],
                "gb_record_accession": row["gb_record_accession"],
                "cache_key": row["cache_key"],
                "cache_gb_path": str(destination),
                "record_length_bp": row["record_length_bp"],
                "gb_sha256": row["gb_sha256"],
                "status": status,
                "message": message,
            }
        )

    manifest_fields = [
        "assembly_accession",
        "fna_filename",
        "gbff_source_file",
        "gb_record_accession",
        "cache_key",
        "cache_gb_path",
        "record_length_bp",
        "gb_sha256",
        "status",
        "message",
    ]
    write_table(manifest_path, manifest_fields, manifest_rows)
    write_table(args.test_root / "cache" / "cache_conflicts.tsv", manifest_fields, conflicts)
    invalid_fields = list(worker_rows[0].keys()) if worker_rows else ["message"]
    write_table(args.test_root / "cache" / "cache_invalid_gbk.tsv", invalid_fields, invalid)

    missing_rows = []
    summary_rows = []
    for sample in fna_manifest:
        total = present = 0
        with Path(sample["source_path"]).open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith(">"):
                    continue
                total += 1
                accession = line[1:].split(maxsplit=1)[0]
                key = cache_key(accession)
                if (cache_dir / f"{key}.gb").is_file():
                    present += 1
                else:
                    missing_rows.append(
                        {
                            "assembly_accession": sample["assembly_accession"],
                            "fna_filename": sample["fna_filename"],
                            "fna_contig_accession": accession,
                            "cache_key": key,
                        }
                    )
        summary_rows.append(
            {
                "assembly_accession": sample["assembly_accession"],
                "fna_filename": sample["fna_filename"],
                "contigs": total,
                "cache_present": present,
                "cache_missing": total - present,
                "coverage_fraction": f"{present / total:.6f}" if total else "0.000000",
            }
        )
    write_table(
        args.test_root / "cache" / "cache_missing_accessions.tsv",
        ["assembly_accession", "fna_filename", "fna_contig_accession", "cache_key"],
        missing_rows,
    )
    write_table(
        args.test_root / "cache" / "cache_coverage_summary.tsv",
        ["assembly_accession", "fna_filename", "contigs", "cache_present", "cache_missing", "coverage_fraction"],
        summary_rows,
    )
    print(
        f"gbff={len(gbff_files)} cache_files={len(list(cache_dir.glob('*.gb')))} "
        f"invalid={len(invalid)} conflicts={len(conflicts)} missing_contigs={len(missing_rows)}"
    )
    return 1 if invalid or conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
