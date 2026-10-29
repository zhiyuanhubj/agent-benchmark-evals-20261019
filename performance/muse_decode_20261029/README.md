# Independent Muse decode-only curves — October 29

This experiment is separate from the October 28 end-to-end serving curves. Queueing, successful preparation and a healthy server do not count as measured results.

## Resources and provenance

The initial seven jobs requested nine exclusive H200 nodes. Job 3133's failed warmup is retained; replacement 3140 and the added BF16 128K job 3141 bring the live allocation target to eleven nodes, with twelve node requests cumulatively including failed 3133. Job 2989 continues the public API independently.

At the user's October 29 instruction, dominick.reilly jobs **3066 and 3130** were cancelled. Both released nodes were obtained by this experiment: **3135 on ip-10-1-13-41**, and **3136 on ip-10-1-88-35**. Together with 3134, that gives three running decode replicas; eight nodes remain requested in pending jobs. `RESOURCE_UPDATE_20261029.json` records the handoff without publishing the cancelled jobs' private command lines.

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
| 3134 | 1 | NVFP4 32K; current 1/8/32 scan followed by the missing dense-grid points on the same warm replica |
| 3135 | 1 | NVFP4 64K; full C scan |
| 3136 | 1 | NVFP4 authentic coding/review, speculation off/on; C=1,2,4,8,16,32 |
| 3137 | 2 | BF16 8K baseline; same C scan |
| 3138 | 2 | BF16 32K/64K full C scans plus paired coding speculation off/on |
| 3139 | 1 | NVFP4 128K full C scan, for additional context-length reference |
| 3140 | 1 | Replacement NVFP4 8K full C scan; failed 3133 artifacts remain separate |
| 3141 | 2 | BF16 128K full C scan |

The synthetic full scan is **1/2/4/8/16/32/64/128/256** for each precision and each of **8K/32K/64K/128K**, making eight configuration groups and up to 72 points. The two actual coding length bins, two precisions and speculation off/on form eight more groups, each with six concurrency points, for up to 48 points. Combined upper bounds are **16 groups, 120 unique configuration points, 364 repetitions** (including the extra NVFP4 8K c4/c8 repeats). Hardware, latency or stability boundaries can prevent higher points; these are documented rather than fabricated. `matrix.py` and its test distinguish unique configuration points from repeated measurements and retries. The publisher exports per-point completion in `decode_matrix.csv` and separate context/coding panels.

A no-common-window, KV retraction, request error, or TPOT p95 over 300ms records a capacity/latency/error boundary; higher load is not labelled a measured hardware peak. Capacity is bounded by the pinned server admission cap. The 128K workload does not make the H200/Muse result a matched DeepInfer/SM100/DeepSeek experiment.

NGRAM uses the framework's native target-only verification path. The previous explicit rejection-sampling flag incorrectly required a `draft_probs` tensor that NGRAM does not supply. Sampling temperature remains 1.0. Both members of the paired speculative control fix decode graph max batch 32 and disable prefill graphs, avoiding the earlier 8GiB verify page-table allocation at graph max batch 256. These paired settings are kept separate from the baseline/long-context server settings. Native verification counts and actual acceptance lengths are required before reporting a speculative speedup.

## Execution and reporting

`control.py` prepares and verifies weights, starts per-node GPU sampling and the pinned server, executes cases, and stops only containers in its own allocation. BF16 first reuses a fully verified local pinned copy; fresh downloads require enough NVMe space plus a reserve and never delete unrelated files. Requests run on the replica's head GPU host. Native request and timing artifacts remain under each job state directory.

`publish.py` updates `evidence/muse_decode_perf_20261029/` every **5 minutes** with queue status, per-round CSV, accepted point CSV, figures and explicit pending/failure states. It reads only the new phase-specific measurements and does not relabel October 28 serving results.

The first 8K attempt (3133) completed a valid warmup request but was incorrectly rejected because a zero-valued, lazily labelled Prometheus retraction counter had no series. Its failed warmup remains preserved. The corrected guard checks native per-request `num_retractions` as well as any cumulative series; missing both kinds of evidence still fails validation. Replacement job **3140** uses a separate state directory. A replay of the actual failed warmup verifies the guard correction. No failed warmup is promoted to a measured point.

The first NVFP4 replica fully hashed all pinned shared files. Later replicas may reuse that complete cryptographic receipt only if every shared file has the expected size and its mtime/ctime predates the original allocation creation, establishing that the files were unchanged throughout and after verification. Reused receipts retain their original provenance.

## Prefill-only cohorts

Decode now runs first. Synthetic, speculation-off cases defer `prefill.py` until their decode sweep finishes. The earlier 32K prefill data remain preserved. For a client already in memory before this ordering change, a separate supervisor waits for its completion and runs deferred prefill on the same warm replica before cleanup. Prefill submits cohorts at concurrency 1/8/32, processes the complete real input, and generates exactly **one output token**. There is no subsequent decode workload in these cohorts.

Native `forward_entry_time` and `prefill_finished_time` define each request's engine prefill phase. The complete cohort's phase envelope runs from the earliest forward entry to the latest prefill completion. Its numerator is the sum of actual native prompt-token counts, including each request once. Initial external queue and network time are excluded from the phase denominator; full client latency remains a separate measurement. Chunk scheduling, engine host overhead and first-token sampling are included: this is an engine prefill phase benchmark, not CUDA-kernel-only timing.

Each repeat accumulates at least 60 seconds of warmup prefill time followed by at least 120 seconds of measured phase time and 32 successful requests; three repeats are required. Preserve raw requests, native timestamps, failures, input counts, backend traces and all physical GPU samples. Points lacking native timestamps, zero retractions/cache hits or sufficient GPU coverage are not plotted. The five-minute publisher writes `prefill_rounds.csv`, `prefill_points.csv`, `prefill_throughput.{png,pdf,svg}` (input length vs input tokens/s/GPU), and `prefill_pareto.{png,pdf,svg}` (prefill phase latency vs throughput), with repetition SD error bars. No prefill figure is declared complete while these fresh measurements are pending.

## In-flight sweep continuation

`dense_followup.py` preserves the current 32K client's valid work, then fills the missing concurrency points using the same resident model and physical GPUs. It stops only the CPU coordinator's polling process; the measurement client, model server and GPU telemetry continue uninterrupted. PID, command, state directory and process birth tick must all match before a coordinator can receive a signal. A persistent supervisor waits for the original client to exit, saves its initial case configuration, starts the dense continuation with completed rounds reused, and resumes the original coordinator for normal cleanup. This preserves fixed deployment conditions across the curve without a second model load or duplicate load generators. A second supervisor preserves deferred 64K prefill for the client that was already running when decode-first ordering was requested. Their state and raw logs remain under the respective job directory.

Validation:

```bash
python -m unittest discover -s performance/muse_decode_20261029 -p 'test_*.py' -v
```

Tests cover token-window boundaries with unequal actual token increments, prefill/tail exclusion, failed requests and non-overlapping cohorts. GPU integration remains pending until allocations start; tests are not experimental results.
