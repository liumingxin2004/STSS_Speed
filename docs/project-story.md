# STSS_Speed project story / 项目故事

## Inspiration / 激励

**中文：** STSS_Speed 的起点不是“怎样让一次 STSS 运行更快”，而是“怎样让一次大规模自我靶向 spacer 搜索值得被相信”。当样本从单个基因组扩大到数千个时，真正困难的不再只是计算时间，而是每一个 FNA、GBFF、缓存记录、检查点和结果行能否被追溯与复核。这个项目由此把速度定义为可靠地完成更多经过验证的样本，而不是单纯增加并发数。

**English:** STSS_Speed began with a question beyond raw throughput: how can a large STSS run remain trustworthy? At thousands of genomes, reproducibility, provenance, and verifiable completion matter as much as elapsed time. Here, speed means completing more validated samples reliably, not merely increasing concurrency.

## What we learned / 我们学到的

**中文：** FNA 与 GBFF 的对应关系必须在运行 STSS 前被严格证明；否则看似正常的结果可能建立在缺失或错配注释之上。网络下载需要可恢复的失败边界，缓存必须检测无效记录、冲突和 contig 覆盖率，CPU 则需要亲和性分配以避免 Clustal Omega 等工具过度并行。零命中同样是有效结果，但前提是输入、worker 退出码和离线网络计数都被验证。

**English:** FNA-to-GBFF correspondence must be proven before STSS runs. Download failures need recoverable boundaries, caches need invalid/conflict/coverage checks, and CPU affinity prevents oversubscription by tools such as Clustal Omega. A zero-hit run is still a result only when inputs, worker exits, and offline network counters have been verified.

## How the project was built / 项目如何构建

**中文：** 流程从确定性的 FNA manifest 开始，接着以有限并发下载和 rehydrate 获取 GBFF。每个 GBFF 被拆分为单 contig GenBank 缓存，并在无效、冲突和缺失均为零后才进入 STSS。STSS 使用隔离 worker、CPU 亲和性和不可变检查点运行；每个检查点失败即停止后续步骤，汇总时再次核对样本数、命中行数、缓存事件和网络防护计数。

**English:** The workflow starts with a deterministic FNA manifest, uses bounded download/rehydration, then publishes a per-contig GenBank cache only after invalid, conflict, and missing counts are zero. STSS runs in isolated workers with CPU affinity and immutable checkpoints. Aggregation rechecks sample counts, hit rows, cache events, and network-guard counters.

## Challenges and safeguards / 挑战与防护

**中文：** 实际运行遇到过连接重置、超时、部分 GBFF、WSL 挂载波动和资源竞争。应对方式是保留失败现场、使用新的重试目录、将下载与计算分阶段、并只在缓存完整后启动 STSS。另一个重要挑战是公开可复现与未公开模型保护之间的平衡：本仓库不包含自定义 HMM 或更新后的分类规则，而是通过固定上游 commit 获取原始 STSS 资产并进行指纹校验。

**English:** Real runs faced connection resets, timeouts, partial GBFF packages, WSL mount instability, and resource contention. The safeguards are preserved failures, new retry directories, staged execution, and a complete-cache gate. The repository also balances reproducibility with model protection: it never distributes custom HMMs or updated classifiers, and instead bootstraps verified original STSS assets from a pinned upstream commit.

## Attribution and scope / 归属与范围

STSS_Speed is an orchestration layer around [Self-Targeting Spacer Searcher (STSS)](https://github.com/kew222/Self-Targeting-Spacer-Searcher). The original STSS source remains an external dependency. Users obtain it locally with the bootstrap command and should review the upstream project’s attribution and licensing status before redistribution.
