# Independent Muse decode-only curves — October 29

This experiment is separate from the October 28 end-to-end serving curves. Queueing, successful preparation and a healthy server do not count as measured results.

## Resources and provenance

Seven jobs request nine exclusive H200 nodes: NVFP4 jobs 3133/3134/3135/3136/3139 each use one node (8 GPUs); BF16 jobs 3137/3138 each use two nodes (16 GPUs). At submission, 3133 started and the remaining jobs requested **eight pending nodes**. Job 2989 continues the public API independently.

Pinned SGLang image: `lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a`.

- NVFP4: `meta-models/Muse-Spark-Open-816B-A42B-NVFP4`, revision `4239e4db19376904f2e82c167e78f70abb5455fe`, TP8/EP8, modelopt FP4/Marlin, static fraction 0.90.
- BF16: `meta-models/Muse-Spark-Open-816B-A42B`, revision `0fb02478b02565b2ce7fc57e6051c91172774ac9`, TP16/EP16, BF16, static fraction 0.88; prefill graphs disabled after the previous EFA startup failure.
- Both: FP8 e4m3 KV, FA3, real prefill, real KV, cache disabled, context capacity 1,048,576, admission cap 256, generation temperature 1/top_p 1/top_k -1, ignore EOS and exactly 1,024 output tokens. Native generated counts include reasoning and final text. No fake/dummy KV.

`native_client.py` is the frozen native streaming/tokenizer helper from the October 28 experiment. Its `Round.request` implementation is reused, while serving window admission and serving throughput statistics are not reused.

## Decode measurement

Submit exactly C requests in a cohort, with no new arrivals until that cohort drains. Perform real prefill. For each request discard its first and last 64 output tokens; intersect the remaining timestamp intervals across **all C requests**. No request is admitted inside that intersection. Validate that the native KV retraction counter has not increased; otherwise exclude and preserve the failed cohort.

This yields a full-resident, decode-only interval, excluding prefill, refill gaps, early transients and shrinking-batch tails. These are client-observed engine decoding windows, not CUDA kernel-only timings. GPU and backend traces are retained for every allocated GPU.

For each configuration, accumulate at least 60 seconds of warmup decode, then at least 120 seconds of measured decode and 32 completed requests. Multiple 1K-output cohorts are needed at low concurrency; the denominator is the **sum of selected decode intervals**, not a continuous 120-second serving window. Three independent repeats; NVFP4 baseline c4/c8 have five. Each repeat retains requests, native cumulative token timestamps, output text, per-cohort intervals, failures and server settings. Actual generated output increments within each selected window supply throughput; do not multiply C by per-user speed.

The x coordinate is the median of individual request decoding speeds measured inside selected windows. The y coordinate is total actual output increments / total selected seconds / physical GPU count. Error bars are repetition SD. Plotted points additionally require all-GPU utilization/memory coverage of at least 80% of their measured windows. TTFT and end-to-end latency remain auxiliary full-request measurements; they are excluded from the decode-throughput denominator.

## Work distribution

| Job | Nodes | Work |
|---|---:|---|
| 3133 | 1 | NVFP4 8K baseline; C=1,2,4,8,16,32,64,128,256 |
| 3134 | 1 | NVFP4 32K; C=1,8,32 |
| 3135 | 1 | NVFP4 64K; C=1,8,32 |
| 3136 | 1 | NVFP4 authentic coding/review, speculation off/on, paired controls |
| 3137 | 2 | BF16 8K baseline; same C scan |
| 3138 | 2 | BF16 32K/64K plus paired coding speculation off/on |
| 3139 | 1 | NVFP4 128K; C=1,8,32, for additional context-length reference |

A no-common-window, KV retraction, request error, or TPOT p95 over 300ms records a capacity/latency/error boundary; higher load is not labelled a measured hardware peak. Capacity is bounded by the pinned server admission cap. The 128K workload does not make the H200/Muse result a matched DeepInfer/SM100/DeepSeek experiment.

NGRAM uses the framework's native target-only verification path. The previous explicit rejection-sampling flag incorrectly required a `draft_probs` tensor that NGRAM does not supply. Sampling temperature remains 1.0. Both members of the paired speculative control fix decode graph max batch 32 and disable prefill graphs, avoiding the earlier 8GiB verify page-table allocation at graph max batch 256. These paired settings are kept separate from the baseline/long-context server settings. Native verification counts and actual acceptance lengths are required before reporting a speculative speedup.

## Execution and reporting

`control.py` prepares and verifies weights, starts per-node GPU sampling and the pinned server, executes cases, and stops only containers in its own allocation. BF16 first reuses a fully verified local pinned copy; fresh downloads require enough NVMe space plus a reserve and never delete unrelated files. Requests run on the replica's head GPU host. Native request and timing artifacts remain under each job state directory.

`publish.py` updates `evidence/muse_decode_perf_20261029/` every 15 minutes with queue status, per-round CSV, accepted point CSV, figures and explicit pending/failure states. It reads only the new decode summaries and does not relabel October 28 serving results.

Validation:

```bash
python -m unittest discover -s performance/muse_decode_20261029 -p 'test_*.py' -v
```

Tests cover token-window boundaries with unequal actual token increments, prefill/tail exclusion, failed requests and non-overlapping cohorts. GPU integration remains pending until allocations start; tests are not experimental results.
