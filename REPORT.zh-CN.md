# 模型评测结果快照

更新时间：**2026-10-19T10:45:24.528606+00:00**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）** | 精确镜像 TB2.1 首轮 **58/89 已判分、47 成功**，首轮未完成；SWE-Review 三组尚无完整官方 RRR |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）** | Pro Verified **64/731 已判分、39 成功**；DeepSWE 首轮 **57/113、16 成功**；精确镜像 TB2.1 首轮 **56/89 已判分、40 成功**，首轮未完成；SWE-Review 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 首轮 **51/113（45.13%）**；精确镜像 TB2.1 首轮 **70/89（78.65%）**，首轮完整 | Pro Verified **672/731 已判分、416 成功** |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | 暂无完整 benchmark 分数 | Pro Verified **40/731 已判分**；指定精确镜像 TB2.1 首轮 **11/89 已判分、9 成功**，首轮未完成；DeepSWE 运行中 |

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **63/85**、**59/76**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。精确镜像首轮只判分 58/89，不能当成最终准确率。两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 2615 条原始模型响应、8 个运行中题目目录，最新响应时间为 2026-10-19T10:45:08+00:00；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。另有首轮 18 道尚未启动的题已按原配置哈希移交给 2867 的 NVFP4 副本和 2919 的评测器；只调整模型接口和任务并发数，保留原配置与结果。 新增 GPU 申请状态：2923 PENDING, 2924 PENDING, 2927 PENDING, 2928 PENDING。排队节点获配后监控器会启动同一 NVFP4 模型服务，并逐批加锁领取 b03、b05 中尚未启动的一批；early95 结束后腾出的 2812 最多可领取两批。原 CPU 评测器继续使用原题目和镜像，仅模型端点变化；若本地批次先启动，不会在其他节点重复抽题。

**超时判分说明。** Muse 精确镜像已判分题目中有 4 题达到协议规定的 agent 时限后仍得到 verifier 分数；逐题审计保留超时标记，首轮不重抽这些题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 6 条、Muse BF16 的 2 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 `break-filter-js-from-html`, `configure-git-webserver`, `fix-code-vulnerability`, `fix-git`, `password-recovery`, `sqlite-db-truncate`；逐题核查记录了 verifier 日志探查或向 `/tests/filter.py` 复制公开文件，已检查的输出没有确认获得隐藏答案。BF16 的 `largest-eigenval` 明确通过修改计时函数和拖慢参考求解器操纵测速；原始 reward 保留，但不能当作未经篡改的加速证据。另有两份 NVFP4 判分前预警，分别记录了[计时篡改](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)和 [`db-wal-recovery` 对宿主边界的探查](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)；这些预警并非最终分数，也不证明边界探查成功。关键词未命中也不代表轨迹已获干净认证。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 148 个归档，优先使用 SWE-Review 的 `*_review_full_io.tar.zst`（含 OpenHands completions）。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 148/148**，逐项核验见 `evidence/release-assets-verification.json`。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **2076/2077 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **238/238 条含非空 thinking**。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `opus47_exact_tb_live_20261019T104317Z.tar.zst`（177 个终态结果）和 `beam_bf16_exact_tb_live_20261019T103623Z.tar.zst`（56 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `opus47_legacy_delta_20261019T103801Z.tar.zst`、`beam_legacy_delta_20261019T103815Z.tar.zst`、`muse_bf16_delta_20261019T104333Z.tar.zst`；截止时间和文件范围见各自清单。
