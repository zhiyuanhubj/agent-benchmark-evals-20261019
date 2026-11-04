[NVFP4 /v1 与 BF16 /v2 使用说明（English）](DUAL_ENDPOINTS.md)

# Muse OpenAI API 部署代码

**2026-11-03 update:** The BF16 API is restored and generation-validated. [English restoration record and lease/renewal details](RESTORE_BF16_20261103.md). Live status remains authoritative.

2026-11-02 已安排优先恢复 BF16：专用两节点作业 **3270**，初始接入上限 8 路同时生成；原三个客户端 key 沿用。提交时处于节点排队阶段，尚未恢复可用；**是否就绪以[实时恢复状态](../../evidence/muse_decode_perf_20261029/MUSE_API_BF16_STATUS.zh-CN.md)为准**，报告每五分钟更新。2026-10-27 的 NVFP4 部署为历史记录，不能证明服务现在可用。

新增 [BF16 后端控制器](bf16_backend.py) 和 [自动激活器](activate_bf16.py)：核对 Slurm allocation 归属，优先复用并完整校验本地权重，验证 BF16/TP16/EP16/两节点配置后再切换网关。激活器通过原三个 key 分别验证公网 SSE 生成、thinking 字段透传，并检查无 key 返回 401。路由切换保留 key 文件、角色和用量数据库；不把 NVFP4 模型别名映射为 BF16。allocation 失效后停用旧后端路由，避免继续向已移交的节点转发请求。

后端控制器复用本仓库 `performance/muse_decode_20261029/` 的 pinned node preparation、容量预检与有界重排代码。服务独占两节点，不与受控 benchmark 共享；原 32K benchmark 已另提交替代作业 **3274**，其他 BF16 benchmark 保留。后端寿命受 Slurm allocation 限制；本次申请的 TimeLimit 为分区允许的 7 天，不承诺超出 allocation 的持续在线。

这里整理了 2026-10-21 实际使用的 Muse API 网关及可复用的部署配置。原服务使用两节点、16 张 H200 的 SGLang BF16 后端，对外地址为 `https://muse.zhiyuanllm.com/v1`。这些是历史部署记录；本目录不证明原 GPU allocation 或域名当前在线。

## 代码与调用说明

- [API 网关](../../protocol/muse_openai_key_relay_20261021.py)：Bearer key 校验、每个 key 的模型权限、模型别名映射、Chat/Completions、SSE、thinking 和工具调用透传。
- [调用统计](../../protocol/muse_api_activity_20261021.py)：SQLite 持久计数、各 key 的用量和活动请求，以及后台探测让路逻辑。
- [历史使用文档](../../MUSE_OPENAI_API.zh-CN.md)：Python/curl 示例、原部署参数、并发与速度实测。
- [已有回归测试](../../tests/test_muse_api_activity.py)：鉴权、thinking 透传、统计持久化、流式 usage 和后台请求取消。

链路为：客户端 → HTTPS/Cloudflare Tunnel → 本网关（`127.0.0.1:8119`）→ 模型后端的 `/v1` 接口。

本目录部署 API 网关；模型权重、SGLang GPU 服务和 Slurm allocation 需要另行准备。上游应为网关可达、无需额外鉴权的内网 OpenAI 兼容接口，且 `/v1/models` 返回配置中的真实模型 ID。模型名可以根据你的后端修改；使用 NVFP4 后端时也应相应修改模型 ID 和别名。

## 安装与生成私有配置

以下命令假设代码克隆在 `$HOME/agent-benchmark-evals-20261019`，使用 Python 3.12。已有克隆可直接进入该目录。

```bash
git clone https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019.git \
  "$HOME/agent-benchmark-evals-20261019"
cd "$HOME/agent-benchmark-evals-20261019"
python3.12 -m venv .venv
.venv/bin/python -m pip install -r deployment/muse-openai-api/requirements.txt

# 生成新的管理员 key 和三个客户端 key；不会打印 key，也不会覆盖已有配置。
.venv/bin/python - <<'PY'
import json
import os
import secrets
from pathlib import Path

os.umask(0o077)
root = Path.home() / '.config/muse-api'
root.mkdir(parents=True, exist_ok=True, mode=0o700)
root.chmod(0o700)
config = json.loads(Path('deployment/muse-openai-api/gateway.example.json').read_text())
for binding in config['keys']:
    path = root / Path(binding['file']).name
    if not path.exists():
        with path.open('x') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
    binding['file'] = str(path)
config['usage_db'] = str(root / 'usage.sqlite3')
with (root / 'gateway.json').open('x') as stream:
    json.dump(config, stream, indent=2)
    stream.write('\n')
print('Private configuration directory:', root)
PY
```

修改 `$HOME/.config/muse-api/gateway.json` 中的 `upstream_base` 和 `models`，对准你的模型服务。`keys[].models` 列出该 key 可调用的别名；`admin_labels` 指定能查看 `/admin/usage` 的 key 标签。配置引用 key 文件，不内嵌真实 key。

## 启动与验证

```bash
export MUSE_OPENAI_RELAY_CONFIG="$HOME/.config/muse-api/gateway.json"
.venv/bin/python -m uvicorn protocol.muse_openai_key_relay_20261021:app \
  --host 127.0.0.1 --port 8119 --workers 1 --no-access-log
```

另开终端验证。下列请求使用示例配置中的模型别名；更改配置后相应替换。

```bash
curl --fail http://127.0.0.1:8119/healthz
export MUSE_API_KEY="$(cat "$HOME/.config/muse-api/client-01.key")"
curl --fail http://127.0.0.1:8119/v1/models \
  -H "Authorization: Bearer $MUSE_API_KEY"
curl --fail http://127.0.0.1:8119/v1/chat/completions \
  -H "Authorization: Bearer $MUSE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"muse-spark-open","messages":[{"role":"user","content":"你好"}],"max_tokens":256}'
```

正式运行使用单个 worker，因为活动请求和后台取消信号保存在进程内。SQLite 中的历史计数跨进程重启保留。推理并发容量由后端配置和 GPU 负载决定；网关没有为每个 key 分配独立生成配额。历史 BF16 后端配置为最多 8 路同时生成，不能将该历史配置视为新部署的容量承诺。

## systemd 与 HTTPS

```bash
mkdir -p "$HOME/.config/systemd/user"
cp deployment/muse-openai-api/muse-openai-relay.service "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now muse-openai-relay.service
```

提供的 unit 使用上述默认克隆和配置路径；如果安装位置不同，请先修改 unit。前台进程和 systemd 服务二选一运行，避免争用 8119 端口。

HTTPS 可沿用 Cloudflare Tunnel。安装 `cloudflared`、登录你自己的账号并创建 tunnel 后，复制 [cloudflared.example.yml](cloudflared.example.yml) 到 `$HOME/.config/muse-api/cloudflared.yml`，填写自己的 tunnel ID、凭证文件绝对路径和域名，并为域名配置 tunnel 路由。然后安装和启动 [muse-openai-tunnel.service](muse-openai-tunnel.service)，确保 unit 中 `cloudflared` 的路径符合你的机器。公网客户端的 base URL 为 `https://你的域名/v1`。

原服务的三个 key、管理员 key、tunnel 凭证和 SQLite 数据库不随代码发布；新机器按以上步骤生成或配置自己的凭证。本目录不自动启动历史的空闲探测脚本。

## 验证代码

在仓库根目录运行已有测试，无需 GPU 或真实模型请求：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover \
  -s tests -p test_muse_api_activity.py -v
```
