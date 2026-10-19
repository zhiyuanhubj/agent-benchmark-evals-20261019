#!/usr/bin/env python3
"""Publish a reproducible, explicitly qualified snapshot of local eval state."""
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path('/fsx/home/zhiyuan/.private')
M = PRIVATE / 'muse_spark_open_20261016'
B = PRIVATE / 'beam_20261018'
BF = PRIVATE / 'muse_bf16_20261018'
O48 = PRIVATE / 'opus48_sbpv_20261004'


def read(path):
    return json.loads(path.read_text())


def write(rel, value):
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=True) + '\n')


def metric(d, name, status=None):
    return {k: d.get(k) for k in ('expected', 'terminal', 'graded', 'success') if k in d} | ({'status': status} if status else {})


now = datetime.now(timezone.utc).isoformat()
pro = read(M / 'state/monitor-current.json')['pro_round1_verified_completion']
tb_recovery = read(M / 'state/monitor-current.json')['reshard_recorder_recovery']
tb_legacy_remaining = read(ROOT / 'results/muse_tb_legacy_status.json')
deep = read(M / 'remaining_deep3_2812_20261018/state/current.json')['three_round_summary']
mr = read(M / 'review_bench_20261018/state/current.json')
ex = read(B / 'expanded-current.json')
br = read(B / 'current.json')
exact = read(B / 'tb_v1_exact_images_20261019/status-current.json')
opus48 = read(O48 / 'completed_full_evaluation_result.json')
nvfp4_recovery = read(B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/completion-2866-plan.json')
nvfp4_recovery_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-completion-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
snapshot = {
    'generated_utc': now,
    'metric_policy': 'Only complete benchmark rounds are reported as accuracy; partial counts are progress, never accuracy. No best-of resampling.',
    'models': {
        'muse_nvfp4': {
            'model': 'Muse-Spark-Open-816B-A42B-NVFP4',
            'swe_bench_pro_verified': {'round_1': {'status': 'complete', 'expected': 731, 'graded': 731, 'success': pro['success'], 'accuracy': pro['accuracy'], 'qualification': pro['qualification']}},
            'deepswe': {'rounds': deep['rounds'], 'mean_three_round_accuracy': deep['benchmark_recorded_mean_accuracy'], 'status': 'complete_three_rounds', 'qualification': deep['metric_scope'], 'trajectory_review_flag': deep['targeted_review']['successful_trajectory_with_verifier_log_probe']},
            'swrbench': {'status': 'complete', 'expected': 1000, 'judged': mr['swrbench']['judged'], 'accuracy': mr['swrbench']['final_metrics']['overall']['accuracy'], 'f1': mr['swrbench']['final_metrics']['overall']['f1'], 'judge': 'gpt-5.5'},
            'swe_review': {key: metric(value, key, 'partial_no_full_rrr') for key, value in mr['swe_review'].items() if isinstance(value, dict) and 'expected' in value},
            'tb2_1_legacy_cached_tag': {'round_1_raw': tb_recovery['raw_round1'], 'round_1_with_all_declared_infrastructure_replacements': tb_recovery['with_all_verified_declared_replacements'], 'rounds_2_3': {k: metric(v, k, 'partial_no_full_score') for k, v in tb_legacy_remaining['rounds'].items()}, 'qualification': 'Infrastructure replacement is a new model draw and must be distinguished from raw first-draw result; no three-round mean.'},
            'tb2_1_exact_supplied_images': {'rounds': exact['models']['muse_nvfp4']['rounds'], 'status': 'partial_no_full_score', 'recovery': {'controller': nvfp4_recovery_unit, 'existing_graded_round_1': len(nvfp4_recovery['existing_scored_results']['1']), 'queued_round_1': sum(len(c['tasks']) for c in nvfp4_recovery['configurations'] if c['round'] == 1), 'user_cutover_interrupted_ungraded': len(nvfp4_recovery['user_cutover_interrupted_ungraded_trials']), 'extra_gpu_allocations_queued': [2923, 2924], 'qualification': nvfp4_recovery['qualification']}},
        },
        'beam_bf16': {
            'model': 'reflection/Beam-1.0-501B-A23B',
            'swe_bench_pro_verified': metric(ex['beam_bf16']['pro'], 'pro', 'partial_no_full_score'),
            'deepswe': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['beam_bf16']['deep'].items()},
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['beam_bf16']['tb'].items()},
            'tb2_1_exact_supplied_images': {'rounds': exact['models']['beam_bf16']['rounds'], 'status': 'partial_no_full_score'},
            'swrbench': {'status': 'complete', 'expected': 1000, 'judged': br['swrbench']['judged'], 'accuracy': br['swrbench']['final_metrics']['overall']['accuracy'], 'f1': br['swrbench']['final_metrics']['overall']['f1'], 'judge': 'gpt-5.5'},
            'swe_review': {key: metric(value, key, 'partial_no_full_rrr') for key, value in br['swe_review'].items() if isinstance(value, dict) and 'expected' in value},
        },
        'opus_4_7': {
            'model': 'Claude Opus 4.7',
            'swe_bench_pro_verified': metric(ex['opus47']['pro'], 'pro', 'partial_no_full_score'),
            'deepswe': {k: metric(v, k, 'complete' if v['graded'] == v['expected'] else 'partial_no_full_score') for k, v in ex['opus47']['deep'].items()},
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'complete' if v['graded'] == v['expected'] else 'partial_no_full_score') for k, v in ex['opus47']['tb'].items()},
            'tb2_1_exact_supplied_images': {'rounds': exact['models']['opus47']['rounds'], 'status': 'partial_no_full_score'},
        },
        'opus_4_8_historical': {
            'model': 'Claude Opus 4.8',
            'swe_bench_pro_verified': {'status': 'complete_historical_run', 'expected': 731, 'graded': 731, 'success': opus48['all731']['correct'], 'accuracy': opus48['all731']['correct'] / 731, 'confirmed_solution_retrieval_cases': opus48['confirmed_solution_retrieval_count'], 'conservative_noncredit_for_confirmed_retrieval': opus48['conservative_noncredit_confirmed_retrieval'], 'qualification': 'Three confirmed solution retrieval cases; raw benchmark score is unchanged and not a claim all other trajectories are clean.'},
        },
        'muse_bf16': {
            'model': 'meta-models/Muse-Spark-Open-816B-A42B',
            'revision': '0fb02478b02565b2ce7fc57e6051c91172774ac9',
            'status': 'in_progress',
            'swe_bench_pro_verified': metric(ex['muse_bf16']['pro'], 'pro', 'partial_no_full_score'),
            'tb2_1': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['tb'].items()},
            'deepswe': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['deep'].items()},
            'qualification': 'Original BF16 native Pro, TB2.1 and DeepSWE started after real inference and tool/thinking preflight; partial counts are progress, not accuracy.',
        },
    },
    'source_files': {
        'muse_pro': str(M / 'state/monitor-current.json'),
        'muse_pro_task_evidence': str(M / 'state/pro-round1-task-evidence.json'),
        'muse_deep_three_round': str(M / 'remaining_deep3_2812_20261018/state/current.json'),
        'muse_swr_review': str(M / 'review_bench_20261018/state/current.json'),
        'beam_opus_bf16': str(B / 'expanded-current.json'),
        'beam_swr_review': str(B / 'current.json'),
        'tb_exact_images': str(B / 'tb_v1_exact_images_20261019/status-current.json'),
        'muse_tb_legacy': str(ROOT / 'results/muse_tb_legacy_status.json'),
        'opus48_pro_full': str(O48 / 'completed_full_evaluation_result.json'),
        'muse_nvfp4_exact_recovery_plan': str(B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/completion-2866-plan.json'),
    },
}
write('results/scores.json', snapshot)

files = {}
for label, base in [('muse_nvfp4', M / 'review_bench_20261018'), ('beam_bf16', B / 'review_bench')]:
    for name in ('generation.jsonl', 'evaluation-gpt-5.5.json'):
        source = base / 'swrbench' / name
        dest = ROOT / 'input_output' / 'swrbench' / label / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        files[str(dest.relative_to(ROOT))] = {'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'size_bytes': dest.stat().st_size, 'source': str(source)}

for label, source in [
    ('muse_pro_identity', M / 'state/pro-round1-task-evidence.json'),
    ('muse_pro_score_source', M / 'state/monitor-current.json'),
    ('muse_deep_completion', M / 'remaining_deep3_2812_20261018/state/current.json'),
    ('muse_deep_canonical_results', M / 'remaining_deep3_2812_20261018/state/three-round-completion-audit.json'),
    ('muse_swr_review_score_source', M / 'review_bench_20261018/state/current.json'),
    ('beam_opus_bf16_score_source', B / 'expanded-current.json'),
    ('beam_swr_review_score_source', B / 'current.json'),
    ('tb_exact_image_score_source', B / 'tb_v1_exact_images_20261019/status-current.json'),
    ('opus48_pro_full_score_source', O48 / 'completed_full_evaluation_result.json'),
    ('opus48_pro_trajectory_index', O48 / 'trajectory_export_20261004/index.json'),
    ('opus48_pro_protocol', O48 / 'trajectory_export_20261004/protocol.json'),
    ('muse_nvfp4_exact_recovery_plan', B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/completion-2866-plan.json'),
    ('muse_bf16_runtime_status', BF / 'status-current.json'),
]:
    dest = ROOT / 'evidence' / (label + '.json')
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)
    files[str(dest.relative_to(ROOT))] = {'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'size_bytes': dest.stat().st_size, 'source': str(source)}
write('input_output/manifest.json', {'generated_utc': now, 'files': files})

def partial(d):
    return f"{d['graded']}/{d['expected']} graded; {d['success']} success (partial)" if d.get('graded') else f"0/{d['expected']} graded"

def review(d):
    return ', '.join(f"{v['terminal']}/{v['expected']} terminal" for v in d.values()) + '; official RRR incomplete'

models = snapshot['models']
mn = models['muse_nvfp4']
be = models['beam_bf16']
op = models['opus_4_7']
mn_tb = mn['tb2_1_exact_supplied_images']['rounds']['1']
be_tb = be['tb2_1_exact_supplied_images']['rounds']['1']
op_tb = op['tb2_1_exact_supplied_images']['rounds']['1']
readme = f'''# Agent benchmark evaluation snapshot

Snapshot: **{now}**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/` and the [native archive release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot); each archive has a SHA-256 manifest.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | {mn_tb['graded']}/89 graded; {mn_tb['success']} success, round 1 partial | {review(mn['swe_review'])} |
| Beam BF16 | {partial(be['swe_bench_pro_verified'])} | {partial(be['deepswe']['1'])}, round 1 | **55.6%** (1000/1000 judged) | {be_tb['graded']}/89 graded; {be_tb['success']} success, round 1 partial | {review(be['swe_review'])} |
| Opus 4.7 | {partial(op['swe_bench_pro_verified'])} | **51/113**, round 1 complete; round 2 partial | — | {op_tb['graded']}/89 graded; {op_tb['success']} success, round 1 partial | — |
| Opus 4.8 (historical) | **503/731 = 68.81%**, completed run; 3 confirmed solution retrieval cases | — | — | — | — |
| Muse original BF16 | {partial(models['muse_bf16']['swe_bench_pro_verified'])} | {partial(models['muse_bf16']['deepswe']['1'])}, round 1 | Queued after Pro round 1 | {partial(models['muse_bf16']['tb2_1']['1'])}, round 1 | Queued after Pro round 1 |

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse legacy rounds 2/3 remain **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}** and **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is {be['tb2_1_legacy_cached_tag']['1']['success']}/{be['tb2_1_legacy_cached_tag']['1']['graded']} graded and partial. None of these partial counts is a full benchmark accuracy. The exact-image TB2.1 scores must not be pooled with legacy-image scores.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_canonical_results.json` maps all 339 graded DeepSWE trials to their exact native results. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; use the release archives and `input_output/archive_manifests/` to check coverage and SHA-256. For SWE-Review, use the `*_review_full_io` assets, which include OpenHands completion JSON in addition to trajectories.

The historical Opus 4.8 Pro Verified result has an existing 731-task trajectory archive in the release. Three confirmed solution retrieval cases are flagged; a conservative supplementary calculation withholding those three credits is **500/731 = 68.40%**. The raw benchmark value stays **503/731**.

Muse NVFP4 exact-image TB2.1 stopped when two model nodes were reassigned to original BF16. A continuation is now active on the surviving NVFP4 node 2866: 11 previously graded round-1 results are locked, 70 tasks had not been sampled, and 8 interrupted ungraded attempts retain their original partial outputs and are labeled infrastructure replacements. Additional GPU allocations 2923 and 2924 are queued. This continuation is separate from both the legacy-image scores and the BF16 evaluation.

Scores are benchmark-recorded values. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. This report does not certify every trajectory clean. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.
'''
(ROOT / 'README.md').write_text(readme)
print(json.dumps({'snapshot': now, 'files': len(files), 'repo': str(ROOT)}))
