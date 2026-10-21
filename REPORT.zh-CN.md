# 模型评测结果快照

Muse NVFP4 精确镜像 TB2.1 第 5 轮在 2899 上独立抽样 89 题；[固定题目和端点凭据](evidence/muse_nvfp4_r5_progress.json)现记录 **21/89 题原生判分、17 题成功**。全部判分和轨迹审查完成前不报告第 5 轮准确率。[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)标记了成功题 `count-dataset-tokens` 探查评测或 agent 日志。原始 reward 保留，轨迹暂不进入干净训练集；目前不能据此断定读到了隐藏答案或修改了评分。


Muse NVFP4 精确镜像 TB2.1 第 4 轮在 2902 上独立抽样 89 题；[固定题目和端点凭据](evidence/muse_nvfp4_r4_progress.json)现记录 **31/89 题原生判分、27 题成功**。[已发布回复的 thinking 核验](evidence/muse_nvfp4_r4_thinking_audit.json)覆盖其所引用归档内的已判分题目；新增题目待下一次归档核验。全部判分和轨迹审查完成前不报告整轮准确率，既有前三轮统计保持独立。[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)标记了成功题 `fix-ocaml-gc` 探查评测或 agent 日志。原始 reward 保留，轨迹暂不进入干净训练集；目前不能据此断定读到了隐藏答案或修改了评分。


更新时间：**2026-10-21T11:54:39.396208+00:00**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Releases](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**；SWE-Review 三组官方 DA：GLM5 **75.7%（500 题）**、Coder **81.2%（462 题）**、Instruct **87.2%（422 题）**；SWE-Review Instruct 组官方 RRR **45.5%**；Coder 组官方 RRR **59.7%**；GLM5 组官方 RRR **75.0%**；整体官方 RRR **60.9%**；精确镜像 TB2.1 第1轮 **68/89（76.40%）**；精确镜像 TB2.1 第2轮 **65/89（73.03%）**；精确镜像 TB2.1 第3轮 **70/89（78.65%）**；三轮原始 reward 均值 **203/267（76.03%）** | Pro Verified 独立第二轮第 0 分片 **36/183 已判分、26 成功**，整轮 731 题尚未完成；SWE-Review 整体 RRR 已完成 |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）**；SWE-Review 三组官方 DA：GLM5 **73.0%（500 题）**、Coder **77.2%（462 题）**、Instruct **86.5%（422 题）**；SWE-Review Instruct 组官方 RRR **42.7%**；Coder 组官方 RRR **59.1%**；GLM5 组官方 RRR **74.2%**；整体官方 RRR **59.5%**；精确镜像 TB2.1 首轮 **62/89（69.66%）**，首轮完整；精确镜像 TB2.1 第2轮基础设施补测后 **63/89** | Pro Verified **706/731 已判分、384 成功**；DeepSWE 首轮 **112/113、47 成功**；精确镜像 TB2.1 第3轮 75/89 已判分、48 成功，未完成；SWE-Review 三组及整体 RRR 已完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 第1轮 **51/113**；DeepSWE 第2轮 **43/113**；DeepSWE 第3轮 **39/113**；精确镜像 TB2.1 第1轮 **70/89**；精确镜像 TB2.1 第2轮 **71/89**；精确镜像 TB2.1 第3轮 **69/89** | Pro Verified **730/731 已判分、451 成功**；SWE-Review glm5_500 500/500 题终态、qwen3_coder_30b_500 462/462 题终态、qwen3_30b_instruct2507_500 422/422 题终态；Instruct 组官方 DA 86.3%，含 1 道事先声明的中断续测；RRR 未完成 |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | SWRBench GPT-5.5 裁判 **54.2%（1000/1000）**，PR 分类 F1 **0.4967** | Pro Verified **219/731 已判分**；指定精确镜像 TB2.1 首轮 **73/89 已判分、56 成功**，首轮未完成；DeepSWE 运行中；SWE-Review 原生任务终态 751/1384（GLM 256/500、Coder 242/462、Instruct 253/422），官方 DA/RRR 待完成；已预建 832 个任务镜像 |

Muse NVFP4 的 TB2.1 首轮 **68/89 是原生 verifier reward**。[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)确认其中 1 条成功轨迹通过操纵计时或参考计算取得奖励（`largest-eigenval`）。正在进行的 Muse BF16 首轮也有 1 条同类确认轨迹（`largest-eigenval`）。原始 reward 保留，轨迹已排除出干净训练数据；其他成功轨迹仍需完整核查，当前不报告“干净准确率”。

Opus 4.7 SWE-Review 使用未改动的官方题卡，每题仅一次评审抽样。[模型可见输入](input_output/archive_manifests/opus47_review_inputs.json)及[原生输出、逐次回复和轨迹](input_output/archive_manifests/opus47_review_full_io.json)已作为带 SHA 校验的 Release 资产保存。输出归档是运行中的局部快照，后续增量归档会续传；仅凭评审阶段结果不能报告 DA 或 RRR。

Muse BF16 原节点在 Pro、TB2.1、DeepSWE 运行中到期。[恢复审计](evidence/muse_bf16_2865_expiry_recovery.json)记录了原始及续跑 ID：**137 道已完成的 Pro 题仅复用一次**，原运行的 10 道失败题和 4 道中断题单独保留。当前 Pro 分数按原始题目 ID 合并续跑结果与互不重叠的直连结果。另有两道 TB 和两道 DeepSWE 的中断原始输入输出及轨迹，分别保存在已做 SHA 校验的 [TB](input_output/archive_manifests/muse_bf16_interrupted_tb_delta_20261020T072043Z.json) 与 [DeepSWE](input_output/archive_manifests/muse_bf16_interrupted_deep_delta_20261020T072043Z.json) 归档中；这些原记录尚未判分，不计为模型失败。

2869 转发节点到期后，[直连续跑清单](evidence/muse_bf16_2869_direct_resume_progress.json)另外声明了原轮次中没有原生结果的 Pro 560 题、TB2.1 16 题、DeepSWE 11 题。已完成的原生结果按原始题目 ID 合并进首轮分数，运行目录和旧轨迹仍分别保留；原始未判分记录不算模型失败。

[DeepSWE 端点故障清单](evidence/muse_bf16_deep_pre_model_endpoint_recovery_claim.json)另冻结了 17 条旧端点健康检查失败的原始记录：没有模型原始回复和轨迹，补丁为空。首个补跑中两题在模型调用前又被客户端依赖检查挡住，[原清单](evidence/muse_bf16_deep_initial_endpoint_recovery_claim.json)及轨迹均保留；现在的补跑接受任务镜像中已锁定的 LiteLLM 版本，仍保持所有已安装包版本。只有新补跑产生原生终态后，才逐题替换对应的未判分原记录。

[BF16 TB2.1 失败审计](evidence/muse_bf16_tb_ungraded_audit.json)逐题确认 30 条原记录没有模型回复或 agent 步骤，另两条中断记录已有真实模型输出。[预先声明的 30 题补跑清单](evidence/muse_bf16_tb_pre_model_recovery_claim.json)沿用指定任务镜像和生成参数，在已验证的 BF16 直连端点进行第一次真实抽样；两条已有输出的中断题不参与此次重采样。原文件继续保留，新结果产生原生终态后才按题目 ID 唯一计入首轮。

**SWE-Review 三组 DA 均已有封存收据。** 官方 `compute_da.py` 在 GLM5 460 个可解析决定上得 **75.7%**（500 题终态），Qwen3-Coder 420 个得 **81.2%**（462 题），Qwen3-30B-Instruct 368 个得 **87.2%**（422 题）。[逐题哈希和官方评分核验](evidence/swe_review_complete_split_da.json)覆盖全部三组。[新版任务准备收据审计](evidence/muse_swe_review_revision_v2_receipts.json)确认 GLM5 的 8 道、Coder 的 2 道只缺 Harbor 汇总：它们的真实原生报告参与 DA，标明用途的适配文件仅供官方修复任务生成，绝非模型结果。[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了 Instruct 组全部 266 条原始生成模型修订：**RRR 45.5%**，原始 baseline RR 27.5%，提升 18.0 个百分点。Coder 组也已核验 222 条原生修订：**RRR 59.7%**，baseline RR 50.9%，提升 8.9 个百分点。GLM5 组 **RRR 75.0%**。整体官方 **RRR 60.9%**。

[修订阶段基础设施审计](evidence/swe_review_revision_queue_recovery_20261020.json)记录了两种任务输入格式、准备错误，以及沙箱在首个模型回复前的连接超时；这些原生失败不计入模型成绩。随后两条合成 Harbor 任务经 Docker 宿主桥接地址完成模型生成、终端工具调用及原生验证，且不纳入 benchmark。四条正式生成补测队列已用[桥接地址 agent](protocol/muse_review_revision_v2/revision_agents_bridge_v4.py)和原任务输入启动，部分分组已完成。[原生实时判分审计](evidence/swe_review_revision_gateway_progress.json)显示 Muse Coder **222/222**、Muse Instruct **266/266**、Beam Coder **224/224**、Beam Instruct **279/279** 道修订已判分；只有分组内全部原生判分与已归档证据核验通过才报告该分组 RRR。[v3 评分脚本](protocol/muse_review_revision_v2/revision_score_v3.py)只读取修正后的桥接队列结果，将 Beam 的 5 份非法评审报告保留为模型失败，并逐项复现四组已封存 DA。

[Beam Coder 端口错误审计](evidence/beam_coder_pre_model_port_mismatch.json)保留了首批 16 道基础设施失败：沙箱放行 31411 端口，Qwen3-Coder 模型实际服务于 31410，因此均未收到模型回复或原生判分，不计入模型成绩。独立的[修正后 224 题队列](protocol/beam_review_revision_v2/beam_coder_portfix/queue-plan.json)放行 31410；其[独立合成预检](protocol/beam_review_revision_v2/beam_coder_portfix/synthetic-portfix-r2-passed.json)已完成模型生成和原生验证。合成输出不计入成绩，修正队列中的每道被拒绝 PR 只抽样一次。

[SWE-Review 控制器核验](evidence/swe_review_recovery_control.json)确认旧队列于 03:17 UTC 中断：11 题从未领取、23 题虽被领取却没有任何原生题目目录；这 34 题已拆成互不重叠的两条续跑队列，继续用同一 Muse NVFP4 模型。另有 16 题留下部分模型输出：其中 10 题的 agent 结束步骤及原生验证报告、reward 都已保存，只缺 Harbor 汇总文件，原结果保留且未重抽；其余 6 题无最终评审报告，已另列基础设施中断补测。旧状态文件中的 healthy 是停机前的记录，不能当作当前运行状态。

Beam SWE-Review 有[**7 份已抽样但 JSON 无法解析的报告**](evidence/beam_swe_review_malformed_reports.json)，旧任务准备控制器因此失败。[带源码哈希的新版本准备协议](protocol/beam_review_revision_v2/task-preparation-plan-v2.json)保留原始文件，并按官方生成器的缺失决定回退处理；当前阶段为 `all_revision_tasks_prepared`。另两组评审仍在继续。

Beam BF16 的 SWE-Review 三组已有[封存的官方 DA](evidence/swe_review_complete_split_da.json)：GLM5 **73.0%**、Coder **77.2%**、Instruct **86.5%**。Instruct 的 422 题终态中 379 个决定可解析；其中 5 份格式错误的原始报告保留，按模型无有效决定处理。[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了全部 279 条原始生成模型修订和未改动的官方分组指标：**RRR 42.7%**，原始 baseline RR 27.5%，提升 15.2 个百分点。Coder 组另有 **RRR 59.1%**，224 条原生修订已核验。GLM5 组 **RRR 74.2%**。整体官方 **RRR 59.5%**。

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **63/85**、**59/76**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。精确镜像首轮已完成：**68/89（76.40%）**。指定镜像的 Muse NVFP4 TB2.1 首轮已完成且逐题审计通过：**68/89（76.40%）**。切换节点前中断、未判分的原始尝试单独留存；余下首轮题目由互不重叠、逐批加锁的队列完成，没有重复计分。第 2/3 轮在已核验 NVFP4 端点上的完成状态、批次及归属凭据见[实时结果与恢复记录](results/scores.json)。额外 GPU 申请状态：2923 RUNNING, 2924 RUNNING, 2927 RUNNING, 2928 RUNNING。指定镜像、旧缓存镜像和 BF16 的成绩分别统计。

GPU 2812 的第二个控制器槽在 b01 最后一题仍运行时领取了未抽样的精确镜像第 2 轮 b02 批次；两条控制器共用已固定的 NVFP4 服务，各批次并发 2 题，服务上限为 8 个请求。[控制器源码](protocol/muse_nvfp4_exact_future_round_controller_20261019.py)使用独立槽锁和原有逐批原子领取；b02 接管凭据及原始/实际配置哈希收录于原始输入输出快照。首轮题目及已抽样的第 2 轮题目均未重抽。

Opus 4.7 Pro 只统计原始运行的 731 道题；同一补丁的纯验证重试单独留证，不能增加首轮题数或成功数。原始运行的 `element-hq` 与两次纯验证重试均在 3600 秒后超时；[Beam BF16 原始运行的同一道题](evidence/shared_element_hq_eval_timeout.json)也在原生 evaluate 阶段超时，两边原始结果都没有有效二元评分。这一共同现象不能证明根因，也不能判定任一模型在该题上成功或失败。独立节点补验未得到已核对的原生评分，需进一步检查。

**超时判分说明。** Muse 精确镜像已判分题目中有 9 题达到协议规定的 agent 时限后仍得到 verifier 分数；逐题审计保留超时标记，首轮不重抽这些题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 仅在全部原生判分和 Release 哈希验证后报告官方 RRR；未核验的已结束题数不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 9 条、Muse BF16 的 5 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 `break-filter-js-from-html`, `configure-git-webserver`, `fix-code-vulnerability`, `fix-git`, `headless-terminal`, `largest-eigenval`, `password-recovery`, `sqlite-db-truncate`, `winning-avg-corewars`；逐题核查记录了 verifier 与 agent 日志探查、向 `/tests/filter.py` 复制公开文件或计时篡改；已检查的日志探查输出没有确认获得隐藏答案。排除的 BF16 题目是 `configure-git-webserver`, `fix-git`, `hf-model-inference`, `largest-eigenval`, `password-recovery`，各题原因见逐题核查；新核查的 verifier 与宿主边界探查在已检查输出中未证实获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval` 都通过修改计时函数、拖慢参考特征值求解器拿到原始 reward 1；原始分数保留，NVFP4 的[最终轨迹审计](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)有哈希锚定，但这两条高分不能当作未经篡改的加速证据。此前的 NVFP4 [`db-wal-recovery` 宿主边界探查预警](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)现已有终态：agent 运行 10800 秒后超时，原始奖励为 0。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)将该轨迹排除出干净训练数据；抽查输出未证明成功越过宿主边界，原始评测结果保持不变。关键词未命中也不代表轨迹已获干净认证。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)还标记了 Opus 4.7 在 `break-filter-js-from-html` 上对不存在的 `/tests` 的探查，以及 Beam BF16 在同题中把公开的过滤器临时复制到 `/tests/filter.py`、在判分前删除的行为；检查到的输出均未确认获得隐藏答案，两条轨迹暂不作为干净训练数据。Opus `torch-pipeline-parallelism` 的关键词命中只是列举 Python 可执行文件。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 归档链共 1303 个归档，SWE-Review 的 `*_review_full_io.tar.zst` 含 OpenHands completions；`*_review_verifier.tar.zst` 含原生验证器的评审报告、判分报告和 reward，其中包括 10 道缺 Harbor 汇总文件但已完成原生验证的 Muse 题。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 1303/1303**，逐项核验见 `evidence/release-assets-verification.json`。

SWE-Review 原始生成模型的修订输入见 [Muse](input_output/archive_manifests/muse_review_revision_inputs.json) 和 [Beam](input_output/archive_manifests/beam_review_revision_inputs.json) 基础归档及按时间命名的增量归档；原生输出、completions、轨迹及 verifier 记录见独立的 [Muse](input_output/archive_manifests/muse_revision_review_full_io.json) 和 [Beam](input_output/archive_manifests/beam_revision_review_full_io.json) 归档链。[Release 覆盖审计](evidence/review_revision_release_coverage.json)给出当前各模型已准备及已进入桥接补测队列的任务卡数量，并确认这些输入与旧故障文件都在 SHA 校验通过的归档中。旧节点地址导致的首回复前失败与可判分的桥接补测分属不同路径；后续增量归档按时间覆盖仍在增长的文件。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **4819/4822 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

第 2 轮已有 **89 题终态、89 题原生判分、65 题成功**。原始 `password-recovery` 尝试在验证前失去 tmux 会话；[哈希锚定记录](evidence/muse_nvfp4_r2_password_recovery_ungraded.json)保留了原生异常、轨迹和 15 条模型原始回复，原尝试仍未判分。[单题基础设施补测声明](evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json)固定原题、镜像和采样设置，使用已核验的等价 NVFP4 副本；补测原生 reward 为 **1.0**。本轮该题最多计一个有效判分，不择优取样。

`password-recovery` 已判分补跑有[轨迹完整性警报](evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json)：31 次工具调用探查宿主挂载或块设备路径，其中 `nsenter` 返回权限不足。原始 reward 保留，但这条轨迹排除出干净训练集；所检查的输出不能证明成功进入宿主或读取隐藏答案。

`prove-plus-comm` 原始尝试在 agent 初始化时[超时](evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json)，模型没有产生回复，也没有原生判分。首次[已声明补跑](evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json)因服务进程缺少 API-key 环境变量，在模型首回复前再次失败且未判分；[故障记录](evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json)保留了原始证据。随后另行声明[服务环境修正](evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json)，其原生 reward 当前为 **1.0**。本题只允许修正后的首个有效原生判分填补缺失值；所有尝试均保留，不择优取样。

原 NVFP4 服务节点 2866 也开始领取第 2/3 轮尚未启动的批次。[节点就绪凭据](evidence/muse_nvfp4_local2866_ready.json)、[实时路由审计](evidence/muse_nvfp4_local2866_route_audit.json)及[控制器代码](protocol/muse_nvfp4_local2866/README.md)显示，本次快照已有 1 条加锁路由，独占 10 道不同题；只按原生结果统计完成题。

第 2 轮**原始首抽**目前有 89 题终态、75 题有效原生判分、54 题成功；上面的修复后统计只补入已单独声明的有效补跑判分。`pytorch-model-cli` 的[原尝试](evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json)在共用 500 GB Docker 底盘占满时失去 tmux 通道，原始 reward 未知。[单次隔离存储补跑](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json)改用 CPU 节点 2922，当前原生 reward 为 **1.0**。[局部命令与 thinking 核验](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json)显示原始回复 13/13 条含推理，40 条 bash 命令中未见访问裁判、隐藏测试或 reward 的迹象；这不等于完整排除 reward hacking。原始首抽仍未判分，两次轨迹都保留；磁盘占满本身不能证明由哪个进程消耗了空间。

另有 10 题原始第 2 轮尝试因旧模型端点连接中断而报 `InternalServerError: Connection error`，原有 431 条模型回复均保留。[哈希锚定补跑声明](evidence/muse_nvfp4_r2_connection_recovery_claim.json)逐题只安排一次独立基础设施补跑，题目、镜像和采样参数不变。目前补跑有 4 题终态、0 题获原生判分、0 题成功；只有有效判分才填补原题的缺失值，不择优取样。

GPU allocation 2867 到期时，第 2 轮连接补跑留下 4 题无分连接错误、2 题无模型回复的中断目录、4 题尚未启动；原始记录全部保留。[2902 新 allocation 的纠错声明](evidence/muse_nvfp4_r2_expiry_correction_claim.json)在[非空 thinking 预检](evidence/muse_nvfp4_replica_2902_reasoning_preflight.json)后逐题仅抽一次，题目、镜像和采样设置不变。当前纠错有 10 题终态、10 题原生判分、8 题成功；不择优取样。

第 3 轮原始 89 题均在模型首回复前遇到旧端点拒绝连接。[补跑审计](evidence/muse_nvfp4_r3_infra_replacement_progress.json)计 **89/89 题获原生判分、70 题成功**；仅在 89 题全部判分后才在上表报告整轮准确率。2869 后来在接手的批次运行中到期：已完成的原生结果只计一次，尚无终态结果的 11 题另有明确标记的基础设施续跑，转到仍在线的 2900。其中 4 题在中断前已有共 150 条模型回复，原始不完整轨迹保留但不当作独立分数。b07 在 2869 尚未采样，已在首次采样前转到 2900；2899 继续负责原定批次。使用同一固定 NVFP4 权重、题目镜像和采样参数；Release 归档保存路由凭据、输入、原始回复和轨迹，不按对错择优。

第 3 轮原生成功数包含 `largest-eigenval`。[哈希锚定轨迹核查](evidence/exact_tb_integrity_manual_notes.json)确认 agent 通过 Python 启动钩子拖慢 NumPy 参考求解器；原始 reward 保留，但这一题不能证明未受干预的加速，轨迹已排除出干净训练数据。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **3004/3005 条含非空 thinking**。

[BF16 2886 双节点部署核验](evidence/muse_bf16_2886_deployment_audit.json)记录两台节点各 78 个固定权重文件的校验、SGLang 镜像版本、16 卡 NCCL/EFA 预检、BF16 接口，以及与正式评测分开的工具调用和 thinking 往返检查；这不是 benchmark 成绩。

BF16 SWRBench 的[逐题源数据、生成、GPT-5.5 裁判及原始回复归档清单](input_output/archive_manifests/muse_bf16_swr.json)指向 GitHub Release 资产；后续 `muse_bf16_swr_delta_*` 归档按时间覆盖仍在增长的同路径文件。

[BF16 SWE-Review 输入归档](input_output/archive_manifests/muse_bf16_review_inputs.json)保存了 96 道已准备题目的模型可见任务卡、指令、Dockerfile、公开题目数据，以及队列与镜像记录；不含隐藏解法和测试。正式轨迹与判分将在任务完成后另行归档。

[BF16 SWRBench 生成与裁判对齐核验](evidence/muse_bf16_swr_alignment.json)于 2026-10-21T11:39:43.848320+00:00 将 1000 条裁判记录逐题对到 1000 条生成记录；按固定官方评分代码的撇号规范化后没有 review 文本错配（涉及 93 条）。1000 题官方结果已与生成、裁判、结果文件及指标收据核对；准确率统计 PR 分类，PR 分类 F1 为 0.4967，逐问题点 F1 为 0.1170。

[Muse BF16 SWE-Review 原生进度核验](evidence/muse_bf16_swe_review_progress.json)逐题对照队列任务及 BF16 模型配置；终态数量只表示评审阶段进度，分组 DA 和整体 RRR 仍需官方后续评分。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `opus47_exact_tb_live_20261019T165447Z.tar.zst`（267 个终态结果）和 `beam_bf16_exact_tb_live_20261021T114210Z.tar.zst`（278 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

[Opus 4.7 第 2 轮核验](evidence/opus47_exact_round2_audit.json)和[第 3 轮核验](evidence/opus47_exact_round3_audit.json)按相同规则逐题检查后续轮次。三轮各 89 题均已完整且核验通过：**70/89、71/89、69/89**，三轮均值 **210/267 = 78.65%**。

Beam TB2.1 第 2 轮 `git-multibranch` 原始尝试已有 6 条真实模型回复，但 tmux 会话丢失后没有 verifier 判分。[单独声明的补测审计](evidence/beam_r2_git_multibranch_recovery_20261021.json)现有 1/1 题原生补测判分，其中 1 题成功。原始首抽仍未判分，最多只用这一次补测填补空缺，不按正确与否择优。

Beam 精确镜像 TB 第 2 轮现由 2887 上核验过的 BF16 副本独立执行，第 1 轮继续使用原接口。[接管凭据](evidence/beam_exact_r23_2887_handoff.json)固定模型版本、镜像、原始及有效配置哈希和轮次归属；第 2 轮逐题只计一次，未满 89 题不报告整轮准确率。

Beam TB2.1 第 3 轮有 11 题原始尝试在沙箱启动阶段、模型首回复前失败。[事先声明的单次补测审计](evidence/beam_r3_setup_recovery_20261021.json)现记录 10/11 题补测获原生判分，其中 7 题成功。原始失败和补测结果分开保存；未判分的原尝试不算模型失败，也不按成功与否择优取样。

Beam 精确镜像 TB 第 3 轮交由 2901 独立执行：固定版本的 BF16 权重 198 个文件全部通过校验，服务通过完整的 133/133 项协议测试。[第 3 轮交接证据](evidence/beam_tb_r3_2901/manifest.json)保存原始 89 题配置、镜像凭据、仅变更模型端点的有效配置及独占轮次记录；2887 继续执行第 2 轮。第 3 轮未满 89 题前不报告完整准确率。

第 2 轮 Muse NVFP4 的成功轨迹 `adaptive-rejection-sampler`, `break-filter-js-from-html` 曾探查 verifier 目录；已检查的返回为空，未证实获得隐藏答案。原始 reward 保留，轨迹暂不进入干净训练数据，见[哈希锚定核查](evidence/exact_tb_integrity_manual_notes.json)和[命令筛查](evidence/exact_tb_integrity_screen.json)。

[Opus 4.7 第 3 轮 thinking 传输核查](evidence/opus47_r3_thinking_transport_audit.json)生成于 2026-10-19T16:53:10.951953+00:00，覆盖 89 道终态题：1911 条归档回复中 822 条有可读 thinking，1084 条用量显示 reasoning token 为零，另 5 条虽计入 reasoning token，但上游原始流也没有可读 thinking，仅有签名。后者不能作为带完整 thinking 的训练样本。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `opus47_legacy_delta_20261021T095943Z.tar.zst`、`beam_legacy_delta_20261021T114428Z.tar.zst`、`muse_bf16_delta_20261021T114614Z.tar.zst`；截止时间和文件范围见各自清单。

DeepSWE verifier 使用的原生 `model.patch` 已纳入 Beam 和 Muse BF16 增量链。[Beam 一次性回填](input_output/archive_manifests/beam_legacy_delta_20261020T114916Z.json)保存 387 份补丁，[Muse BF16 一次性回填](input_output/archive_manifests/muse_bf16_delta_20261020T114927Z.json)保存 74 份；后续新补丁随增量继续归档。补丁是模型输出，不增加抽样或得分。

Beam DeepSWE 首轮的 `koota-composite-trait-aspects` 缺失判分：原 verifier 与[复用同一补丁的纯验证补验](evidence/beam_deep_r1_koota_regrade_plan.json)均在 1800 秒后超时。[诊断输入输出归档](input_output/archive_manifests/beam_deep_r1_koota_diagnostic_delta_20261020T121244Z.json)保存两次结果、轨迹、补丁及 verifier 输出。首轮仍为 112/113 已判分、47 成功；补验没有新模型抽样，也没有二元 reward。
