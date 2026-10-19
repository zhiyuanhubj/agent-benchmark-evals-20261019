# Agent benchmark evaluation snapshot

Snapshot: **2026-10-19T04:14:57.707145+00:00**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/` and the [native archive release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot); each archive has a SHA-256 manifest.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | 11/89 graded; 10 success, round 1 partial | 473/500 terminal, 439/462 terminal, 422/422 terminal; official RRR incomplete |
| Beam BF16 | 41/731 graded; 31 success (partial) | 44/113 graded; 9 success (partial), round 1 | **55.6%** (1000/1000 judged) | 34/89 graded; 26 success, round 1 partial | 226/500 terminal, 229/462 terminal, 227/422 terminal; official RRR incomplete |
| Opus 4.7 | 413/731 graded; 258 success (partial) | **51/113**, round 1 complete; round 2 partial | — | 71/89 graded; 56 success, round 1 partial | — |
| Opus 4.8 (historical) | **503/731 = 68.81%**, completed run; 3 confirmed solution retrieval cases | — | — | — | — |
| Muse original BF16 | 2/731 graded; 2 success (partial) | 0/113 graded, round 1 | Queued after Pro round 1 | Not started; legacy cached-tag round 1: 2/89 graded; 2 success (partial) | Queued after Pro round 1 |

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse legacy rounds 2/3 remain **63/85** and **59/76** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is 15/22 graded and partial. None of these partial counts is a full benchmark accuracy. The exact-image TB2.1 scores must not be pooled with legacy-image scores.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_canonical_results.json` maps all 339 graded DeepSWE trials to their exact native results. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; use the release archives and `input_output/archive_manifests/` to check coverage and SHA-256. For SWE-Review, use the `*_review_full_io` assets, which include OpenHands completion JSON in addition to trajectories.

The historical Opus 4.8 Pro Verified result has an existing 731-task trajectory archive in the release. Three confirmed solution retrieval cases are flagged; a conservative supplementary calculation withholding those three credits is **500/731 = 68.40%**. The raw benchmark value stays **503/731**.

The 24 release assets were checked against GitHub's reported SHA-256 digests: **24/24 matched** their committed archive manifests.

Muse NVFP4 exact-image TB2.1 stopped when two model nodes were reassigned to original BF16. A continuation is now active on the surviving NVFP4 node 2866: 11 previously graded round-1 results are locked, 70 tasks had not been sampled, and 8 interrupted ungraded attempts retain their original partial outputs and are labeled infrastructure replacements. Additional GPU allocations 2923 and 2924 are queued. This continuation is separate from both the legacy-image scores and the BF16 evaluation.

Scores are benchmark-recorded values. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. This report does not certify every trajectory clean. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.
