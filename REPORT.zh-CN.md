# 模型评测结果快照

更新时间：**2026-10-19T05:38:20.151850+00:00**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）** | 精确镜像 TB2.1 首轮 **21/89 已判分、19 成功**，首轮未完成；SWE-Review 三组尚无完整官方 RRR |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）** | Pro Verified **44/731 已判分、32 成功**；DeepSWE 首轮 **46/113、10 成功**；精确镜像 TB2.1 首轮 **34/89 已判分、26 成功**，首轮未完成；SWE-Review 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 首轮 **51/113（45.13%）** | Pro Verified **476/731 已判分、302 成功**；精确镜像 TB2.1 首轮 **87/89 已判分、70 成功**，首轮未完成 |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | 暂无完整 benchmark 分数 | Pro Verified **11/731 已判分**；**旧缓存镜像** TB2.1 首轮 **4/89 已判分**；精确镜像尚未启动，DeepSWE 运行中 |

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **63/85**、**59/76**，尚无三轮均值。精确镜像首轮只判分 21/89，不能当成最终准确率。两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 395 条原始模型响应、8 个运行中题目目录，最新响应时间为 2026-10-19T05:37:40+00:00；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；新增 GPU 申请状态：2923 PENDING, 2924 PENDING, 2927 PENDING, 2928 PENDING。监控器会在获配后自动启动同一 NVFP4 模型服务，题目移交仍需核对互不重叠的任务清单。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 38 个归档，优先使用 SWE-Review 的 `*_review_full_io.tar.zst`（含 OpenHands completions）。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 38/38**，逐项核验见 `evidence/release-assets-verification.json`。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `opus47_exact_tb_live_20261019T051949Z.tar.zst`（87 个终态结果）和 `beam_bf16_exact_tb_live_20261019T052008Z.tar.zst`（34 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `opus47_legacy_delta_20261019T053244Z.tar.zst`、`beam_legacy_delta_20261019T053138Z.tar.zst`、`muse_bf16_delta_20261019T053146Z.tar.zst`；截止时间和文件范围见各自清单。
