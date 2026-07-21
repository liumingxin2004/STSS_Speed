#!/usr/bin/env python3
"""Verify that downloaded GBFF assemblies exactly match the input manifest."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def read_tsv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-root", type=Path, required=True)
    args = parser.parse_args(argv)

    status = read_tsv(args.test_root / "download" / "download_status.tsv")
    manifest = read_tsv(args.test_root / "input" / "fna_manifest.tsv")
    expected = {row["assembly_accession"] for row in manifest}
    gbff_paths = sorted(args.test_root.rglob("*.gbff"))
    actual_list = [path.parent.name for path in gbff_paths]
    actual = set(actual_list)
    payload = {
        "status_rows": len(status),
        "status_counts": dict(sorted(Counter(row["status"] for row in status).items())),
        "requested_accessions": sum(int(row["requested_accessions"]) for row in status),
        "reported_gbff": sum(int(row["gbff_files"]) for row in status),
        "reported_missing": sum(int(row["missing_gbff"]) for row in status),
        "manifest_accessions": len(expected),
        "gbff_paths": len(gbff_paths),
        "gbff_unique_assembly_dirs": len(actual),
        "missing_expected_assemblies": sorted(expected - actual),
        "unexpected_assemblies": sorted(actual - expected),
        "duplicate_assembly_dirs": sorted(name for name, count in Counter(actual_list).items() if count > 1),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = (
        payload["status_counts"] == {"downloaded": len(status)}
        and payload["requested_accessions"] == len(manifest)
        and payload["reported_gbff"] == len(manifest)
        and payload["reported_missing"] == 0
        and len(gbff_paths) == len(manifest)
        and len(actual) == len(manifest)
        and not payload["missing_expected_assemblies"]
        and not payload["unexpected_assemblies"]
        and not payload["duplicate_assembly_dirs"]
    )
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
