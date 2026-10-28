# Muse 受控压测完整协议进度

单点数据只是进度；完整曲线、长上下文与投机对照尚未全部完成。

已完成 5 / 52 个当前列出的目标测点。真实 coding 输入分桶在准备后展开；自适应扩展另见 SATURATION/EXTENSION 记录。

| 模型 | 输入/工作负载 | 缓存 | 投机 | 并发 | 有效重复/目标 | 状态 |
|---|---|---|---|---:|---:|---|
| nvfp4 | synthetic/8192 | False | off | 1 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 2 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 4 | 5/5 | complete |
| nvfp4 | synthetic/8192 | False | off | 8 | 5/5 | complete |
| nvfp4 | synthetic/8192 | False | off | 16 | 3/3 | complete |
| nvfp4 | synthetic/8192 | False | off | 32 | 0/3 | pending |
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
