#!/usr/bin/env python3
"""Run the local STSS snapshot with all online annotation paths disabled."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from Bio import SeqIO

import STSS


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


class OfflineGuard:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_hits = 0
        self.cache_misses = []
        self.cache_invalid = []
        self.cdd_disabled_calls = 0
        self.entrez_requests = 0
        self.phaster_requests = 0
        self.other_http_requests = 0

    @staticmethod
    def cache_key(accession: str) -> str:
        return re.sub(r"\.\d+$", "", accession)

    def download_genbank(self, contig_accession, bad_gb_links=None):
        cache_key = self.cache_key(contig_accession)
        cache_file = self.cache_dir / f"{cache_key}.gb"
        if not cache_file.is_file():
            self.cache_misses.append(contig_accession)
            print(
                f"GBK cache miss: {contig_accession}; "
                "recorded Missing Data; network disabled"
            )
            return "Missing Data"

        try:
            record = SeqIO.read(cache_file, "genbank")
        except Exception as error:
            self.cache_invalid.append((contig_accession, str(error)))
            print(
                f"GBK cache invalid: {contig_accession}; "
                "recorded Missing Data; network disabled"
            )
            return "Missing Data"

        self.cache_hits += 1
        return record

    def cdd_homology_search(self, check_list):
        self.cdd_disabled_calls += 1
        print("CDD disabled: hypothetical-protein target annotation left unchanged.")
        return []

    def block_entrez(self, *args, **kwargs):
        self.entrez_requests += 1
        raise RuntimeError("Entrez request blocked by strict offline mode")

    def block_http(self, *args, **kwargs):
        self.other_http_requests += 1
        raise RuntimeError("HTTP request blocked by strict offline mode")

    def block_phaster(self, *args, **kwargs):
        self.phaster_requests += 1
        raise RuntimeError("PHASTER request blocked by strict offline mode")


def patch_network_paths(guard: OfflineGuard) -> None:
    STSS.download_genbank = guard.download_genbank
    STSS.CDD_homology_search = guard.cdd_homology_search
    STSS.query_PHASTER = guard.block_phaster
    STSS.Entrez.efetch = guard.block_entrez
    STSS.Entrez.esearch = guard.block_entrez
    STSS.Entrez.elink = guard.block_entrez
    STSS.requests.sessions.Session.request = guard.block_http


def configure_runtime_bin() -> None:
    raw_path = os.environ.get("STSS_SPEED_RUNTIME_BIN")
    if not raw_path:
        return
    runtime_bin = Path(raw_path).resolve()
    required = ("blastn", "clustalo", "hmmscan", "nhmmscan", "CRT1.2-CLI.jar")
    missing = [name for name in required if not (runtime_bin / name).exists()]
    if missing:
        raise FileNotFoundError(f"STSS runtime bin is incomplete: {runtime_bin}; missing={','.join(missing)}")
    STSS.bin_path = f"{runtime_bin}/"


def convert_tab_to_csv(source: Path, target: Path) -> int:
    if not source.is_file():
        return 0
    with source.open("r", encoding="utf-8", newline="") as input_handle:
        rows = list(csv.reader(input_handle, delimiter="\t"))
    with target.open("x", encoding="utf-8", newline="") as output_handle:
        csv.writer(output_handle).writerows(rows)
    return max(0, len(rows) - 1)


def count_nonempty_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def write_tsv(path: Path, rows) -> None:
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerows(rows)


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--cas-gene-distance", type=int, default=20000)
    return parser.parse_args(argv)


def validate_args(args) -> None:
    if not args.input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {args.input_dir}")
    if not args.cache_dir.is_dir():
        raise ValueError(f"Cache directory does not exist: {args.cache_dir}")
    if args.run_dir.exists():
        raise FileExistsError(f"Run directory already exists: {args.run_dir}")
    if args.cas_gene_distance == 0:
        raise ValueError("--cas-gene-distance 0 is forbidden in strict offline mode")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", args.prefix):
        raise ValueError("Prefix may contain only letters, digits, dot, underscore, and hyphen")


def main(argv=None) -> int:
    args = parse_args(argv)
    args.input_dir = args.input_dir.resolve()
    args.cache_dir = args.cache_dir.resolve()
    args.run_dir = args.run_dir.resolve()
    validate_args(args)

    args.run_dir.parent.mkdir(parents=True, exist_ok=True)
    args.run_dir.mkdir()
    (args.run_dir / "GenBank_files").symlink_to(args.cache_dir, target_is_directory=True)

    guard = OfflineGuard(args.cache_dir)
    configure_runtime_bin()
    patch_network_paths(guard)
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    status = "completed"
    exit_code = 0
    original_cwd = Path.cwd()
    log_path = args.run_dir / "run.log"

    try:
        os.chdir(args.run_dir)
        with log_path.open("x", encoding="utf-8") as log_handle:
            stdout_tee = Tee(sys.stdout, log_handle)
            stderr_tee = Tee(sys.stderr, log_handle)
            with redirect_stdout(stdout_tee), redirect_stderr(stderr_tee):
                stss_argv = [
                    "STSS.py",
                    "--dir",
                    str(args.input_dir),
                    "-o",
                    args.prefix,
                    "--no-ask",
                    "--skip-PHASTER",
                    "--Cas-gene-distance",
                    str(args.cas_gene_distance),
                ]
                original_argv = sys.argv
                try:
                    sys.argv = stss_argv
                    try:
                        result = STSS.main()
                        exit_code = int(result or 0)
                    except SystemExit as error:
                        exit_code = error.code if isinstance(error.code, int) else 0
                finally:
                    sys.argv = original_argv
    except Exception:
        status = "failed"
        exit_code = 1
        raise
    finally:
        os.chdir(original_cwd)
        wall_seconds = time.perf_counter() - started_wall
        cpu_seconds = time.process_time() - started_cpu
        result_txt = args.run_dir / f"{args.prefix}_Spacers_no_PHASTER_analysis.txt"
        result_csv = args.run_dir / f"{args.prefix}_Spacers_no_PHASTER_analysis.csv"
        hit_count = convert_tab_to_csv(result_txt, result_csv)
        genome_count = count_nonempty_lines(
            args.run_dir / f"{args.prefix}_genomes_analyzed.txt"
        )
        input_fna_count = sum(
            path.is_file() and path.suffix.lower() in {".fna", ".fa", ".fasta"}
            for path in args.input_dir.iterdir()
        )
        if status == "completed" and input_fna_count and genome_count == 0:
            status = "failed_no_genomes_analyzed"
            exit_code = 1
        elif status == "completed" and not result_txt.exists():
            status = "completed_no_hits"

        log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
        report_rows = [
            ["metric", "value"],
            ["Entrez requests", guard.entrez_requests],
            ["CDD network requests", 0],
            ["PHASTER requests", guard.phaster_requests],
            ["other HTTP requests", guard.other_http_requests],
            ["CDD disabled calls", guard.cdd_disabled_calls],
            ["CDD retry messages", log_text.count("Trying to overcome issues with CDD speed/connectivity")],
            ["CDD error retry messages", log_text.count("Error in protein homology search. Retrying")],
            ["GBK cache hits", guard.cache_hits],
            ["GBK cache misses", len(guard.cache_misses)],
            ["GBK cache invalid", len(guard.cache_invalid)],
        ]
        write_tsv(args.run_dir / "network_guard_report.tsv", report_rows)
        write_tsv(
            args.run_dir / "cache_missing_accessions.tsv",
            [["accession"]] + [[item] for item in sorted(set(guard.cache_misses))],
        )
        write_tsv(
            args.run_dir / "cache_invalid_accessions.tsv",
            [["accession", "message"]] + guard.cache_invalid,
        )
        write_tsv(
            args.run_dir / "run_metadata.tsv",
            [
                ["field", "value"],
                ["status", status],
                ["exit_code", exit_code],
                ["input_dir", args.input_dir],
                ["cache_dir", args.cache_dir],
                ["prefix", args.prefix],
                ["PHASTER", "skipped"],
                ["cas_gene_distance", args.cas_gene_distance],
                ["wall_seconds", f"{wall_seconds:.6f}"],
                ["python_cpu_seconds", f"{cpu_seconds:.6f}"],
                ["analyzed_genomes", genome_count],
                ["self_target_hits", hit_count],
            ],
        )

    print(f"Run directory: {args.run_dir}")
    print(f"Main TXT: {result_txt}")
    print(f"Main CSV: {result_csv}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
