# 模型评测结果快照

更新时间：**2026-10-19T19:53:34.509329+00:00**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**；SWE-Review Qwen3-30B-Instruct 子集官方 DA **87.2%（422/422）** | 精确镜像 TB2.1 首轮 **88/89 已判分、68 成功**，首轮未完成；SWE-Review 整体 RRR 尚未完成 |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）** | Pro Verified **94/731 已判分、61 成功**；DeepSWE 首轮 **71/113、24 成功**；精确镜像 TB2.1 首轮 **87/89 已判分、62 成功**，首轮未完成；精确镜像 TB2.1 第2轮 22/89 已判分、17 成功，未完成；SWE-Review 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 第1轮 **51/113**；DeepSWE 第2轮 **43/113**；DeepSWE 第3轮 **39/113**；精确镜像 TB2.1 第1轮 **70/89**；精确镜像 TB2.1 第2轮 **71/89**；精确镜像 TB2.1 第3轮 **69/89** | Pro Verified **730/731 已判分、451 成功** |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | 暂无完整 benchmark 分数 | Pro Verified **84/731 已判分**；指定精确镜像 TB2.1 首轮 **31/89 已判分、27 成功**，首轮未完成；DeepSWE 运行中；SWRBench 已在 2886 双节点生成 198/1000、裁判 198/1000；SWE-Review 已预建 96 个任务镜像，最终分数待完成 |

**SWE-Review 的最终子集 DA。** Muse NVFP4 的 Qwen3-30B-Instruct 组 422 题全部有规范终态记录，官方 `compute_da.py` 得 **87.2%**（368 个可解析决定，54 个模型无有效决定）；将无有效决定按 0.5 计的 `DA_total_50` 为 **82.5%**。[逐题哈希与评分源码核验](evidence/swe_review_complete_split_da.json)可复查。另两组仍未完整，原始生成模型修复与判分尚未产生 RRR，因此没有可汇报的 SWE-Review 整体最终 RRR。

[SWE-Review 控制器核验](evidence/swe_review_recovery_control.json)确认旧队列于 03:17 UTC 中断：11 题从未领取、23 题虽被领取却没有任何原生题目目录；这 34 题已拆成互不重叠的两条续跑队列，继续用同一 Muse NVFP4 模型。另有 16 题留下部分模型输出：其中 10 题的 agent 结束步骤及原生验证报告、reward 都已保存，只缺 Harbor 汇总文件，原结果保留且未重抽；其余 6 题无最终评审报告，已另列基础设施中断补测。旧状态文件中的 healthy 是停机前的记录，不能当作当前运行状态。

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **63/85**、**59/76**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。精确镜像首轮只判分 88/89，不能当成最终准确率。已判分 68 题成功；若最后一题按协议得到有效评分，完整首轮将是 68/89（76.40%）或 69/89（77.53%），目前尚不能确定是哪一个。最后未判分的是 `mteb-leaderboard`：题卡 agent 超时 3600 秒，本轮协议乘数 12，agent 阶段上限 12 小时；运行中的原始首抽不提前记错。两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 5119 条原始模型响应、5 个运行中题目目录，最新响应时间为 2026-10-19T19:53:33+00:00；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。另有首轮 18 道尚未启动的题已按原配置哈希移交给 2867 的 NVFP4 副本和 2919 的评测器；只调整模型接口和任务并发数，保留原配置与结果。 2867 上独立的第 2/3 轮控制器状态为 active，阶段 running，当前批次 muse-nvfp4-tb-v1-exact-r2-completion-2866-b00；批次归属凭据阻止重复抽题。 新增 GPU 申请状态：2923 PENDING, 2924 PENDING, 2927 PENDING, 2928 PENDING。排队节点获配后监控器会启动同一 NVFP4 模型服务，并逐批加锁领取 b03、b05 中尚未启动的一批；early95 结束后腾出的 2812 最多可领取两批。原 CPU 评测器继续使用原题目和镜像，仅模型端点变化；若本地批次先启动，不会在其他节点重复抽题。首轮 b05 已在 GPU 2812、CPU 2922 完成 10 道原生题；归属凭据阻止重复抽题。GPU 2812 现以独立加锁接管运行未抽取的第 2/3 轮批次 muse-nvfp4-tb-v1-exact-r2-completion-2866-b01；仅改变模型端点。另有四个排队 GPU 节点获配后只领取第 2/3 轮尚未启动的批次；逐批文件锁和接管凭据阻止原控制器重复抽题，实际配置仅修改模型端点。

GPU 2812 的第二个控制器槽在 b01 最后一题仍运行时领取了未抽样的精确镜像第 2 轮 b02 批次；两条控制器共用已固定的 NVFP4 服务，各批次并发 2 题，服务上限为 8 个请求。[控制器源码](protocol/muse_nvfp4_exact_future_round_controller_20261019.py)使用独立槽锁和原有逐批原子领取；b02 接管凭据及原始/实际配置哈希收录于原始输入输出快照。首轮题目及已抽样的第 2 轮题目均未重抽。

Opus 4.7 Pro 只统计原始运行的 731 道题；同一补丁的纯验证重试单独留证，不能增加首轮题数或成功数。原始运行仍有 1 题在两次 3600 秒验证超时后缺少有效评分。独立节点补验未得到已核对的原生评分，需进一步检查。

**超时判分说明。** Muse 精确镜像已判分题目中有 8 题达到协议规定的 agent 时限后仍得到 verifier 分数；逐题审计保留超时标记，首轮不重抽这些题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 8 条、Muse BF16 的 2 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 `break-filter-js-from-html`, `configure-git-webserver`, `fix-code-vulnerability`, `fix-git`, `largest-eigenval`, `password-recovery`, `sqlite-db-truncate`, `winning-avg-corewars`；逐题核查记录了 verifier 日志探查、向 `/tests/filter.py` 复制公开文件或计时篡改；已检查的 verifier 探查输出没有确认获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval` 都通过修改计时函数、拖慢参考特征值求解器拿到原始 reward 1；原始分数保留，NVFP4 的[最终轨迹审计](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)有哈希锚定，但这两条高分不能当作未经篡改的加速证据。此前的 NVFP4 [`db-wal-recovery` 宿主边界探查预警](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)现已有终态：agent 运行 10800 秒后超时，原始奖励为 0。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)将该轨迹排除出干净训练数据；抽查输出未证明成功越过宿主边界，原始评测结果保持不变。关键词未命中也不代表轨迹已获干净认证。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)还标记了 Opus 4.7 在 `break-filter-js-from-html` 上对不存在的 `/tests` 的探查，以及 Beam BF16 在同题中把公开的过滤器临时复制到 `/tests/filter.py`、在判分前删除的行为；检查到的输出均未确认获得隐藏答案，两条轨迹暂不作为干净训练数据。Opus `torch-pipeline-parallelism` 的关键词命中只是列举 Python 可执行文件。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 403 个归档，SWE-Review 的 `*_review_full_io.tar.zst` 含 OpenHands completions；`*_review_verifier.tar.zst` 含原生验证器的评审报告、判分报告和 reward，其中包括 10 道缺 Harbor 汇总文件但已完成原生验证的 Muse 题。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 403/403**，逐项核验见 `evidence/release-assets-verification.json`。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **4166/4167 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **779/779 条含非空 thinking**。

[BF16 2886 双节点部署核验](evidence/muse_bf16_2886_deployment_audit.json)记录两台节点各 78 个固定权重文件的校验、SGLang 镜像版本、16 卡 NCCL/EFA 预检、BF16 接口，以及与正式评测分开的工具调用和 thinking 往返检查；这不是 benchmark 成绩。

BF16 SWRBench 的[逐题源数据、生成、GPT-5.5 裁判及原始回复归档清单](input_output/archive_manifests/muse_bf16_swr.json)指向 GitHub Release 资产；后续 `muse_bf16_swr_delta_*` 归档按时间覆盖仍在增长的同路径文件。

[BF16 SWE-Review 输入归档](input_output/archive_manifests/muse_bf16_review_inputs.json)保存了 96 道已准备题目的模型可见任务卡、指令、Dockerfile、公开题目数据，以及队列与镜像记录；不含隐藏解法和测试。正式轨迹与判分将在任务完成后另行归档。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `opus47_exact_tb_live_20261019T165447Z.tar.zst`（267 个终态结果）和 `beam_bf16_exact_tb_live_20261019T195034Z.tar.zst`（109 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

[Opus 4.7 第 2 轮核验](evidence/opus47_exact_round2_audit.json)和[第 3 轮核验](evidence/opus47_exact_round3_audit.json)按相同规则逐题检查后续轮次。三轮各 89 题均已完整且核验通过：**70/89、71/89、69/89**，三轮均值 **210/267 = 78.65%**。

Beam 精确镜像 TB 第 2 轮现由 2887 上核验过的 BF16 副本独立执行，第 1 轮继续使用原接口。[接管凭据](evidence/beam_exact_r23_2887_handoff.json)固定模型版本、镜像、原始及有效配置哈希和轮次归属；第 2 轮逐题只计一次，未满 89 题不报告整轮准确率。

第 2 轮 Muse NVFP4 的成功轨迹 `adaptive-rejection-sampler`, `break-filter-js-from-html` 曾探查 verifier 目录；已检查的返回为空，未证实获得隐藏答案。原始 reward 保留，轨迹暂不进入干净训练数据，见[哈希锚定核查](evidence/exact_tb_integrity_manual_notes.json)和[命令筛查](evidence/exact_tb_integrity_screen.json)。

[Opus 4.7 第 3 轮 thinking 传输核查](evidence/opus47_r3_thinking_transport_audit.json)生成于 2026-10-19T16:53:10.951953+00:00，覆盖 89 道终态题：1911 条归档回复中 822 条有可读 thinking，1084 条用量显示 reasoning token 为零，另 5 条虽计入 reasoning token，但上游原始流也没有可读 thinking，仅有签名。后者不能作为带完整 thinking 的训练样本。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `opus47_legacy_delta_20261019T194133Z.tar.zst`、`beam_legacy_delta_20261019T194142Z.tar.zst`、`muse_bf16_delta_20261019T194146Z.tar.zst`；截止时间和文件范围见各自清单。
