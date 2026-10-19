Benchmark snapshot begun 2026-10-19 UTC. Read the repository README and `results/scores.json` for model/precision, benchmark image profile, complete versus partial status, and audit qualifications.

Each `.tar.zst` asset contains native per-task inputs (`task.json` or `config.json`), result outputs, trajectories, raw API responses and trial logs available at the archive time. Matching JSON files in `input_output/archive_manifests/` record coverage, SHA-256 and source roots. Archives omit model weights, caches and sandbox/verifier internals. Some benchmarks remain active, so this release is a dated snapshot; later results require a new snapshot.

For SWE-Review, select `muse_review_full_io.tar.zst` and `beam_review_full_io.tar.zst`; these include OpenHands `agent/completions/*.json`. The earlier `muse_review.tar.zst` and `beam_review.tar.zst` contain result/trajectory/log summaries only. The historical Opus 4.8 Pro Verified 731-task export is `opus48_731_trajectories.tar.gz`.
