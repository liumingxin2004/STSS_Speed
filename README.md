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

### Native WSL video demo / 原生 WSL 演示

After cloning the repository in a WSL shell that already has Conda, run one presentation-friendly command:

```bash
bash scripts/demo_clean_environment.sh
```

It creates a unique Conda environment, bootstraps STSS, checks runtime dependencies and all public CLIs, then runs the no-data smoke test. It keeps that environment for inspection and prints its exact cleanup command. To make the same invocation remove only its own new environment after a successful test, add `--cleanup`.

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

Completion requires matching requested/downloaded assemblies, complete valid cache coverage, successful worker exits, equal result-row and hit counts, and zero network/cache anomalies.

## Aggregate performance / 聚合性能

The orchestration was used to substantially improve throughput at a 6,000-sample scale. The STSS stage completed in 2,602.406 seconds (43 minutes 22 seconds): **2.306 genomes/second** or **138.334 genomes/minute**. Compared with an earlier 500-sample offline pilot that measured 0.253 genomes/second, this is a **9.11× observed throughput increase**. This is a cross-run measurement, not a controlled same-input serial benchmark, so it should not be interpreted as a universal speedup factor.

该编排在 6,000 个样本规模的实践中实现了显著提速。STSS 阶段耗时 2,602.406 秒（43 分 22 秒），吞吐量为 **2.306 个基因组/秒**或 **138.334 个基因组/分钟**。相对于较早的 500 样本离线试运行（0.253 个基因组/秒），观测到的吞吐量提升为 **9.11 倍**。这是跨运行的实测吞吐量比较，而非同一输入下严格的串行基准，因此不应解读为普适的固定加速倍数。

To protect research data, this repository deliberately contains no sample identifiers, assembly accessions, genome or GBFF metadata, cache contents, hit rows, timing measurements beyond the aggregate values above, result hashes, or validation reports.

为保护研究数据，本仓库不包含任何样本标识符、assembly accession、基因组或 GBFF 元数据、缓存内容、命中行、除上述聚合指标外的耗时数据、结果哈希或验证报告。

## Development with Codex and GPT-5.6 / 使用 Codex 与 GPT-5.6 开发

The research problem, large-scale analysis goal, and core workflow logic were defined by the author, a bioinformatics engineer working with large biological datasets. Codex powered by GPT-5.6 was used as an engineering collaborator: it helped implement and review the orchestration scripts, improve failure isolation, add runtime and validation checks, document reproducible commands, and run small-scale verification. The author retained responsibility for the scientific scope, system decisions, performance interpretation, and protection of unpublished models and research data.

研究问题、大规模分析目标与核心流程逻辑由作者提出。作者是一名从事大规模生物数据分析的生物信息工程师。由 GPT-5.6 驱动的 Codex 作为工程协作工具，用于实现和审查编排脚本、改善故障隔离、加入运行时和验证检查、编写可复现命令、以及进行小规模验证。作者始终负责科学边界、系统决策、性能解读以及未公开模型与研究数据的保护。

## Runtime assets and attribution / 运行资产与归属

The bootstrap is pinned to `kew222/Self-Targeting-Spacer-Searcher@9e5d560ffb6100c5c28b46e71dae0bcde7e533e2` and verifies the original Cas HMM, repeat HMM, and `CRISPR_definitions.py` before use. The upstream STSS project has no license declaration in its GitHub metadata at the time this repository was created; users must review upstream attribution and licensing before redistributing STSS itself.

This repository is intentionally limited to STSS_Speed orchestration code and documentation.
