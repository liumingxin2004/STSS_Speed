# STSS_Speed

STSS_Speed is a checkpointed strict-offline batch runner for [Self-Targeting Spacer Searcher (STSS)](https://github.com/kew222/Self-Targeting-Spacer-Searcher). It turns local FNA files and matching GBFF annotations into a validated per-contig cache, runs isolated STSS workers with CPU affinity, and verifies every checkpoint before aggregation.

STSS_Speed does **not** publish STSS itself, genome data, GBFF files, caches, logs, results, custom HMMs, or updated classifier rules. It obtains a pinned original STSS checkout locally after cloning.

中文简介：STSS_Speed 是面向大规模 STSS 自我靶向 spacer 搜索的严格离线编排层。它不公开自定义 HMM、更新后的分类规则或任何输入/结果数据；clone 后通过 bootstrap 获取并校验固定版本的原版 STSS。

Read the bilingual [project story](docs/project-story.md) for the motivation, lessons, construction, and operational challenges behind the pipeline.

## Quick start / 快速开始

Run these commands in WSL. The Conda environment supplies the Python and command-line dependencies; the bootstrap command retrieves the pinned upstream STSS source into an ignored local directory.

```bash
git clone https://github.com/liumingxin2004/STSS_Speed.git
cd STSS_Speed
conda env create -f environment.yml
conda activate stss-speed
python scripts/bootstrap_upstream_stss.py
python scripts/check_runtime.py
```

The bootstrap is intentionally idempotent. It keeps the upstream checkout unchanged and creates a separate ignored `.stss_speed/bin/` directory of links to the locally installed BLAST, HMMER, Clustal Omega, and CRT runtime assets. A modified or mismatched checkout is rejected and never overwritten.

## Offline workflow / 离线流程

Every run must use a new run root and output root. Input FNA files are treated as read-only. The following abbreviated example uses explicit executable paths only where they are environment-specific.

```bash
RUN_ROOT=/path/to/new_run
FNA_DIR=/path/to/fna

python scripts/prepare_batch.py \
  --source-fna-dir "$FNA_DIR" \
  --test-root "$RUN_ROOT/work" \
  --count 500 --batch-size 100

python scripts/download_rehydrate.py \
  --test-root "$RUN_ROOT/work" \
  --datasets "$(command -v datasets)" \
  --download-concurrency 2 --rehydrate-workers 5

python scripts/verify_download.py --test-root "$RUN_ROOT/work"
python scripts/split_gbff.py --test-root "$RUN_ROOT/work" --workers 8
python scripts/verify_cache.py --test-root "$RUN_ROOT/work"

python scripts/run_batch.py \
  --test-root "$RUN_ROOT/work" \
  --output-root "$RUN_ROOT/results" \
  --python "$(command -v python)" \
  --wrapper scripts/offline_stss_wrapper.py \
  --workers 4
```

`run_batch.py` and `run_checkpoints.py` use `.stss_speed/upstream/` by default after bootstrap. Advanced users may override that source with `--stss-dir /path/to/a/validated/STSS`, but STSS_Speed never downloads or copies custom HMMs or classifier scripts into the repository.

Before STSS starts, require zero invalid/conflicting/missing cache records and complete FNA-contig coverage. STSS always skips PHASTER, blocks Entrez/CDD/other HTTP paths, and rejects `Cas_gene_distance=0`.

## Checkpoints and validation / 检查点与验证

For large runs, prepare immutable checkpoints and run them sequentially. A failed checkpoint stops later checkpoints; preserve the failed directory and retry only in a new workspace.

```bash
python scripts/prepare_checkpoints.py --run-root "$RUN_ROOT" --chunk-size 500
python scripts/run_checkpoints.py \
  --master "$RUN_ROOT/work/config/stss_checkpoints.tsv" \
  --python "$(command -v python)" \
  --run-batch scripts/run_batch.py \
  --wrapper scripts/offline_stss_wrapper.py \
  --workers 6 --cpus-per-worker 5

python scripts/aggregate_checkpoints.py \
  --master "$RUN_ROOT/work/config/stss_checkpoints.tsv" \
  --final-root "$RUN_ROOT/results" --output-prefix stss
```

Completion requires matching requested/downloaded assemblies, complete valid cache coverage, successful worker exits, equal result-row and hit counts, and zero network/cache anomalies. See the [validated 6,000-genome profile](docs/validated-6000-run.md).

## Runtime assets and attribution / 运行资产与归属

The bootstrap is pinned to `kew222/Self-Targeting-Spacer-Searcher@9e5d560ffb6100c5c28b46e71dae0bcde7e533e2` and verifies the original Cas HMM, repeat HMM, and `CRISPR_definitions.py` before use. The upstream STSS project has no license declaration in its GitHub metadata at the time this repository was created; users must review upstream attribution and licensing before redistributing STSS itself.

This repository is intentionally limited to STSS_Speed orchestration code and documentation.
