# Muse Spark BF16 OpenAI API

Muse Spark BF16 runs on the two GPU hosts in Slurm job 2886: `ip-10-1-13-41` and `ip-10-1-122-30` (16 GPUs total). Its upstream is `http://10.1.13.41:31324/v1`; the dedicated, key-protected public base URL is `https://muse.zhiyuanllm.com/v1`.

Use `muse-spark-open` or `muse-spark-open-bf16` as the model name. Both route to the same BF16 deployment. The relay supports `/v1/models`, `/v1/models/{id}`, `/v1/chat/completions` (including streaming), and `/v1/completions`. It passes the upstream response through, including `reasoning_content`, tool calls, and SSE chunks.

The new API key is in `/fsx/home/zhiyuan/.private/muse_openai_api_20261021/primary.key`. The existing `/fsx/home/zhiyuan/bench/model-relay-token.txt` is also mapped to these two model names. Key values are not stored in this repository. To add or restrict a key, edit the private `gateway-bf16.json` file and restart the `muse-openai-relay-bf16.service` user unit. The relay compares Bearer keys and returns only model aliases allowed for that key.

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://muse.zhiyuanllm.com/v1",
    api_key=open("/fsx/home/zhiyuan/.private/muse_openai_api_20261021/primary.key").read().strip(),
)
response = client.chat.completions.create(
    model="muse-spark-open",
    messages=[{"role": "user", "content": "Hello"}],
)
print(response.choices[0].message)
```

The relay and Cloudflare tunnel are enabled user systemd services (`muse-openai-relay-bf16.service` and `muse-openai-tunnel.service`); user lingering is enabled. Job 2886 is currently allocated until `2026-10-26T18:21:46Z`, so the BF16 GPU pair must be renewed or replaced before then for uninterrupted service. The existing `llm.zhiyuanllm.com` gateway was not changed. The BF16 evaluation clients on CPU nodes continue calling this deployment and share its inference throughput.

Deployment validation is recorded in [`../evidence/muse_openai_bf16_deployment_20261021.json`](../evidence/muse_openai_bf16_deployment_20261021.json).
