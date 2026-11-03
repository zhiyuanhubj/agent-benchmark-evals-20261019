# H200 本地对照：实际硬件和框架分别标注

用户要求统一使用现有 H200 做本地测试。新曲线必须来自 H200 上实际执行的请求及遥测，不能将官方 SM100 图的数据改名为 H200。

| 模型 | 推理框架 | 硬件 | 状态 |
|---|---|---|---|
| Muse NVFP4 | SGLang，原固定镜像 | 8×H200 | 已有本地实测，剩余补点独立排队 |
| Muse BF16 | SGLang，同一固定镜像 | 16×H200 | 本地测试进行中 |
| DeepSeek V4.1 Flash 1017 | DeepInfer | 目标8×H200 | 已提交独立H200依赖编译与算子入口验证；正式模型吞吐测试尚未开始 |
| DeepSeek V4.1 Flash 1017 | SGLang，同一固定镜像 | 目标8×H200 | 备用对照方案；镜像包含模型实现，尚未启动 |

原 DeepInfer 官方参考仍标为64×SM100。该行的原始数字和硬件标注保留；H200 的待实测行没有速度或吞吐数值。

## 固定测试口径

基础输入8192、输出1024 tokens，全局并发1/2/4/8/16/32/64/128/256，每点至少三遍，预热至少60秒有效 Decode、测量至少120秒有效 Decode，并至少32个成功测量请求。关闭前缀缓存和投机解码，KV 使用 FP8 e4m3。请求 TP8/EP8，实际启动成功后记录最终配置和限制。

沿用 Muse 的真实 KV Decode 区间统计：实际输出 token 增量/有效区间时长/物理 GPU 数，横轴为逐请求 Decode 速度 P50。保存 reasoning、回答、原始流式记录、失败、GPU 和 KV 遥测。若另外测连续补请求的服务性能，分别出线，不混入纯 Decode 图。

8×H200 的 DeepSeek 行主要与8×H200的 Muse NVFP4 行对照；Muse BF16的16卡结果单列，不能仅除以卡数就声称条件完全一致。模型、权重精度和框架差异均需保留在表格里。

## 已查明的兼容性问题

固定 DeepInfer commit 为 `553741557a57df44a46fb3ab72b6aafeaf945337`，其 FlashMLA submodule 为 `2e5429fc5653bab6e081f09477126f731882a6a9`。DeepInfer 的稀疏 Decode 调用进入 FlashMLA；该版本的 [sparse_decode.cpp 第190行](https://github.com/deepseek-ai/FlashMLA/blob/2e5429fc5653bab6e081f09477126f731882a6a9/csrc/api/sparse_decode.cpp#L190)检查 SM100f 架构。因此当前原版路径需要 H200 兼容算子或移植，修改图例不能解决运行限制。

这是源码兼容性检查，不是模型在 H200 上失败的一次跑分。还没有 DeepInfer 的 H200 实际推理结果。

DeepSeek 模型固定为 `deepseek-ai/DeepSeek-V4.1-Flash-1017`，revision 和文件级校验信息见 [固定文件清单](DEEPSEEK_H200_PINNED_FILES_20261102.json)。本地同体积权重只能作为待校验候选；完整文件内容哈希和运行验证完成后才用于正式结果。

[机器可读兼容性记录](H200_COMPATIBILITY_20261102.json) · [Muse 当前曲线和进度](../../evidence/muse_decode_perf_20261029/README.zh-CN.md)

## 2026-11-03 执行更新

DeepInfer 的H200验证已实际分配过节点。先确认原镜像NVCC13.0不足，随后在隔离NVMe环境配置NVCC13.2.86并修复构建依赖。该阶段是固定版本算子的编译和入口检查，尚无DeepInfer在H200上的模型吞吐数据。具体作业和日志见[验证记录](../../evidence/muse_decode_perf_20261029/deepinfer-h200-probe/)。
