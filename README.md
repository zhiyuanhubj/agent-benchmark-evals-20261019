# Agent benchmark evaluation snapshot

Snapshot: **2026-10-19T03:47:13.628881+00:00**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/`; full native trial archives are being added as release assets with checksums.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | 10/11 graded, round 1 partial | 473/500, 439/462, 422/422 terminal; official RRR incomplete |
| Beam BF16 | 31/41 graded, partial | 9/43 graded, round 1 partial | **55.6%** (1000/1000 judged) | 24/32 graded, round 1 partial | Partial; see `results/scores.json` |
| Opus 4.7 | 244/390 graded, partial | **51/113**, round 1 complete; round 2 partial | — | 45/59 graded, round 1 partial | — |
| Muse original BF16 | Running; no complete score | Running; no complete score | Queued after Pro round 1 | Running; no complete score | Queued after Pro round 1 |

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse legacy rounds 2/3 remain **63/85** and **59/76** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is 15/22 graded and partial. None of these partial counts is a full benchmark accuracy. The exact-image TB2.1 scores must not be pooled with legacy-image scores.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_completion.json` documents the three completed DeepSWE rounds and audit flags. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; release archive manifests identify their coverage and SHA-256 once uploaded.

Scores are benchmark-recorded values. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. This report does not certify every trajectory clean. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.
