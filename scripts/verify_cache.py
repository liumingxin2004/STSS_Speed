#!/usr/bin/env python3
"""Verify the shared per-contig GenBank cache before offline STSS."""

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
    cache = args.test_root / "cache"
    manifest = read_tsv(cache / "cache_manifest.tsv")
    invalid = read_tsv(cache / "cache_invalid_gbk.tsv")
    conflicts = read_tsv(cache / "cache_conflicts.tsv")
    coverage = read_tsv(cache / "cache_coverage_summary.tsv")
    missing = read_tsv(cache / "cache_missing_accessions.tsv")
    published = list((cache / "shared_GenBank_files").glob("*.gb"))
    payload = {
        "cache_manifest_rows": len(manifest),
        "cache_status_counts": dict(sorted(Counter(row["status"] for row in manifest).items())),
        "published_gb_files": len(published),
        "invalid_rows": len(invalid),
        "conflict_rows": len(conflicts),
        "coverage_assemblies": len(coverage),
        "fna_contigs": sum(int(row["contigs"]) for row in coverage),
        "cache_present": sum(int(row["cache_present"]) for row in coverage),
        "cache_missing": sum(int(row["cache_missing"]) for row in coverage),
        "assemblies_below_full_coverage": sum(row["coverage_fraction"] != "1.000000" for row in coverage),
        "missing_accession_rows": len(missing),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    ok = (
        len(manifest) == len(published)
        and payload["cache_status_counts"] == {"published": len(manifest)}
        and not invalid
        and not conflicts
        and payload["fna_contigs"] == payload["cache_present"]
        and payload["cache_missing"] == 0
        and payload["assemblies_below_full_coverage"] == 0
        and not missing
    )
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
