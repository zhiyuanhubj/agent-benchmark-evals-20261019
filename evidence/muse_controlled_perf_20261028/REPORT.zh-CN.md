# Muse 受控压测完整协议进度

以下结果为进行中的测量；完整曲线、长上下文与投机对照尚未全部完成。

更新时间：2026-10-28 16:06:46 UTC。

配置、模型完整 revision、镜像 digest、实际启动命令、物理 GPU 与 native server_info：[reproducibility.json](reproducibility.json)。

已完成规定重复的测点如下。TTFT/E2E 单位为秒，TPOT 为毫秒/token；输出速度包含 reasoning 与回答。吞吐按实际测量窗计算。

| 模型/输入 | 缓存/投机 | 并发 | 重复 | 测量秒数合计 | 成功/失败入场请求 | 输出 t/s/GPU ±重复SD | 单请求 t/s p50 ±重复SD | TTFT p50/p95 | TPOT p50/p95 | E2E p50/p95 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nvfp4/8192 | False/off | 1 | 3 | 1287.300 | 99/0 | 9.690 ± 0.003 | 81.188 ± 0.008 | 0.610/0.613 | 12.317/12.321 | 13.211/13.215 |
| nvfp4/8192 | False/off | 2 | 3 | 723.959 | 102/0 | 16.987 ± 0.011 | 73.219 ± 0.031 | 1.084/1.213 | 13.658/13.802 | 15.052/15.079 |
| nvfp4/8192 | False/off | 4 | 5 | 788.285 | 180/0 | 28.549 ± 0.021 | 62.894 ± 0.071 | 1.859/2.413 | 15.903/16.781 | 18.125/18.165 |
| nvfp4/8192 | False/off | 8 | 5 | 600.501 | 200/0 | 45.242 ± 0.047 | 51.634 ± 0.067 | 3.072/4.837 | 19.370/21.416 | 22.906/22.963 |
| nvfp4/8192 | False/off | 16 | 3 | 360.488 | 192/0 | 64.296 ± 0.130 | 39.768 ± 0.061 | 5.493/9.664 | 25.148/29.487 | 31.268/31.360 |

当前吞吐—单用户速度曲线（仅含已验收测点）：

![synthetic curve](synthetic.png)

coding+review 各 native 输入长度桶及投机开关分别成线：[coding.png](coding.png)。

已完成 5 / 52 个当前列出的目标测点。真实 coding 输入分桶在准备后展开；自适应扩展另见 SATURATION/EXTENSION 记录。

| 模型 | 输入/工作负载 | 缓存 | 投机 | 并发 | 有效重复/目标 | 状态 |
|---|---|---|---|---:|---:|---|
| nvfp4 | synthetic/8192 | False | off | 1 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 2 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 4 | 5/5 | complete |
| nvfp4 | synthetic/8192 | False | off | 8 | 5/5 | complete |
| nvfp4 | synthetic/8192 | False | off | 16 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 32 | 2/3 | partial |
| nvfp4 | synthetic/8192 | False | off | 64 | 0/3 | pending |
| nvfp4 | synthetic/8192 | False | off | 128 | 0/3 | pending |
| nvfp4 | synthetic/32768 | False | off | 1 | 0/3 | pending |
| nvfp4 | synthetic/32768 | False | off | 8 | 0/3 | pending |
| nvfp4 | synthetic/32768 | False | off | 32 | 0/3 | pending |
| nvfp4 | synthetic/32768 | True | off | 1 | 0/3 | pending |
| nvfp4 | synthetic/32768 | True | off | 8 | 0/3 | pending |
| nvfp4 | synthetic/32768 | True | off | 32 | 0/3 | pending |
| nvfp4 | synthetic/65536 | False | off | 1 | 0/3 | pending |
| nvfp4 | synthetic/65536 | False | off | 8 | 0/3 | pending |
| nvfp4 | synthetic/65536 | False | off | 32 | 0/3 | pending |
| nvfp4 | synthetic/65536 | True | off | 1 | 0/3 | pending |
| nvfp4 | synthetic/65536 | True | off | 8 | 0/3 | pending |
| nvfp4 | synthetic/65536 | True | off | 32 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | off | 1 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | off | 8 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | off | 32 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | NGRAM | 1 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | NGRAM | 8 | 0/3 | pending |
| nvfp4 | coding/native-input-bins-pending | False | NGRAM | 32 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 1 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 2 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 4 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 8 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 16 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 32 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 64 | 0/3 | pending |
| bf16 | synthetic/8192 | False | off | 128 | 0/3 | pending |
| bf16 | synthetic/32768 | False | off | 1 | 0/3 | pending |
| bf16 | synthetic/32768 | False | off | 8 | 0/3 | pending |
| bf16 | synthetic/32768 | False | off | 32 | 0/3 | pending |
| bf16 | synthetic/32768 | True | off | 1 | 0/3 | pending |
| bf16 | synthetic/32768 | True | off | 8 | 0/3 | pending |
| bf16 | synthetic/32768 | True | off | 32 | 0/3 | pending |
| bf16 | synthetic/65536 | False | off | 1 | 0/3 | pending |
| bf16 | synthetic/65536 | False | off | 8 | 0/3 | pending |
| bf16 | synthetic/65536 | False | off | 32 | 0/3 | pending |
| bf16 | synthetic/65536 | True | off | 1 | 0/3 | pending |
| bf16 | synthetic/65536 | True | off | 8 | 0/3 | pending |
| bf16 | synthetic/65536 | True | off | 32 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | off | 1 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | off | 8 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | off | 32 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | NGRAM | 1 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | NGRAM | 8 | 0/3 | pending |
| bf16 | coding/native-input-bins-pending | False | NGRAM | 32 | 0/3 | pending |

详细逐轮指标：[detailed_rounds.csv](detailed_rounds.csv)；逐请求合并后的测点统计：[detailed_points.csv](detailed_points.csv)。

吞吐严格来自测量窗内收到的 native token 增量；延迟统计保留测量窗内入场请求的完整排空尾部。输出包括模型生成的 reasoning 和回答。

GPU 指标来自所有物理 GPU 的 1 秒采样；KV/运行/排队指标来自 2 秒 Prometheus 原始记录。没有完整重复或 GPU 遥测的点不作为最终曲线点。

误差棒为重复实验间的样本标准差。DeepSeek 未进行条件对齐的独立实测，本报告不补造对照数字。
