# Muse Spark Open BF16 对外 API 使用说明

**2026-10-27 更新：公网 API 已恢复为 NVFP4，原三个 key 沿用。当前可用模型、调用示例与节点有效期请看 [NVFP4 服务恢复记录](MUSE_API_STATUS_20261027.zh-CN.md)。下文 BF16 配置与速度保留为历史资料。**

API 源码、可复用配置模板和 systemd 启动步骤见 [Muse API 部署目录](deployment/muse-openai-api/README.zh-CN.md)。下文记录的是 2026-10-21 的部署与测量，不代表原 GPU allocation 或公网服务当前仍在线。

Muse Spark Open 的 BF16 版本部署在两个 GPU 节点、共 16 张 GPU 上，通过独立的 OpenAI 兼容地址提供服务。

| 项目 | 值 |
| --- | --- |
| Base URL | `https://muse.zhiyuanllm.com/v1` |
| 模型名 | `muse-spark-open` 或 `muse-spark-open-bf16`，两者指向同一 BF16 部署 |
| 鉴权 | `Authorization: Bearer <API key>` |
| 接口 | `GET /models`、`GET /models/{id}`、`POST /chat/completions`、`POST /completions` |
| 健康检查 | `GET https://muse.zhiyuanllm.com/healthz` |

三个独立的新 key 保存在服务器的 `/fsx/home/zhiyuan/.private/muse_openai_api_20261021/client-01.key`、`client-02.key`、`client-03.key`。这三个 key 都允许访问上面两个模型别名。原有 `primary.key` 和 `bench/model-relay-token.txt` 也仍可用。**不要把 key 值提交到 GitHub、粘贴到日志或放进客户端网页代码。**

下面的命令中，先在本机把收到的某个 key 放进环境变量 `MUSE_API_KEY`。

```bash
curl https://muse.zhiyuanllm.com/v1/models \
  -H "Authorization: Bearer $MUSE_API_KEY"

curl https://muse.zhiyuanllm.com/v1/chat/completions \
  -H "Authorization: Bearer $MUSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"muse-spark-open","messages":[{"role":"user","content":"你好，请用一句话介绍自己"}],"max_tokens":256}'
```

OpenAI Python SDK 示例：

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://muse.zhiyuanllm.com/v1",
    api_key=os.environ["MUSE_API_KEY"],
)
response = client.chat.completions.create(
    model="muse-spark-open",
    messages=[{"role": "user", "content": "你好"}],
    max_tokens=256,
)
print(response.choices[0].message)
```

流式输出时设置 `stream=True`（或 JSON 中的 `"stream":true`）。服务透传上游的 SSE、`reasoning_content` 和工具调用字段；具体字段取决于请求与模型回答。

## 并发容量

推理后端的 `max-running-requests` 配置是 **8**，即同一时间最多有 8 个请求在模型中生成。API 网关没有按 key 分配独立配额；所有 key 和仍在运行的 BF16 评测客户端共享这 8 个执行位置。超过 8 个的请求可以进入后端等待队列，这不代表它们也在并行生成。当前后端未配置队列长度上限，因此请在调用端自行设置并发上限和超时，避免长队列。

2026-10-21 的公网短请求实测（每请求最多输出 8 token）如下；成功只说明这些短请求在当时被接受并完成，**不是长上下文或长回答的吞吐保证**。

| 同时发起 | 完成 | 整批耗时 | 单请求中位耗时 | 最慢请求 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1/1 | 0.639 s | 0.639 s | 0.639 s |
| 2 | 2/2 | 0.440 s | 0.439 s | 0.439 s |
| 4 | 4/4 | 0.598 s | 0.455 s | 0.597 s |
| 8 | 8/8 | 1.175 s | 0.738 s | 1.174 s |
| 16 | 16/16 | 4.946 s | 2.603 s | 4.743 s |

目前建议单个外部客户端先限制在 **2–4 路**，并监控延迟；如果停止共享评测负载，整个服务最多可让 **8 路**同时进入模型生成。16 路短请求虽然全部完成，后半批明显等待，不宜把 16 当作稳定的并行生成容量。实际容量还受输入长度、输出长度和正在运行的其他任务影响。

服务通过启用的 `muse-openai-relay-bf16.service` 与 `muse-openai-tunnel.service` 提供。BF16 的 Slurm allocation 2886 当前截至 **2026-10-26 18:21:46 UTC**；到期前必须续接或更换部署，才能持续对外服务。现有 `llm.zhiyuanllm.com` 网关没有改动。

部署和鉴权验证见 [Muse API 证据](evidence/muse_openai_bf16_deployment_20261021.json)，并发配置和实测原始数值见 [并发证据](evidence/muse_openai_concurrency_20261021.json)。

## 推理框架与速度实测

2026-10-21 12:24 UTC 的运行配置核验显示，两种精度均使用固定镜像中的 Muse 适配版 SGLang，包版本为 `0.0.0.dev0`。当前 BF16 为一套两节点、16 张 H200 的 TP16/EP16 部署；NVFP4 为七套单节点、每套八张 H200 的 TP8/EP8 副本。两者 Attention 后端均为 FA3，KV cache 均为 `fp8_e4m3`，最多同时生成八个请求，未开启 speculative decoding。BF16 权重精度与 FP8 KV cache 精度应分开描述。镜像固定为 `lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a`，容器内 PyTorch 为 2.14.1、CUDA 13.0；完整配置见[运行证据](evidence/muse_serving_runtime_20261021.json)。

以下为约 12:26–12:29 UTC 的客户端 SSE 实测。短输入约 260 token，长输入约 7,200 token；每个输入场景三次单请求，输出固定预算 256 token，表中均为中位数。现有评测持续共享各自副本，未暂停评测来制造独占环境。

| 部署与访问路径 | 输入 token | 首个生成 token（TTFT） | 解码速度 | 平均每输出 token 耗时 | 256 token 流耗时 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BF16，内网直连 | 约 260 | 0.180 s | 33.7 token/s | 29.7 ms | 7.74 s |
| BF16，内网直连 | 约 7,200 | 0.592 s | 32.7 token/s | 30.5 ms | 8.39 s |
| NVFP4，内网直连 | 约 260 | 0.116 s | 63.5 token/s | 15.7 ms | 7.43 s |
| NVFP4，内网直连 | 约 7,200 | 0.669 s | 63.7 token/s | 15.7 ms | 4.67 s |
| BF16，公网 API | 约 260 | 0.299 s | 34.1 token/s | 29.3 ms | 7.83 s |

TTFT 从客户端开始 POST 起算，到首个非空 `reasoning_content`、正文或工具调用 delta 为止，包含排队、prefill 与网络耗时；空的 role 事件不算首 token。此次 39 个计时请求都在 256 token 预算内持续输出 thinking，没有到最终回答，因此上述流耗时不能当成完整回答耗时。解码速度以服务器实际返回的 completion token 数除以首个到最后一个非空 token delta 的时间计算；首 token 和总耗时分别取中位数，不能将各列中位数直接相加。NVFP4 短输入有一次 TTFT 为 3.495 秒、另一次流中生成变慢，所以其解码速度更快也不代表每条请求的总耗时都缩短。

短输入另各测了一批 4 路和 8 路并发，每请求 256 输出 token：

| 部署 | 4 路探测请求合计吞吐 | 8 路探测请求合计吞吐 | 8 路首 token 中位数 / 最慢 |
| --- | ---: | ---: | ---: |
| BF16 | 98.4 token/s | 115.1 token/s | 3.84 s / 7.86 s |
| NVFP4 | 216.1 token/s | 234.8 token/s | 0.209 s / 4.69 s |

吞吐仅计算这批探测请求的输出，未包括同时运行的评测请求，不能作为服务总吞吐上限。两组硬件规模、实时负载不同，也不能用这张表计算单由量化带来的加速比。每并发档只有一批，本次没有足够样本报告 p95、长上下文 SLA 或稳定最大吞吐。全部 39/39 请求返回 HTTP 200、`[DONE]` 和 256 个 completion token。

逐请求指标、统计口径和原生 SSE 归档指针见[速度证据](evidence/muse_serving_speed_20261021.json)，可复现脚本见[测量脚本](protocol/measure_muse_serving_speed_20261021.py)。

### 64K 输入与缓存复用补测

此前约 260/7,200 token 的短测不能代表 NVIDIA Dynamo 的 Agent 长上下文性能。12:35–12:38 UTC 在同一个 8×H200 NVFP4 副本补测了约 64,000 输入、400 输出、89.95%公共前缀的合成负载。原生 `/generate` 检查确认公共前缀约 57,567–57,569 token 已在缓存；OpenAI 路由不返回逐请求缓存命中数，所以这里称为“公共前缀已预热”，不声称逐请求实测命中率恰好为 90%。

| 来源/部署 | GPU | 入口并发 | 首 token p50 | 单请求解码速度 p50 |
| --- | --- | ---: | ---: | ---: |
| NVIDIA Dynamo + SGLang，官方 Agent trace | 4×GB200 | 12 | 222 ms | 57.4 token/s |
| NVIDIA Dynamo + SGLang，官方 Agent trace | 4×GB300 | 16 | 178 ms | 51.0 token/s |
| 本部署 SGLang，合成公共前缀请求 | 8×H200 | 1 | 755 ms | 63.2 token/s |
| 本部署 SGLang，合成公共前缀请求 | 8×H200 | 4 | 2,361 ms | 38.3 token/s |
| 本部署 SGLang，合成公共前缀请求 | 8×H200 | 8 | 3,372 ms | 55.0 token/s |
| 本部署 SGLang，合成公共前缀请求 | 8×H200 | 12 | 8,573 ms | 54.8 token/s |
| 本部署 SGLang，合成公共前缀请求 | 8×H200 | 16 | 14,255 ms | 51.3 token/s |

官方数字见 [Dynamo Muse recipe](https://docs.nvidia.com/dynamo/dev/recipes/Muse-Spark-Open)。表格并列供参考：本次没有使用 AIPerf 回放官方 3,541 请求 trace，没有重启清空整个副本的 KV，也没有停止共享的 Pro 评测；硬件、框架版本、入口并发和负载长度分布均不同。当前后端执行上限为 8，入口 12/16 路会排队。本次 1 路为三次请求，其余每档只有一批；44 个请求（含冷输入基线）均成功，不能据此声明长期 p50/p95 或独占峰值。低并发下的解码速度可以达到约 63 token/s，但 64K 并发首 token 延迟目前没有达到官方约 0.2 秒的结果。

这些 p50 都先计算逐请求指标再取中位数，不是算术平均值；解码速度不包含首 token 等待。12 路时，本部署将等待算入后的每请求输出速度 p50 只有约 28.2 token/s，16 路约 18.2 token/s。单次冷 64K 请求的首 token 为 6.58 秒；预热公共前缀后，三次单请求首 token 中位数为 0.755 秒，但这仍是共享负载下的小样本。

官方还注明 vLLM 的两条记录仅为前 500 请求的功能验证，不应直接与 SGLang 全 trace 做框架排名。完整逐请求时间戳、缓存检查与统计边界见 [64K 补测证据](evidence/muse_64k_cached_speed_20261021.json) 和[补测脚本](protocol/measure_muse_64k_cached_speed_20261021.py)。

### BF16 的 64K 输入与缓存复用补测

2026-10-21 12:43–12:47 UTC，在对外 API 使用的同一套 16×H200、TP16/EP16 BF16 权重加 FP8 KV cache 部署上，按上一组 NVFP4 的相同合成请求构造与 SSE 统计口径补测。约 64,000 输入、400 输出 token，89.94% 公共前缀；原生检查显示公共前缀约 57,568–57,570 token 在缓存中。此次使用内网直连，现有评测与对外 API 均保持运行。

| 入口并发 | 首 token p50 | 单请求解码速度 p50 | 400 token 流耗时 p50 | 本批探测合计吞吐 |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0.795 s | 33.0 token/s | 12.89 s | 31.5 / 31.0 / 25.8 token/s |
| 4 | 1.625 s | 34.2 token/s | 13.28 s | 58.0 token/s |
| 8 | 3.792 s | 32.4 token/s | 16.73 s | 116.6 token/s |
| 12 | 15.318 s | 31.6 token/s | 27.93 s | 110.7 token/s |
| 16 | 16.077 s | 31.4 token/s | 29.20 s | 139.3 token/s |

43 个预热后的计时请求和 1 个新公共前缀基线请求均成功完成，均返回 400 个 thinking token，没有在预算内进入最终正文。新公共前缀基线的首 token 为 4.21 秒，解码约 28.8 token/s；不是清空整个副本 KV 后的冷启动。首 token 包括 thinking、排队、prefill 和内网传输；解码速度排除首 token 等待，各列独立取中位数。合计吞吐仅计算探测请求，未包含同时运行的评测或 API 调用。

当前后端最多同时生成 8 路，12/16 路入口会排队。单路做三次，其余每档仅一批；这些数值是共享负载下的小样本，不能当作稳定最大容量、p95 或 SLA。BF16 与 NVFP4 分别在 16 与 8 张 H200 上、不同时间测量，不能据此计算单由量化带来的加速比，也不能视为在 GB200/GB300 上回放官方 Dynamo trace 的复现。

逐请求指标见 [BF16 64K 速度证据](evidence/muse_bf16_64k_cached_speed_20261021.json)，原始请求、thinking、SSE 时间戳与缓存检查的完整清单见 [BF16 64K 归档清单](input_output/archive_manifests/muse_bf16_64k_cached_speed_20261021T124334Z.json)。可复现命令：

```bash
python -m protocol.measure_muse_64k_cached_speed_20261021 --target bf16_direct
```

## 调用量与空闲质量探测

从 2026-10-21 12:11 UTC 起，网关按 `client-01`、`client-02`、`client-03` 等标签持久记录请求数、成功/错误数、最近 5/15/60 分钟调用数及上游实际返回的 token 用量。流式响应只有携带 usage 时才能统计 token；可在请求中设置 `stream_options={"include_usage":true}`。统计库不保存 key、提示词或回答。此前没有逐 key 日志，无法补算历史调用量。

管理员可使用原有 `primary.key` 请求 `GET /admin/usage` 查看统计；三个客户端 key 无权读取管理统计。重启网关保留已记录数据。

`muse-api-idle-quality.service` 每 30 秒检查一次。所有真实调用连续安静至少 120 秒、没有活动请求，且 BF16 主节点八卡平均 GPU 利用率低于 10% 时，才发出一个非 benchmark 质量探测请求。每次最多 256 个输出 token、并发为 1；真实请求到来会取消后台 HTTP 请求，后台输出不计入 benchmark 成绩或三个客户端的调用量。现有直连评测使 GPU 忙碌时，也不会补发探测。

探测使用独立的 `background-quality` 身份，其响应与返回的 thinking 保存在服务器私有目录 `background-quality/` 中；单段日志不超过约 10 MiB。服务由 systemd 自动启动和故障重启，可用 `systemctl --user stop muse-api-idle-quality.service` 停止。管理员的 `background-current.json` 记录最近一次跳过或执行原因。

这是健康检查和空闲性能采样，不保证豁免集群的空闲回收、抢占或 allocation 到期规则。应按实际集群规则续期或申请服务用途的节点。
