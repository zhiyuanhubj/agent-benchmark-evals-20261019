# 模型评测结果快照

更新时间：**2026-10-20T06:25:45.322146+00:00**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**；SWE-Review 三组官方 DA：GLM5 **75.7%（500 题）**、Coder **81.2%（462 题）**、Instruct **87.2%（422 题）**；SWE-Review Instruct 组官方 RRR **45.5%**；Coder 组官方 RRR **59.7%**；精确镜像 TB2.1 首轮 **68/89（76.40%）**，首轮完整 | SWE-Review 整体 RRR 尚未完成 |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）**；SWE-Review Instruct 组封存 DA **86.5%（422 题）**；SWE-Review Instruct 组官方 RRR **42.7%**；精确镜像 TB2.1 首轮 **62/89（69.66%）**，首轮完整 | Pro Verified **155/731 已判分、94 成功**；DeepSWE 首轮 **112/113、47 成功**；精确镜像 TB2.1 第2轮 54/89 已判分、38 成功，未完成；SWE-Review 另两组与整体 RRR 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 第1轮 **51/113**；DeepSWE 第2轮 **43/113**；DeepSWE 第3轮 **39/113**；精确镜像 TB2.1 第1轮 **70/89**；精确镜像 TB2.1 第2轮 **71/89**；精确镜像 TB2.1 第3轮 **69/89** | Pro Verified **730/731 已判分、451 成功** |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | SWRBench GPT-5.5 裁判 **54.2%（1000/1000）**，PR 分类 F1 **0.4967** | Pro Verified **141/731 已判分**；指定精确镜像 TB2.1 首轮 **36/89 已判分、30 成功**，首轮未完成；DeepSWE 运行中；SWE-Review 原生任务终态 134/1384（GLM 42/500、Coder 49/462、Instruct 43/422），官方 DA/RRR 待完成；已预建 208 个任务镜像 |

**SWE-Review 三组 DA 均已有封存收据。** 官方 `compute_da.py` 在 GLM5 460 个可解析决定上得 **75.7%**（500 题终态），Qwen3-Coder 420 个得 **81.2%**（462 题），Qwen3-30B-Instruct 368 个得 **87.2%**（422 题）。[逐题哈希和官方评分核验](evidence/swe_review_complete_split_da.json)覆盖全部三组。[新版任务准备收据审计](evidence/muse_swe_review_revision_v2_receipts.json)确认 GLM5 的 8 道、Coder 的 2 道只缺 Harbor 汇总：它们的真实原生报告参与 DA，标明用途的适配文件仅供官方修复任务生成，绝非模型结果。[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了 Instruct 组全部 266 条原始生成模型修订：**RRR 45.5%**，原始 baseline RR 27.5%，提升 18.0 个百分点。Coder 组也已核验 222 条原生修订：**RRR 59.7%**，baseline RR 50.9%，提升 8.9 个百分点。GLM5 组及整体 RRR 尚未完成。

[修订阶段基础设施审计](evidence/swe_review_revision_queue_recovery_20261020.json)记录了两种任务输入格式、准备错误，以及沙箱在首个模型回复前的连接超时；这些原生失败不计入模型成绩。随后两条合成 Harbor 任务经 Docker 宿主桥接地址完成模型生成、终端工具调用及原生验证，且不纳入 benchmark。四条正式生成补测队列已用[桥接地址 agent](protocol/muse_review_revision_v2/revision_agents_bridge_v4.py)和原任务输入启动，部分分组已完成。[原生实时判分审计](evidence/swe_review_revision_gateway_progress.json)显示 Muse Coder **222/222**、Muse Instruct **266/266**、Beam Coder **136/224**、Beam Instruct **279/279** 道修订已判分；只有分组内全部原生判分与已归档证据核验通过才报告该分组 RRR。[v3 评分脚本](protocol/muse_review_revision_v2/revision_score_v3.py)只读取修正后的桥接队列结果，将 Beam 的 5 份非法评审报告保留为模型失败，并逐项复现四组已封存 DA。

[Beam Coder 端口错误审计](evidence/beam_coder_pre_model_port_mismatch.json)保留了首批 16 道基础设施失败：沙箱放行 31411 端口，Qwen3-Coder 模型实际服务于 31410，因此均未收到模型回复或原生判分，不计入模型成绩。独立的[修正后 224 题队列](protocol/beam_review_revision_v2/beam_coder_portfix/queue-plan.json)放行 31410；其[独立合成预检](protocol/beam_review_revision_v2/beam_coder_portfix/synthetic-portfix-r2-passed.json)已完成模型生成和原生验证。合成输出不计入成绩，修正队列中的每道被拒绝 PR 只抽样一次。

[SWE-Review 控制器核验](evidence/swe_review_recovery_control.json)确认旧队列于 03:17 UTC 中断：11 题从未领取、23 题虽被领取却没有任何原生题目目录；这 34 题已拆成互不重叠的两条续跑队列，继续用同一 Muse NVFP4 模型。另有 16 题留下部分模型输出：其中 10 题的 agent 结束步骤及原生验证报告、reward 都已保存，只缺 Harbor 汇总文件，原结果保留且未重抽；其余 6 题无最终评审报告，已另列基础设施中断补测。旧状态文件中的 healthy 是停机前的记录，不能当作当前运行状态。

Beam SWE-Review 有[**7 份已抽样但 JSON 无法解析的报告**](evidence/beam_swe_review_malformed_reports.json)，旧任务准备控制器因此失败。[带源码哈希的新版本准备协议](protocol/beam_review_revision_v2/task-preparation-plan-v2.json)保留原始文件，并按官方生成器的缺失决定回退处理；当前阶段为 `all_revision_tasks_prepared`。另两组评审仍在继续。

Beam BF16 的 SWE-Review Instruct 组已有[封存的官方 DA](evidence/swe_review_complete_split_da.json)：422 题终态中 379 个决定可解析，**DA 86.5%**。其中 5 份格式错误的原始报告保留，按模型无有效决定处理。[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了全部 279 条原始生成模型修订和未改动的官方分组指标：**RRR 42.7%**，原始 baseline RR 27.5%，提升 15.2 个百分点。GLM5/Coder 两组及整体 RRR 尚未完成。

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **63/85**、**59/76**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。精确镜像首轮已完成：**68/89（76.40%）**。两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 8839 条原始模型响应、7 个运行中题目目录，最新响应时间为 2026-10-20T06:25:59+00:00；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。另有首轮 18 道尚未启动的题已按原配置哈希移交给 2867 的 NVFP4 副本和 2919 的评测器；只调整模型接口和任务并发数，保留原配置与结果。 2867 上独立的第 2/3 轮控制器状态为 active，阶段 running，当前批次 muse-nvfp4-tb-v1-exact-r2-completion-2866-b03；批次归属凭据阻止重复抽题。 新增 GPU 申请状态：2923 PENDING, 2924 PENDING, 2927 PENDING, 2928 PENDING。排队节点获配后监控器会启动同一 NVFP4 模型服务，并逐批加锁领取 b03、b05 中尚未启动的一批；early95 结束后腾出的 2812 最多可领取两批。原 CPU 评测器继续使用原题目和镜像，仅模型端点变化；若本地批次先启动，不会在其他节点重复抽题。首轮 b05 已在 GPU 2812、CPU 2922 完成 10 道原生题；归属凭据阻止重复抽题。GPU 2812 现以独立加锁接管运行未抽取的第 2/3 轮批次 muse-nvfp4-tb-v1-exact-r2-completion-2866-b05；仅改变模型端点。另有四个排队 GPU 节点获配后只领取第 2/3 轮尚未启动的批次；逐批文件锁和接管凭据阻止原控制器重复抽题，实际配置仅修改模型端点。

GPU 2812 的第二个控制器槽在 b01 最后一题仍运行时领取了未抽样的精确镜像第 2 轮 b02 批次；两条控制器共用已固定的 NVFP4 服务，各批次并发 2 题，服务上限为 8 个请求。[控制器源码](protocol/muse_nvfp4_exact_future_round_controller_20261019.py)使用独立槽锁和原有逐批原子领取；b02 接管凭据及原始/实际配置哈希收录于原始输入输出快照。首轮题目及已抽样的第 2 轮题目均未重抽。

Opus 4.7 Pro 只统计原始运行的 731 道题；同一补丁的纯验证重试单独留证，不能增加首轮题数或成功数。原始运行的 `element-hq` 与两次纯验证重试均在 3600 秒后超时；[Beam BF16 原始运行的同一道题](evidence/shared_element_hq_eval_timeout.json)也在原生 evaluate 阶段超时，两边原始结果都没有有效二元评分。这一共同现象不能证明根因，也不能判定任一模型在该题上成功或失败。独立节点补验未得到已核对的原生评分，需进一步检查。

**超时判分说明。** Muse 精确镜像已判分题目中有 9 题达到协议规定的 agent 时限后仍得到 verifier 分数；逐题审计保留超时标记，首轮不重抽这些题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 8 条、Muse BF16 的 5 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 `break-filter-js-from-html`, `configure-git-webserver`, `fix-code-vulnerability`, `fix-git`, `largest-eigenval`, `password-recovery`, `sqlite-db-truncate`, `winning-avg-corewars`；逐题核查记录了 verifier 日志探查、向 `/tests/filter.py` 复制公开文件或计时篡改；已检查的 verifier 探查输出没有确认获得隐藏答案。排除的 BF16 题目是 `configure-git-webserver`, `fix-git`, `hf-model-inference`, `largest-eigenval`, `password-recovery`，各题原因见逐题核查；新核查的 verifier 与宿主边界探查在已检查输出中未证实获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval` 都通过修改计时函数、拖慢参考特征值求解器拿到原始 reward 1；原始分数保留，NVFP4 的[最终轨迹审计](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)有哈希锚定，但这两条高分不能当作未经篡改的加速证据。此前的 NVFP4 [`db-wal-recovery` 宿主边界探查预警](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)现已有终态：agent 运行 10800 秒后超时，原始奖励为 0。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)将该轨迹排除出干净训练数据；抽查输出未证明成功越过宿主边界，原始评测结果保持不变。关键词未命中也不代表轨迹已获干净认证。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)还标记了 Opus 4.7 在 `break-filter-js-from-html` 上对不存在的 `/tests` 的探查，以及 Beam BF16 在同题中把公开的过滤器临时复制到 `/tests/filter.py`、在判分前删除的行为；检查到的输出均未确认获得隐藏答案，两条轨迹暂不作为干净训练数据。Opus `torch-pipeline-parallelism` 的关键词命中只是列举 Python 可执行文件。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 716 个归档，SWE-Review 的 `*_review_full_io.tar.zst` 含 OpenHands completions；`*_review_verifier.tar.zst` 含原生验证器的评审报告、判分报告和 reward，其中包括 10 道缺 Harbor 汇总文件但已完成原生验证的 Muse 题。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 716/716**，逐项核验见 `evidence/release-assets-verification.json`。

SWE-Review 原始生成模型的修订输入见 [Muse](input_output/archive_manifests/muse_review_revision_inputs.json) 和 [Beam](input_output/archive_manifests/beam_review_revision_inputs.json) 基础归档及按时间命名的增量归档；原生输出、completions、轨迹及 verifier 记录见独立的 [Muse](input_output/archive_manifests/muse_revision_review_full_io.json) 和 [Beam](input_output/archive_manifests/beam_revision_review_full_io.json) 归档链。[Release 覆盖审计](evidence/review_revision_release_coverage.json)给出当前各模型已准备及已进入桥接补测队列的任务卡数量，并确认这些输入与旧故障文件都在 SHA 校验通过的归档中。旧节点地址导致的首回复前失败与可判分的桥接补测分属不同路径；后续增量归档按时间覆盖仍在增长的文件。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **4819/4822 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

第 2 轮目前 **62 题终态、61 题有原生判分、45 题成功**。原始 `password-recovery` 尝试在验证前失去 tmux 会话；[哈希锚定记录](evidence/muse_nvfp4_r2_password_recovery_ungraded.json)保留了原生异常、轨迹和 15 条模型原始回复，原尝试仍未判分。[单题基础设施补测声明](evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json)固定原题、镜像和采样设置，使用已核验的等价 NVFP4 副本；补测原生 reward 当前为 **1.0**。本轮该题最多计一个有效判分，不择优取样。

`password-recovery` 已判分补跑有[轨迹完整性警报](evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json)：31 次工具调用探查宿主挂载或块设备路径，其中 `nsenter` 返回权限不足。原始 reward 保留，但这条轨迹排除出干净训练集；所检查的输出不能证明成功进入宿主或读取隐藏答案。

`prove-plus-comm` 原始尝试在 agent 初始化时[超时](evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json)，模型没有产生回复，也没有原生判分。首次[已声明补跑](evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json)因服务进程缺少 API-key 环境变量，在模型首回复前再次失败且未判分；[故障记录](evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json)保留了原始证据。随后另行声明[服务环境修正](evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json)，其原生 reward 当前为 **1.0**。本题只允许修正后的首个有效原生判分填补缺失值；所有尝试均保留，不择优取样。

原 NVFP4 服务节点 2866 也开始领取第 2/3 轮尚未启动的批次。[节点就绪凭据](evidence/muse_nvfp4_local2866_ready.json)、[实时路由审计](evidence/muse_nvfp4_local2866_route_audit.json)及[控制器代码](protocol/muse_nvfp4_local2866/README.md)显示，本次快照已有 1 条加锁路由，独占 10 道不同题；只按原生结果统计完成题。

第 2 轮**原始首抽**目前有 62 题终态、59 题有效原生判分、43 题成功；上面的修复后统计只补入已单独声明的有效补跑判分。`pytorch-model-cli` 的[原尝试](evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json)在共用 500 GB Docker 底盘占满时失去 tmux 通道，原始 reward 未知。[单次隔离存储补跑](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json)改用 CPU 节点 2922，当前原生 reward 为 **运行中/待判分**。原始首抽仍未判分，两次轨迹都保留；磁盘占满本身不能证明由哪个进程消耗了空间。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **1335/1336 条含非空 thinking**。

[BF16 2886 双节点部署核验](evidence/muse_bf16_2886_deployment_audit.json)记录两台节点各 78 个固定权重文件的校验、SGLang 镜像版本、16 卡 NCCL/EFA 预检、BF16 接口，以及与正式评测分开的工具调用和 thinking 往返检查；这不是 benchmark 成绩。

BF16 SWRBench 的[逐题源数据、生成、GPT-5.5 裁判及原始回复归档清单](input_output/archive_manifests/muse_bf16_swr.json)指向 GitHub Release 资产；后续 `muse_bf16_swr_delta_*` 归档按时间覆盖仍在增长的同路径文件。

[BF16 SWE-Review 输入归档](input_output/archive_manifests/muse_bf16_review_inputs.json)保存了 96 道已准备题目的模型可见任务卡、指令、Dockerfile、公开题目数据，以及队列与镜像记录；不含隐藏解法和测试。正式轨迹与判分将在任务完成后另行归档。

[BF16 SWRBench 生成与裁判对齐核验](evidence/muse_bf16_swr_alignment.json)于 2026-10-20T06:17:02.460501+00:00 将 1000 条裁判记录逐题对到 1000 条生成记录；按固定官方评分代码的撇号规范化后没有 review 文本错配（涉及 93 条）。1000 题官方结果已与生成、裁判、结果文件及指标收据核对；准确率统计 PR 分类，PR 分类 F1 为 0.4967，逐问题点 F1 为 0.1170。

[Muse BF16 SWE-Review 原生进度核验](evidence/muse_bf16_swe_review_progress.json)逐题对照队列任务及 BF16 模型配置；终态数量只表示评审阶段进度，分组 DA 和整体 RRR 仍需官方后续评分。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `opus47_exact_tb_live_20261019T165447Z.tar.zst`（267 个终态结果）和 `beam_bf16_exact_tb_live_20261020T061804Z.tar.zst`（144 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

[Opus 4.7 第 2 轮核验](evidence/opus47_exact_round2_audit.json)和[第 3 轮核验](evidence/opus47_exact_round3_audit.json)按相同规则逐题检查后续轮次。三轮各 89 题均已完整且核验通过：**70/89、71/89、69/89**，三轮均值 **210/267 = 78.65%**。

Beam 精确镜像 TB 第 2 轮现由 2887 上核验过的 BF16 副本独立执行，第 1 轮继续使用原接口。[接管凭据](evidence/beam_exact_r23_2887_handoff.json)固定模型版本、镜像、原始及有效配置哈希和轮次归属；第 2 轮逐题只计一次，未满 89 题不报告整轮准确率。

第 2 轮 Muse NVFP4 的成功轨迹 `adaptive-rejection-sampler`, `break-filter-js-from-html` 曾探查 verifier 目录；已检查的返回为空，未证实获得隐藏答案。原始 reward 保留，轨迹暂不进入干净训练数据，见[哈希锚定核查](evidence/exact_tb_integrity_manual_notes.json)和[命令筛查](evidence/exact_tb_integrity_screen.json)。

[Opus 4.7 第 3 轮 thinking 传输核查](evidence/opus47_r3_thinking_transport_audit.json)生成于 2026-10-19T16:53:10.951953+00:00，覆盖 89 道终态题：1911 条归档回复中 822 条有可读 thinking，1084 条用量显示 reasoning token 为零，另 5 条虽计入 reasoning token，但上游原始流也没有可读 thinking，仅有签名。后者不能作为带完整 thinking 的训练样本。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `opus47_legacy_delta_20261019T194133Z.tar.zst`、`beam_legacy_delta_20261020T061850Z.tar.zst`、`muse_bf16_delta_20261020T061907Z.tar.zst`；截止时间和文件范围见各自清单。
