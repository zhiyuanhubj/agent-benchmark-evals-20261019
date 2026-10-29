# Muse decode-only 测试

这是独立新测量，尚未完成；不复用之前包含 prefill 的服务曲线。

更新时间：2026-10-29 05:36:37 UTC

累计申请 9 个节点；完成 0 个有效重复、0 个满足重复要求的测点。

## 调度实况

```
3137|PENDING|2|(Priority)
3138|PENDING|2|(Priority)
3134|PENDING|1|(Resources)
3135|PENDING|1|(Priority)
3136|PENDING|1|(Priority)
3139|PENDING|1|(Priority)
3133|RUNNING|1|ip-10-1-114-210
```

## 定义

每批实际完成 prefill 并生成 1024 tokens。取所有请求都进入 decode 的共同区间，额外剔除每个请求首尾各 64 tokens；区间内不补入新请求。检查 native KV retraction 计数未增加。

每重复热身至少 60 秒有效 decode；正式累计至少 120 秒有效 decode 和 32 个成功请求。不同批次之间 prefill/refill/排空时间不计入分母。这是多个纯 decode 区间之和，并非连续 120 秒的闭环 serving 窗口。

横轴是区间内逐请求解码速度中位数；纵轴是区间内实际 native output token 增量之和 / 区间时长之和 / 物理 GPU 数。保留 reasoning、输出、逐 token 时间戳、完整原始请求、GPU 与后台遥测。

投机对照保持采样参数不变，使用 NGRAM 原生 target-only 验证路径；移除不受支持的 draft_probs rejection 路径。对照双方均固定 decode graph max batch 32，防止之前 8 GiB verify page-table 分配失败。

服务器接入/流式传输仍有开销，本图不声称是 CUDA kernel 的纯设备计时。硬件、模型、并行和上下文未与 DeepInfer 对齐，不直接作吞吐倍数比较。

配置与控制器：[测试代码](../../performance/muse_decode_20261029/README.md)。原始详细状态：[progress.json](progress.json)。
