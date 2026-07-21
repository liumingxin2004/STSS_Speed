#!/usr/bin/env python3
"""Verify that every command-line entry point parses and renders help."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


DEFAULT_STSS_DIR = Path(__file__).resolve().parents[1] / ".stss_speed" / "upstream"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stss-dir",
        type=Path,
        default=DEFAULT_STSS_DIR,
        help=f"STSS source directory (default: {DEFAULT_STSS_DIR})",
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    scripts = sorted((repo / "scripts").glob("*.py"))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(args.stss_dir) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    failures = []
    for script in scripts:
        print(f"checking_help={script.name}", flush=True)
        try:
            completed = subprocess.run(
                [sys.executable, str(script), "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                check=False,
                timeout=60,
            )
        except subprocess.TimeoutExpired:
            failures.append(
                {
                    "script": script.name,
                    "exit_code": "timeout",
                    "stderr": "did not finish --help within 60 seconds",
                }
            )
            continue
        if completed.returncode or "usage:" not in completed.stdout.lower():
            failures.append(
                {
                    "script": script.name,
                    "exit_code": completed.returncode,
                    "stderr": completed.stderr[-1000:],
                }
            )
        else:
            print(f"help_ok={script.name}")
    if failures:
        for failure in failures:
            print(f"help_failed={failure}", file=sys.stderr)
        return 1
    print(f"cli_help_checks={len(scripts)} status=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
