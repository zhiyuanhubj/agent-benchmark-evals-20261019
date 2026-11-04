# Muse OpenAI-Compatible API: NVFP4 and BF16

BF16 public validation passed on **2026-11-04 at 08:37 UTC**: all three original keys completed reasoning streams; a separate full generation returned `1591` for `37 * 43` with nonempty reasoning and a normal stop. NVFP4 `/v1` remained online.

The two endpoints use the **same original three client keys**, the same OpenAI-compatible request format, and the common model name **`muse-spark-open`**. Select precision by changing only the base URL.

| Precision | Base URL | Explicit model alias | Hardware | Maximum running requests |
| --- | --- | --- | --- | --- |
| NVFP4 | `https://muse.zhiyuanllm.com/v1` | `muse-spark-open-nvfp4` | 8 H200 GPUs | 8 |
| BF16 | `https://muse.zhiyuanllm.com/v2` | `muse-spark-open-bf16` | 16 H200 GPUs | 8 |

The admission caps are service configuration limits, not newly measured throughput results. Additional requests queue. Both services use SGLang, FP8 e4m3 KV cache, enabled prefix caching, disabled speculation, and the Muse reasoning/tool parsers. The BF16 API explicitly selects the Libfabric network plugin for its two-node EFA transport. These API-only overrides do not change the benchmark plans. The original key files and key labels are preserved. Keys are excluded from Git.

## Request example

Set `MUSE_API_KEY` to one of your existing keys, then run:

```bash
curl https://muse.zhiyuanllm.com/v2/chat/completions \
  -H "Authorization: Bearer ${MUSE_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"muse-spark-open","messages":[{"role":"user","content":"Compute 37 * 43."}],"reasoning_effort":"low","max_tokens":2048,"stream":false}'
```

Change `/v2` to `/v1` for NVFP4. For streaming, set `stream` to `true` and use `curl -N`. Reasoning is returned in `reasoning_content`, while the final answer is returned in `content`; streamed events carry these fields in `delta`. The output-token budget includes reasoning, so a short budget may end before the final answer. Existing high/low reasoning parameters are forwarded as before.

## Verify availability

- NVFP4 health: `https://muse.zhiyuanllm.com/healthz`
- BF16 health: `https://muse.zhiyuanllm.com/v2/healthz`
- Authenticated model listings: `/v1/models` and `/v2/models`

A model listing alone does not establish model readiness. Activation checks allocation ownership, pinned precision, parallelism, admission cap, freshness, all three keys, streamed reasoning, and a complete generated answer. Health returns HTTP 503 until the corresponding backend becomes available.

The cloudflared ingress sends `/v2` to a separate loopback relay on port 8120; the existing `/v1` relay stays on 8119. Relays use the same implementation with `api_prefix` set to `/v1` or `/v2`. Their configs and activation timers remain independent. Native SGLang upstreams use `/v1` internally for both precisions. BF16 standby promotion cannot replace the NVFP4 `/v1` route.

Current allocations have scheduler-enforced leases. Retention prevents task-completion release but does not extend a Slurm lease. Each precision has its own queued standby, and scheduler availability affects continuity.

## Operator files

- [Versioned relay](../../protocol/muse_openai_key_relay_20261021.py)
- [BF16 gateway example](gateway-v2.example.json)
- [Activation checks](activate_bf16.py)
- [Versioned routing/authentication tests](test_versioned_relay.py)
- [Independent BF16 standby watcher](../../performance/muse_decode_20261029/v2_watch.py)
- [Pinned node-local staging tools](v2-staging/)

The staging tools are the exact allocation-specific operator scripts and require adapting job IDs, node addresses, state directories, and local storage paths for another cluster. They resume authenticated native copies and verify every staged file against its pinned SHA-256 or Git-blob hash. No cache-eviction tool or dataset contents are included. Reuse receipts bind verified files to exact size, nanosecond timestamps, inode, and device when available, avoiding cross-filesystem clock comparisons; legacy receipts retain the conservative timestamp check. Timestamp-ambiguous files were rehashed before creating exact-metadata receipts.

Run the relay regression check from the repository root:

```bash
python deployment/muse-openai-api/test_versioned_relay.py
```

Live public validation receipts are published with the experiment evidence; the final deployment is only considered ready after complete generation succeeds.
