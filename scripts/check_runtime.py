#!/usr/bin/env python3
"""Validate the local STSS_Speed runtime without changing any files."""

from __future__ import annotations

import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

from bootstrap_upstream_stss import default_destination, validate_checkout, validate_runtime_bin


COMMANDS = {
    "git": ["--version"],
    "blastn": ["-version"],
    "hmmscan": ["-h"],
    "nhmmscan": ["-h"],
    "clustalo": ["--version"],
    "java": ["-version"],
    "datasets": ["version"],
}


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Check STSS_Speed dependencies and the pinned upstream STSS checkout."
    )
    parser.add_argument(
        "--stss-dir",
        type=Path,
        default=default_destination(),
        help=f"Pinned STSS checkout directory (default: {default_destination()})",
    )
    return parser.parse_args(argv)


def check_command(name: str, arguments: list[str]) -> str | None:
    executable = shutil.which(name)
    if not executable:
        return f"missing command: {name}"
    completed = subprocess.run(
        [executable, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return f"unusable command: {name} ({detail[:240]})"
    return None


def main(argv=None) -> int:
    args = parse_args(argv)
    failures: list[str] = []

    try:
        validate_checkout(args.stss_dir)
        validate_runtime_bin(args.stss_dir)
        print(f"upstream_checkout=ok path={args.stss_dir.resolve()}")
    except Exception as error:
        failures.append(f"upstream checkout: {error}")

    for module_name in ("Bio", "requests"):
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", "installed")
            print(f"python_module=ok name={module_name} version={version}")
        except Exception as error:
            failures.append(f"python module {module_name}: {error}")

    try:
        bio = importlib.import_module("Bio")
        if getattr(bio, "__version__", None) != "1.79":
            failures.append(
                f"Biopython version must be 1.79, found {getattr(bio, '__version__', 'unknown')}"
            )
    except Exception:
        pass

    for name, arguments in COMMANDS.items():
        failure = check_command(name, arguments)
        if failure:
            failures.append(failure)
        else:
            print(f"command=ok name={name}")

    if failures:
        for failure in failures:
            print(f"runtime_check_failed={failure}", file=sys.stderr)
        return 1
    print("runtime_check=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
