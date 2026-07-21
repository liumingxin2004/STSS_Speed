#!/usr/bin/env bash
set -euo pipefail

# Video-friendly native WSL demonstration.  Run this script from a freshly
# cloned STSS_Speed checkout after installing Conda in WSL.
#
# Default behavior keeps the new environment for inspection.  --cleanup
# removes only the unique environment created by this invocation after all
# checks pass.  A failed run always keeps its environment and artifacts.

cleanup=false
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--cleanup" ) ]]; then
    echo "Usage: bash scripts/demo_clean_environment.sh [--cleanup]" >&2
    exit 2
fi
if [[ $# -eq 1 ]]; then
    cleanup=true
fi

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
stamp="$(date +%Y%m%d_%H%M%S)"

if [[ -n "${CONDA_EXE:-}" ]]; then
    conda_exe="$CONDA_EXE"
    if [[ ! -x "$conda_exe" ]]; then
        echo "CONDA_EXE is not executable: $conda_exe" >&2
        exit 2
    fi
else
    command -v conda >/dev/null 2>&1 || {
        echo "Conda is not available in this WSL shell. Install Conda, then retry." >&2
        exit 2
    }
    conda_exe="conda"
fi

conda_base="$("$conda_exe" info --base)"
env_prefix="${HOME}/.conda/envs/stss_speed_demo_${stamp}"
scratch_root="${repo_dir}/validation_scratch_${stamp}"

if [[ -e "$env_prefix" || -e "$scratch_root" ]]; then
    echo "Refusing to reuse an existing demo path." >&2
    exit 2
fi

echo "== STSS_Speed native WSL demo =="
echo "repository=${repo_dir}"
echo "commit=$(git -C "$repo_dir" rev-parse --short HEAD)"
echo "environment=${env_prefix}"

echo "[1/5] Creating a new Conda environment"
"$conda_exe" env create --prefix "$env_prefix" --file "$repo_dir/environment.yml"

source "${conda_base}/etc/profile.d/conda.sh"
conda activate "$env_prefix"

echo "[2/5] Bootstrapping the pinned original STSS release"
python "$repo_dir/scripts/bootstrap_upstream_stss.py"

echo "[3/5] Checking Python packages and command-line tools"
python "$repo_dir/scripts/check_runtime.py"

echo "[4/5] Checking all public command-line interfaces"
python "$repo_dir/tests/check_cli_help.py"

echo "[5/5] Running the public no-data smoke test"
python "$repo_dir/tests/smoke_prepare.py" --scratch-root "$scratch_root"

echo "demo_status=passed"
echo "test_artifacts=${scratch_root}"

if [[ "$cleanup" == true ]]; then
    conda deactivate
    echo "Removing only this demo environment"
    "$conda_exe" env remove --prefix "$env_prefix" --yes
    [[ ! -e "$env_prefix" ]] || { echo "Environment removal failed: $env_prefix" >&2; exit 1; }
    echo "demo_environment_removed=passed"
else
    echo "Environment retained for the video: ${env_prefix}"
    echo "After recording, remove it with:"
    echo "${conda_exe} env remove --prefix ${env_prefix} --yes"
fi
