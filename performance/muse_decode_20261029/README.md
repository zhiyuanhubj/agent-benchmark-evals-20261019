# Muse H200 Decode Benchmark Source

The complete English reproducibility snapshot is available at [English code, data, figures, and download](../../evidence/muse_decode_perf_20261029/english/README.md).

- [Exact plotted coordinates and SD error bars](../../evidence/muse_decode_perf_20261029/english/data/decode_points.csv)
- [Per-repetition values](../../evidence/muse_decode_perf_20261029/english/data/decode_rounds.csv)
- [Per-request speeds and timing-window exports](../../evidence/muse_decode_perf_20261029/english/data/)
- [Complete ZIP](../../evidence/muse_decode_perf_20261029/english/muse_decode_h200_bundle.zip)

## Measurement and plotting code

| File | Purpose |
|---|---|
| `decode.py` | Real-KV, full-resident cohort decode windows; measured native token increments |
| `native_client.py` | Native SGLang request streaming, token timing, prompts, and latency quantiles |
| `prefill.py` | Native prefill-phase measurements with one output token |
| `gpu.py` | Per-node GPU telemetry |
| `node.py`, `control.py` | Pinned model preparation and isolated replica lifecycle |
| `plot_from_csv.py` | Offline figures from exported numeric CSVs |
| `recompute_points.py` | Independent reconstruction of both coordinates and both SD error bars |
| `export_english_bundle.py` | English snapshot, numeric exports, manifest, and ZIP |
| `publish.py` | Cluster-specific live reporting and publication |

## Replot and independently verify

```bash
pip install matplotlib numpy Pillow
python plot_from_csv.py --data ../../evidence/muse_decode_perf_20261029/english/data --out replotted
python recompute_points.py --data ../../evidence/muse_decode_perf_20261029/english/data --out recomputed_points.csv
```

The downloadable English snapshot includes pinned plotting-library versions, SHA-256 hashes, model revisions, request-level numerical exports, and measured timing windows. It does not require model weights or cluster access to reconstruct the existing figures.

## Fixed experimental configuration

Muse NVFP4 uses 8 H200 GPUs, TP8/EP8, modelopt FP4 and Marlin MoE. Muse BF16 uses 16 H200 GPUs, TP16/EP16 and BF16 weights. Both use FP8 e4m3 KV, FA3, a pinned SGLang image, real prefill/KV, and disabled prefix caching for baseline measurements. Baseline speculation is off. Input lengths are 8K/32K/64K/128K, output length is 1024 tokens, and counts include reasoning and final output.

X is the pooled median of individual-request decode speeds. Y is actual output-token increments / measured decode-window seconds / physical GPU count. Error bars are sample SD across repetitions. Each repetition requires at least 60 warmup decode seconds, 120 measured decode seconds, and 32 successful requests. Baseline NVFP4 C=4 and C=8 have five repeats; other published points require at least three. Full details and limitations are in the English snapshot.

These are selected decode-only intervals, not whole-test serving throughput and not isolated CUDA-kernel timing. Real prefill, refill gaps, and draining tails are excluded from the decode denominator. TTFT includes actual prefill and scheduling and is reported separately.

## Run the client on a new deployment

The native client requires compatible SGLang `/generate`, `/tokenize`, `/metrics`, `/server_info`, and `/flush_cache` endpoints. Use the corpus in the English code snapshot and collect telemetry on every physical GPU. The original provisioning helpers target Slurm, Docker, local NVMe and AWS EFA; adapt account, paths and networking to another cluster. No authentication keys or model weights are included.

The public API deployment is separate from controlled measurements. Its restoration and allocation-retention helpers are also versioned here. The current live status is in [API status](../../evidence/muse_decode_perf_20261029/MUSE_API_BF16_STATUS.zh-CN.md).
