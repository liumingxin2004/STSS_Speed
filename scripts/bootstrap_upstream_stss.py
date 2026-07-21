#!/usr/bin/env python3
"""Fetch and verify the pinned upstream STSS source without publishing it."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


UPSTREAM_URL = "https://github.com/kew222/Self-Targeting-Spacer-Searcher.git"
UPSTREAM_COMMIT = "9e5d560ffb6100c5c28b46e71dae0bcde7e533e2"
PINNED_ASSET_BLOBS = {
    "HMMs/HMMs_Cas_proteins.hmm": "72ce0e2c1bb9d00665bad5b7a942ff6bae1e532f",
    "HMMs/REPEATS_HMMs.hmm": "7c32a1d15c56b9cb8a49509c29f92e3d44fc4f07",
    "CRISPR_definitions.py": "06cc1025d8cb7a9e07d0c9c894e864509df5eef4",
}
RUNTIME_BINARIES = ("blastn", "clustalo", "hmmscan", "nhmmscan")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_destination() -> Path:
    return repository_root() / ".stss_speed" / "upstream"


def runtime_bin_directory(destination: Path) -> Path:
    return destination.resolve().parent / "bin"


def git_output(directory: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(directory), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(arguments)} failed in {directory}: {detail}")
    return completed.stdout.strip()


def validate_checkout(destination: Path) -> None:
    destination = destination.resolve()
    if not destination.is_dir():
        raise FileNotFoundError(f"Upstream STSS directory does not exist: {destination}")
    if not (destination / ".git").exists():
        raise ValueError(f"Upstream STSS directory is not a Git checkout: {destination}")
    if not (destination / "STSS.py").is_file():
        raise FileNotFoundError(destination / "STSS.py")

    head = git_output(destination, "rev-parse", "HEAD")
    if head != UPSTREAM_COMMIT:
        raise ValueError(f"Expected STSS commit {UPSTREAM_COMMIT}, found {head}")
    clean = subprocess.run(
        ["git", "-C", str(destination), "diff", "--quiet", "--exit-code"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if clean.returncode:
        raise ValueError(f"Upstream STSS checkout is modified: {destination}")

    for relative_path, expected_blob in PINNED_ASSET_BLOBS.items():
        local_path = destination / relative_path
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        actual_blob = git_output(destination, "rev-parse", f"HEAD:{relative_path}")
        if actual_blob != expected_blob:
            raise ValueError(
                f"Unexpected upstream asset {relative_path}: expected {expected_blob}, "
                f"found {actual_blob}"
            )


def validate_runtime_bin(destination: Path) -> None:
    runtime_bin = runtime_bin_directory(destination)
    if not runtime_bin.is_dir():
        raise FileNotFoundError(f"Runtime binary directory does not exist: {runtime_bin}")
    for name in RUNTIME_BINARIES:
        binary = runtime_bin / name
        if not binary.is_symlink() or not binary.resolve().is_file() or not os.access(binary, os.X_OK):
            raise ValueError(f"Runtime binary is missing or unusable: {binary}")
    jar = runtime_bin / "CRT1.2-CLI.jar"
    expected_jar = destination / "bin" / "CRT1.2-CLI.jar"
    if not jar.is_symlink() or jar.resolve() != expected_jar.resolve():
        raise ValueError(f"Runtime CRT JAR must link to the pinned upstream checkout: {jar}")


def create_runtime_bin(destination: Path) -> None:
    runtime_bin = runtime_bin_directory(destination)
    if runtime_bin.exists():
        validate_runtime_bin(destination)
        return

    targets = {}
    for name in RUNTIME_BINARIES:
        located = shutil.which(name)
        if not located:
            raise RuntimeError(f"Required runtime binary is not on PATH: {name}")
        targets[name] = Path(located).resolve()
    crt_jar = destination / "bin" / "CRT1.2-CLI.jar"
    if not crt_jar.is_file():
        raise FileNotFoundError(crt_jar)

    runtime_bin.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".runtime_bin_", dir=runtime_bin.parent) as temporary:
        staging = Path(temporary) / "bin"
        staging.mkdir()
        for name, target in targets.items():
            (staging / name).symlink_to(target)
        (staging / "CRT1.2-CLI.jar").symlink_to(crt_jar)
        staging.rename(runtime_bin)
    validate_runtime_bin(destination)


def clone_and_publish(destination: Path) -> None:
    destination = destination.expanduser().resolve()
    if destination.exists():
        validate_checkout(destination)
        create_runtime_bin(destination)
        print(f"bootstrap_ok=existing destination={destination}")
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bootstrap_stss_", dir=destination.parent) as temporary:
        staging = Path(temporary) / "upstream"
        completed = subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(staging)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if completed.returncode:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"Could not clone upstream STSS: {detail}")
        git_output(staging, "checkout", "--detach", UPSTREAM_COMMIT)
        validate_checkout(staging)
        staging.rename(destination)

    create_runtime_bin(destination)

    print(f"bootstrap_ok=created destination={destination}")
    print(f"upstream_commit={UPSTREAM_COMMIT}")
    for relative_path, blob in PINNED_ASSET_BLOBS.items():
        print(f"verified_asset={relative_path} git_blob={blob}")
    print(f"runtime_bin={runtime_bin_directory(destination)}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fetch the pinned original STSS checkout into an ignored local runtime directory."
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=default_destination(),
        help=f"Ignored local checkout directory (default: {default_destination()})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate an existing checkout without downloading or modifying anything.",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    destination = args.destination.expanduser().resolve()
    if args.check:
        validate_checkout(destination)
        validate_runtime_bin(destination)
        print(f"bootstrap_check=passed destination={destination}")
        return 0
    clone_and_publish(destination)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"bootstrap_error={type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1)
