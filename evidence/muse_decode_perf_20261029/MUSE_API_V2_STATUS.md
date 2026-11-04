# Muse BF16 API at /v2

Status: waiting_backend_readiness.

Base URL: `https://muse.zhiyuanllm.com/v2`. Use the same original three client keys and the common model name `muse-spark-open`.

Allocation 3388: BF16 on 16 H200 GPUs, TP16/EP16, FP8 e4m3 KV cache, maximum 8 running requests. Prefix caching is enabled; speculation is disabled.

The NVFP4 endpoint remains at `/v1`. Each precision has an independent backend, relay, activation timer, and standby path. Internal native SGLang APIs use `/v1` for both precisions.

Readiness requires all three keys to pass streaming checks and a complete generated answer with reasoning. Historical receipts from other allocations are excluded.

Scheduler-enforced lease ends: 2026-11-04T22:39:28 UTC. No allocation was cancelled for this handoff.

[Usage and code](../../deployment/muse-openai-api/DUAL_ENDPOINTS.md); [public validation receipts](muse_api_v2_status.json).
