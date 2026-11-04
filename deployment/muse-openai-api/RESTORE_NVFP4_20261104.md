# Muse NVFP4 API restoration on an existing allocation

The retained one-node allocation 3389 is reassigned from its completed C=256 decode repair to the public API. The original batch retention process remains the allocation anchor; no running allocation is cancelled. The two-node BF16 standby job remains queued.

## Fixed configuration

- Public API: `https://muse.zhiyuanllm.com/v1`
- Model aliases: `muse-spark-open` and `muse-spark-open-nvfp4`
- Hardware: 8 NVIDIA H200 GPUs on one node
- Framework: the same pinned SGLang image used by the published decode tests
- Weights: NVFP4, revision `4239e4db19376904f2e82c167e78f70abb5455fe`
- Parallelism: TP8 / EP8
- KV cache: FP8 e4m3; prefix caching enabled; speculation disabled
- Maximum running requests: 8, with additional requests queued
- Authentication: the original three client key files are retained; secrets are excluded from Git

The runtime now accepts both NVFP4 and BF16 plans. Backend verification checks precision, quantization, model identity, GPU count, admission cap, node ownership, and marker freshness before publishing the route. Activation validates each original client key, streamed reasoning, a complete final answer, and rejection of unauthenticated requests. The BF16 standby promotes only after its own native readiness and generation checks pass.

The allocation has a scheduler-enforced expiry of **2026-11-04 17:48:15 UTC**. Retention prevents automatic release on task completion; it does not extend a Slurm lease or guarantee immediate standby allocation. Do not create synthetic GPU traffic to disguise idle capacity.

Public validation completed at **2026-11-04 06:48 UTC**: health HTTP 200; all three original client keys completed SSE streams; reasoning events were observed; an additional full response returned `1591` for `37 * 43`, with nonempty reasoning and `finish_reason=stop`. Unauthenticated requests returned HTTP 401. The three 128-token stream probes test streaming and authentication; a separate 4096-token-budget request verifies a complete final answer. Subsequent availability depends on the live allocation and backend health.
