# Controlled Muse throughput and per-request speed experiment

Prepared 2026-10-28. This is a new controlled experiment, separate from the shared-load, short-batch probes from October 21. Do not treat code readiness or queued jobs as completed measurements.

## Deployment and allocation

- Existing NVFP4 API: job **2989**, 8×H200, remains in service. Real clients are actively using it; measurements from this shared endpoint are not used in these curves.
- Dedicated NVFP4 experiment: job **3120**, running on `ip-10-1-101-159`, one 8×H200 node.
- Dedicated BF16 experiment: job **3121**, running on `ip-10-1-112-220` and `ip-10-1-114-210`, 16×H200. The earlier BF16 allocation has ended; this experiment prepares a fresh pinned deployment.
- On user instruction, weikai.huang jobs **3093, 3075, 3074** were cancelled on October 28. Older queued letian.zhang jobs **3114, 3113, 3111** subsequently acquired those nodes. The user then explicitly requested cancellation of those three letian jobs; this was completed. Weikai replacement jobs 3122–3124 were held pending so the earlier request to stop three allocations would not immediately be undone. Jobs 3120/3121 are now running on the freed hosts.
- Shared runtime state: `/fsx/home/zhiyuan/.private/muse_controlled_perf_20261028.7qXoZZ/`. `READY.json` freezes runnable code hashes; each job starts its own controller when Slurm allocates it. Scripts never use another user's running allocation.

Pinned image: `lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a`.

| Setting | NVFP4 | BF16 |
|---|---|---|
| Model | `meta-models/Muse-Spark-Open-816B-A42B-NVFP4` | `meta-models/Muse-Spark-Open-816B-A42B` |
| Revision | `4239e4db19376904f2e82c167e78f70abb5455fe` | `0fb02478b02565b2ce7fc57e6051c91172774ac9` |
| GPUs / TP / EP | 8 / 8 / 8 | 16 / 16 / 16 |
| KV cache | FP8 `e4m3` | FP8 `e4m3` |
| Attention | FA3 | FA3 |
| Context limit | 1,048,576 | 1,048,576 |
| Baseline speculation | off | off |
| Dedicated serving admission cap | 256 | 256 |

The old public service admits at most eight simultaneous generations. The new dedicated cap is fixed across the sweep so offered concurrency 16–128 is not automatically reduced to an eight-slot queue. This changes serving admission relative to the old deployment; do not merge the new and old curves. Actual active/queued requests and KV occupancy are retained in Prometheus telemetry. Weight files are checked against pinned Hub hashes before serving; BF16 is not produced by casting NVFP4 weights.

## Load and repetitions

1. Baseline: exactly **8,192 input tokens**, **1,024 generated output tokens**, radix cache disabled, no speculative decoding; offered concurrency **1, 2, 4, 8, 16, 32, 64, 128**. Native `/tokenize` constructs model-specific input IDs. Synthetic input is padded/truncated in token space while retaining chat-template boundaries; it is not a real agent trace.
2. Every point has at least **3 repetitions**. NVFP4 baseline concurrency **4 and 8 get 5 repetitions**. Each round warms for at least 60 seconds and four successful completions; its effective window lasts at least **120 seconds** and seeks **32 successful arrival-cohort requests**. Low concurrency extends up to 1,800 seconds to reach that sample count; points missing the target remain visibly incomplete.
3. Closed-loop workers immediately submit the next request when their previous request finishes, maintaining target in-flight concurrency throughout warmup and measurement. HTTP connection capacity exceeds the tested concurrency. No finite one-batch approximation is used.
4. Sampling is fixed: temperature 1.0, top_p 1.0, top_k -1, reasoning effort xhigh. `min_new_tokens=max_new_tokens=1024` and `ignore_eos=True` enforce the output length. This is a forced-length serving workload, not an accuracy evaluation.
5. Provisional limits, pending user preference: TTFT p95 **60 s**, E2E p95 **300 s**. Baseline scanning stops after a measured limit crossing or request failures. If 64→128 yields at least 5% throughput growth, test 256. If growth persists, automatically continue offered concurrency 512/1024/2048, keeping the serving admission cap fixed at 256, until throughput grows less than 5% or latency crosses the limit. Active and queued counts distinguish offered load from actual generation concurrency. This is saturation of the pinned serving configuration, not an absolute hardware peak. A client-safety or error stop remains unresolved rather than being called a measured peak. For the already-running NVFP4 process, any >256 extension runs before the first 32K case, on the same still-running baseline server.

## Window accounting and request latency

- Use native `/generate` with the authentic chat-template token IDs. The stream returns cumulative `completion_tokens`. Each positive increment is timestamped with the client's monotonic clock. Counts include **all generated reasoning and answer tokens**, not only visible final text, and never infer tokens from SSE chunk count. Final native text, metadata and token-count timestamps are retained per request.
- Throughput numerator: **all output-token increments received in `[measurement_start, measurement_end)`**, including increments from requests crossing either boundary. Denominator: actual window duration × physical GPU count. Partial failed-request output is still actual emitted output; failures are reported and invalidate a clean curve point.
- Latency cohort: requests admitted inside that window. Already admitted requests drain to completion after admission stops; these tails remain in latency statistics. Drain tokens and drain time are excluded from the throughput numerator/denominator. This avoids dropping slow right tails or counting full outputs outside the measured window.
- TTFT: POST start to first native token-bearing SSE event. TPOT: `(last_token_time-first_token_time)/(completion_tokens-1)`. Per-request decode speed is its reciprocal. E2E includes receipt of stream completion. These are client-observed streaming boundaries, not GPU kernel timings; speculative batches can contain several tokens in one event.
- Save successes/failures both by completion-window and arrival-cohort definitions, full native prompt/output counts, elapsed duration, p50/p95 TTFT/TPOT/E2E, raw requests, and all failed attempts. Do not retry a failed measured request as though it never happened.

## Long context, cache and speculation

After each precision's baseline, test **32,768 and 65,536 input tokens**, 1,024 output tokens, concurrency **1, 8, 32**, three repeats, separately for radix cache off/on. Cache-on inputs share a nominal 90% token prefix primed before warmup; cache-off remains truly disabled. Native per-request `cached_tokens/prompt_tokens` supplies the measured hit rate, not the nominal prefix ratio.

Speculation off/on uses the same frozen corpus of **16 authentic SWE-bench Pro coding issues** and **16 authentic SWRBench code-review prompts**. It excludes reference patches, tests, model outputs and answers. Prompts remain unchanged after template application. The corpus is partitioned by actual tokenizer length into [0,8K), [8K,32K), [32K,64K), and [64K,130048) bins. Each nonempty bin gets independent windows and separate curves; each round reports its actual input-token distribution. Empty bins are explicitly recorded. No padding/truncation is applied, and these ranges are not represented as exact fixed-length agent traces.

The available pinned framework supports **NGRAM** speculation without a draft checkpoint. It is a specific CPU n-gram draft experiment with eight draft tokens and rejection sampling, not a Muse MTP/EAGLE experiment and not a proxy for DeepSeek's draft model. Run concurrency 1/8/32, cache off, with the same corpus and generation settings as its non-speculative control. Preserve native `spec_verify_ct`, proposed/correct drafts and weighted acceptance length. Startup incompatibility is recorded as an untested/incomplete configuration, never turned into a speedup claim.

## Telemetry and figures

`gpu.py` samples every allocated GPU every second: utilization, memory used/total, power, clocks, UUID, host and timestamp. `bench.py` retains `/server_info` and full Prometheus text every two seconds, including available scheduler/KV occupancy metrics. Measurement windows have epoch and monotonic anchors for alignment. No-metrics windows are excluded from valid curves.

`plot.py` writes per-round CSV, PNG and PDF. Each line fixes precision, workload/input length, cache policy and speculative configuration. Only points meeting their required valid repetition count appear (three normally; five for NVFP4 baseline c4/c8). Every physical GPU must have valid utilization/memory samples covering at least 80% of its expected one-second samples. NGRAM points additionally require native verification/acceptance counters. The x coordinate is the **pooled median of individual-request decode speeds**; y is **sum of actual window output tokens / sum of window seconds / GPU count**. Error bars show the sample standard deviation of repeat-level medians (x) and repeat-level measured throughputs (y), not a confidence interval. The input concurrency is annotated separately.

For a DeepSeek comparison, record its exact model revision, precision, hardware/GPU count, inference framework, TP/EP, KV format, input/output lengths, cache state, speculation/draft model, actual active versus offered concurrency, latency limits and token-window definition. Without those aligned conditions, label any external numbers as reference only. No unmatched DeepSeek line is fabricated in these figures.

## Files and verification

Storage recovery on October 28: BF16 rank 1's 28 TB NVMe had only about 37 GB free and its initial download stopped. The batch controller was paused to preserve the granted allocation while rank 0 continued its download. With the user's explicit cleanup authorization, an inactive, downloaded GLM-5 cache from ended allocation 2899 was removed after checking for open/mapped files. This reclaimed **1,507,764,948,992 bytes** and left **1,545,117,028,352 bytes** free. Training checkpoints, trajectories and evaluation results were retained. `repair_bf16_download.py` resumes only missing shards on local NVMe with a 100 GB reserve and a local Xet cache, then verifies every pinned file; `resume_bf16.py` starts a replacement controller only after both ranks' complete verification receipts exist. Model, image and measurement settings are unchanged. The original paused controller is released after replacement-controller cleanup.

- `bench.py`: native streaming closed-loop load and statistics.
- `node.py`: per-node pinned model preparation and serving.
- `orchestrate.py`: autonomous configuration/case sequence inside the approved allocations.
- `gpu.py`: GPU traces; `plot.py`: curves and CSV; `publish.py`: safe GitHub progress publication.
- `test_metrics.py`: measurement-boundary accounting, failure retention, uncensored latency tails and native cumulative-token parsing.

Run unit tests with Python 3.12 and httpx 0.28.1:

```bash
python -m unittest discover -s performance/muse_controlled_20261028 -p 'test_*.py' -v
```

Matplotlib 3.10.7 and its resolved dependencies are installed in this experiment's isolated `plot_deps`, not into the live API environment. The CSV/PNG/PDF workflow was checked with an explicitly synthetic test fixture; fixture results are not experimental data. An eight-token native request on the live server checked monotonic token counts and `[DONE]`; it is not part of the controlled curve.

## Detailed acceptance report

The 15-minute publisher produces `REPORT.zh-CN.md` and `acceptance_matrix.csv` listing every required point, completed/required repetitions, and missing items. `detailed_rounds.csv` contains TTFT/TPOT/E2E p50/p95, actual token totals, success/failure counts, duration, all-GPU utilization/memory/power/clocks, live KV occupancy and active/queued request gauges. `detailed_points.csv` pools native individual requests across repetitions; it does not average per-round p95 values. It also reports repeat-level SD, input/output-length distributions, and actual window throughput. Figures are marked IN PROGRESS until acceptance is complete.

`MEASUREMENT_INVARIANCE.json` verifies that core request timing, native token-window accounting and request-latency functions are unchanged from commit 3e212e5. The additions implement sweep continuation, authentic coding input-length bins and detailed postprocessing.

BF16 recovery runs its control plane outside a narrowed single-node Slurm step, while its load client still runs on the model's rank-0 GPU host, matching the NVFP4 client placement. Allocation hostnames come from Slurm's authoritative job list. The headless second BF16 node skips tokenizer initialization and receives token IDs from rank 0. External symlinks left by an earlier overflow download were materialized and SHA-verified on each node's NVMe; the launch preflight now requires all files to resolve inside the read-only weight mount.

Before any valid BF16 measurement, the first real prefill failed with `NET/OFI ... ofi cq creation failed` on the default breakable prefill graph path. The BF16 launch explicitly disables prefill CUDA graphs, while retaining decode CUDA graphs. This setting is frozen across all BF16 cases and recorded in the native server configuration; NVFP4 keeps its existing graph settings. Consequently these are measurements of two documented serving deployments, not a precision-only causal comparison. Failed-startup logs and GPU traces are preserved separately from measurement traces.
