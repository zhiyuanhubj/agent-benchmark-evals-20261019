# Muse API 恢复记录：2026-10-27

原公网域名与三个客户端 key 已恢复服务，当前连接 Muse NVFP4。原 BF16 后端已不可用，此次复用了仍在运行的 NVFP4 后端，没有申请额外 GPU 节点。

| 项目 | 当前恢复配置 |
| --- | --- |
| Base URL | `https://muse.zhiyuanllm.com/v1` |
| 模型名 | `muse-spark-open` 或 `muse-spark-open-nvfp4` |
| 精度 | NVFP4 权重，FP8 `e4m3` KV cache |
| 推理框架 | Muse 适配版 SGLang |
| GPU | 1 节点，8×H200，TP8/EP8 |
| 后端同时生成上限 | 配置为 8，所有 key 共享，额外请求排队 |
| 鉴权 | 原三个客户端 Bearer key 保持有效 |
| 健康检查 | `https://muse.zhiyuanllm.com/healthz` |
| 当前 allocation | 2989，`ip-10-1-25-253` |
| 当前 allocation 到期 | **2026-10-30 21:16:57 UTC**，届时需续接或更换后端 |

`muse-spark-open-bf16` 不再列为可调用别名，避免将 NVFP4 响应误标成 BF16。客户端使用上表中的任一模型名。

## 调用示例

`MUSE_API_KEY` 使用之前收到的某个 key。普通问答可设置较低 reasoning effort；这仍会返回模型原生的 `reasoning_content`。默认模板的 effort 是 `xhigh`，`max_tokens` 同时包含 thinking 和最终回答，应留足预算。

```bash
curl https://muse.zhiyuanllm.com/v1/chat/completions \
  -H "Authorization: Bearer $MUSE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"muse-spark-open","messages":[{"role":"user","content":"你好"}],"temperature":1.0,"top_p":1.0,"top_k":-1,"max_tokens":2048,"chat_template_kwargs":{"reasoning_effort":"low"}}'
```

```python
import os
from openai import OpenAI

client = OpenAI(base_url="https://muse.zhiyuanllm.com/v1",
                api_key=os.environ["MUSE_API_KEY"])
response = client.chat.completions.create(
    model="muse-spark-open",
    messages=[{"role": "user", "content": "你好"}],
    temperature=1.0,
    top_p=1.0,
    max_tokens=2048,
    extra_body={"top_k": -1, "chat_template_kwargs": {"reasoning_effort": "low"}},
)
print(response.choices[0].message.content)
```

恢复探测中，`temperature=0` 的部分请求反复生成 thinking，直到输出预算耗尽。因此以上沿用原评测记录中的采样参数 `temperature=1.0, top_p=1.0, top_k=-1`。网关透传请求和模型响应，不补写 thinking，也不改写模型的原生结果。

## 已完成验证与运维位置

公网健康检查返回 200；匿名及错误 key 返回 401；三个客户端 key 均完成真实模型问答，得到最终回答和非空 thinking。另验证了 SSE `[DONE]`、流式 usage、工具调用、逐 key 统计和客户端禁止访问管理员统计。原始诊断响应保存在服务器私有目录，摘要见[恢复核验记录](evidence/muse_openai_nvfp4_restore_20261027.json)。这些是功能探测，不是 benchmark 成绩或稳定性能测试。

网关服务沿用原名称 `muse-openai-relay-bf16.service`，描述与实际配置已切为 NVFP4；HTTPS 服务仍为 `muse-openai-tunnel.service`。原共享盘写入报空间不足，因此新配置、原统计库的备份副本和后续用量记录放在本机私有目录 `/var/tmp/zhiyuan-muse-api-20261027/`，通过持久 systemd drop-in 读取。原配置及原统计库保留。更换网关主机时需一并迁移该目录及原私有 key/tunnel 凭证。

API 代码和自行部署步骤见[部署目录](deployment/muse-openai-api/README.zh-CN.md)。[2026-10-21 BF16 使用与性能记录](MUSE_OPENAI_API.zh-CN.md)保留为历史资料，其中 BF16 的硬件、速度和到期时间不适用于当前 NVFP4 服务。
