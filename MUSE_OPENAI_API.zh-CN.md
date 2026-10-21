# Muse Spark Open BF16 对外 API 使用说明

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
