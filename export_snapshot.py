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
nvfp4_parallel_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-parallel-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
extra_lane_units = {str(lane): subprocess.run(['systemctl', '--user', 'is-active', f'muse-nvfp4-exact-tb-extra-lane{lane}-2866-20261019.service'], capture_output=True, text=True).stdout.strip() for lane in (2, 3)}
extra_gpu_watcher_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-extra-gpu-watcher-20261019.service'], capture_output=True, text=True).stdout.strip()
extra_gpu_jobs = (2923, 2924, 2927, 2928)
queued_gpu_result = subprocess.run(['squeue', '-h', '-j', ','.join(map(str, extra_gpu_jobs)), '-o', '%i|%T|%N|%S'], capture_output=True, text=True, check=True)
extra_gpu_allocations = {}
for line in queued_gpu_result.stdout.splitlines():
    job, state, nodes, start = line.split('|', 3)
    extra_gpu_allocations[job] = {'state': state, 'nodes': nodes, 'scheduler_start': start}
extra_gpu_status = ', '.join(f'{job} {extra_gpu_allocations.get(str(job), {}).get("state", "not_in_queue")}' for job in extra_gpu_jobs)
nvfp4_rounds = json.loads(json.dumps(exact['models']['muse_nvfp4']['rounds']))
new_terminal_by_round = {str(i): {} for i in (1, 2, 3)}
new_raw_responses = 0
new_raw_response_latest_mtime = None
new_raw_response_by_batch = {}
active_recovery_trial_dirs = 0
for item in nvfp4_recovery['configurations']:
    rnd = str(item['round'])
    batch_raw_count = 0
    for trial in (B / 'tb_v1_exact_images_20261019/results/muse_nvfp4' / item['job_name']).glob('*'):
        if not trial.is_dir():
            continue
        raw_files = list((trial / 'agent/raw_responses').glob('*.json'))
        new_raw_responses += len(raw_files)
        batch_raw_count += len(raw_files)
        for raw_file in raw_files:
            stamp = raw_file.stat().st_mtime
            new_raw_response_latest_mtime = stamp if new_raw_response_latest_mtime is None else max(new_raw_response_latest_mtime, stamp)
        result = trial / 'result.json'
        if not result.exists():
            active_recovery_trial_dirs += 1
            continue
        value = read(result)
        if not value.get('finished_at'):
            active_recovery_trial_dirs += 1
            continue
        task = Path(value['config']['task']['path']).name
        assert task in item['tasks'] and task not in new_terminal_by_round[rnd]
        new_terminal_by_round[rnd][task] = {'reward': ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward'), 'source': str(result)}
    if batch_raw_count:
        new_raw_response_by_batch[item['job_name']] = batch_raw_count
new_raw_response_latest_utc = datetime.fromtimestamp(new_raw_response_latest_mtime, timezone.utc).isoformat() if new_raw_response_latest_mtime is not None else None
for rnd, rows in new_terminal_by_round.items():
    nvfp4_rounds[rnd]['terminal'] += len(rows)
    nvfp4_rounds[rnd]['graded'] += sum(row['reward'] in (0, 1) for row in rows.values())
    nvfp4_rounds[rnd]['success'] += sum(row['reward'] == 1 for row in rows.values())
    nvfp4_rounds[rnd]['complete'] = nvfp4_rounds[rnd]['graded'] == 89
    nvfp4_rounds[rnd]['accuracy'] = nvfp4_rounds[rnd]['success'] / 89 if nvfp4_rounds[rnd]['complete'] else None


def tb_profile_status(rounds):
    if all(row['complete'] for row in rounds.values()):
        return 'complete_three_rounds'
    if rounds['1']['complete']:
        return 'round_1_complete_later_rounds_partial'
    return 'partial_no_full_score'


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
            'tb2_1_exact_supplied_images': {'rounds': nvfp4_rounds, 'status': tb_profile_status(nvfp4_rounds), 'recovery': {'controller': nvfp4_recovery_unit, 'parallel_controller': nvfp4_parallel_unit, 'extra_lane_controllers': extra_lane_units, 'extra_gpu_watcher': extra_gpu_watcher_unit, 'existing_graded_round_1': len(nvfp4_recovery['existing_scored_results']['1']), 'queued_round_1': sum(len(c['tasks']) for c in nvfp4_recovery['configurations'] if c['round'] == 1), 'new_terminal_by_round': {k: len(v) for k, v in new_terminal_by_round.items()}, 'new_raw_model_responses': new_raw_responses, 'new_raw_model_responses_by_batch': new_raw_response_by_batch, 'latest_new_raw_model_response_utc': new_raw_response_latest_utc, 'active_recovery_trial_dirs': active_recovery_trial_dirs, 'user_cutover_interrupted_ungraded': len(nvfp4_recovery['user_cutover_interrupted_ungraded_trials']), 'extra_gpu_allocations': extra_gpu_allocations, 'qualification': nvfp4_recovery['qualification']}},
        },
        'beam_bf16': {
            'model': 'reflection/Beam-1.0-501B-A23B',
            'swe_bench_pro_verified': metric(ex['beam_bf16']['pro'], 'pro', 'partial_no_full_score'),
            'deepswe': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['beam_bf16']['deep'].items()},
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['beam_bf16']['tb'].items()},
            'tb2_1_exact_supplied_images': {'rounds': exact['models']['beam_bf16']['rounds'], 'status': tb_profile_status(exact['models']['beam_bf16']['rounds'])},
            'swrbench': {'status': 'complete', 'expected': 1000, 'judged': br['swrbench']['judged'], 'accuracy': br['swrbench']['final_metrics']['overall']['accuracy'], 'f1': br['swrbench']['final_metrics']['overall']['f1'], 'judge': 'gpt-5.5'},
            'swe_review': {key: metric(value, key, 'partial_no_full_rrr') for key, value in br['swe_review'].items() if isinstance(value, dict) and 'expected' in value},
        },
        'opus_4_7': {
            'model': 'Claude Opus 4.7',
            'swe_bench_pro_verified': metric(ex['opus47']['pro'], 'pro', 'partial_no_full_score'),
            'deepswe': {k: metric(v, k, 'complete' if v['graded'] == v['expected'] else 'partial_no_full_score') for k, v in ex['opus47']['deep'].items()},
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'complete' if v['graded'] == v['expected'] else 'partial_no_full_score') for k, v in ex['opus47']['tb'].items()},
            'tb2_1_exact_supplied_images': {'rounds': exact['models']['opus47']['rounds'], 'status': tb_profile_status(exact['models']['opus47']['rounds'])},
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
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['tb'].items()},
            'tb2_1_exact_supplied_images': {'status': 'not_started', 'qualification': 'Legacy benchmark task images are not counted as exact supplied-image trials.'},
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
asset_count = len(list((ROOT / 'input_output/archive_manifests').glob('*.json')))
release_audit_path = ROOT / 'evidence/release-assets-verification.json'
release_audit = read(release_audit_path) if release_audit_path.exists() else {}
verified_asset_count = release_audit.get('sha256_and_size_match_count', 0)
release_audit_label = f'{verified_asset_count}/{asset_count}'
latest_opus_exact_archive = read(sorted((ROOT / 'input_output/archive_manifests').glob('opus47_exact_tb_live_*.json'))[-1])
latest_beam_exact_archive = read(sorted((ROOT / 'input_output/archive_manifests').glob('beam_bf16_exact_tb_live_*.json'))[-1])
latest_legacy_deltas = {group: read(sorted((ROOT / 'input_output/archive_manifests').glob(f'{group}_delta_*.json'))[-1]) for group in ('opus47_legacy', 'beam_legacy', 'muse_bf16')}
mn = models['muse_nvfp4']
be = models['beam_bf16']
op = models['opus_4_7']
mn_tb = mn['tb2_1_exact_supplied_images']['rounds']['1']
be_tb = be['tb2_1_exact_supplied_images']['rounds']['1']
op_tb = op['tb2_1_exact_supplied_images']['rounds']['1']


def tb_en(row):
    return f"**{row['success']}/89 = {row['accuracy']:.2%}**, round 1 complete" if row['complete'] else f"{row['graded']}/89 graded; {row['success']} success, round 1 partial"


def tb_zh(row):
    return f"**{row['success']}/89（{row['accuracy']:.2%}）**，首轮完整" if row['complete'] else f"**{row['graded']}/89 已判分、{row['success']} 成功**，首轮未完成"


muse_exact_zh_done = f'；精确镜像 TB2.1 首轮 {tb_zh(mn_tb)}' if mn_tb['complete'] else ''
muse_exact_zh_pending = '' if mn_tb['complete'] else f'精确镜像 TB2.1 首轮 {tb_zh(mn_tb)}；'
beam_exact_zh_done = f'；精确镜像 TB2.1 首轮 {tb_zh(be_tb)}' if be_tb['complete'] else ''
beam_exact_zh_pending = '' if be_tb['complete'] else f'；精确镜像 TB2.1 首轮 {tb_zh(be_tb)}'
opus_exact_zh_done = f'；精确镜像 TB2.1 首轮 {tb_zh(op_tb)}' if op_tb['complete'] else ''
opus_exact_zh_pending = '' if op_tb['complete'] else f'；精确镜像 TB2.1 首轮 {tb_zh(op_tb)}'
mn_exact_note_zh = f"精确镜像首轮已完成：**{mn_tb['success']}/89（{mn_tb['accuracy']:.2%}）**。" if mn_tb['complete'] else f"精确镜像首轮只判分 {mn_tb['graded']}/89，不能当成最终准确率。"
readme = f'''# Agent benchmark evaluation snapshot

Snapshot: **{now}**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/` and the [native archive release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot); each archive has a SHA-256 manifest.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | {tb_en(mn_tb)} | {review(mn['swe_review'])} |
| Beam BF16 | {partial(be['swe_bench_pro_verified'])} | {partial(be['deepswe']['1'])}, round 1 | **55.6%** (1000/1000 judged) | {tb_en(be_tb)} | {review(be['swe_review'])} |
| Opus 4.7 | {partial(op['swe_bench_pro_verified'])} | **51/113**, round 1 complete; round 2 partial | — | {tb_en(op_tb)} | — |
| Opus 4.8 (historical) | **503/731 = 68.81%**, completed run; 3 confirmed solution retrieval cases | — | — | — | — |
| Muse original BF16 | {partial(models['muse_bf16']['swe_bench_pro_verified'])} | {partial(models['muse_bf16']['deepswe']['1'])}, round 1 | Queued after Pro round 1 | Not started; legacy cached-tag round 1: {partial(models['muse_bf16']['tb2_1_legacy_cached_tag']['1'])} | Queued after Pro round 1 |

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse legacy rounds 2/3 remain **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}** and **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is {be['tb2_1_legacy_cached_tag']['1']['success']}/{be['tb2_1_legacy_cached_tag']['1']['graded']} graded and partial. None of these partial counts is a full benchmark accuracy. The exact-image TB2.1 scores must not be pooled with legacy-image scores.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_canonical_results.json` maps all 339 graded DeepSWE trials to their exact native results. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; use the release archives and `input_output/archive_manifests/` to check coverage and SHA-256. For SWE-Review, use the `*_review_full_io` assets, which include OpenHands completion JSON in addition to trajectories.

Current exact-image TB2.1 native I/O snapshots: `{latest_opus_exact_archive['archive_name']}` contains {latest_opus_exact_archive['terminal_result_count']} terminal Opus 4.7 trials; `{latest_beam_exact_archive['archive_name']}` contains {latest_beam_exact_archive['terminal_result_count']} terminal Beam trials. These snapshots include in-progress trajectories but do not convert partial rounds into final benchmark scores.

The [Opus 4.7](evidence/opus47_exact_round1_audit.json) and [Beam](evidence/beam_bf16_exact_round1_audit.json) first-round audits reconcile each task with its reward and released input, raw response, and trajectory. A full round is reported only when all 89 task results pass this check.

For actively changing Pro/legacy/Deep results, apply each timestamped delta after its base archive, replacing earlier files with the same path. Current delta assets are `{latest_legacy_deltas['opus47_legacy']['archive_name']}`, `{latest_legacy_deltas['beam_legacy']['archive_name']}`, and `{latest_legacy_deltas['muse_bf16']['archive_name']}`. Their manifests state the cutoff and source scope.

The historical Opus 4.8 Pro Verified result has an existing 731-task trajectory archive in the release. Three confirmed solution retrieval cases are flagged; a conservative supplementary calculation withholding those three credits is **500/731 = 68.40%**. The raw benchmark value stays **503/731**.

The release has {asset_count} archive manifests; **{release_audit_label} assets** have a matching GitHub-reported SHA-256 digest and size in `evidence/release-assets-verification.json`. The latest exact-image TB archive is a timestamped snapshot containing both terminal results and ongoing trajectories; only terminal `result.json` files count as scores.

Muse NVFP4 round-one inputs are in `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst` (all 89 public `task.toml` files, original job configs, and image identity checks). The [I/O coverage audit](evidence/muse_nvfp4_exact_io_coverage.json) verifies that the released archives contain every scored result, its raw response and trajectory, and all task inputs.

Muse NVFP4 exact-image TB2.1 stopped when two model nodes were reassigned to original BF16. Four disjoint continuation lanes are now active on the surviving NVFP4 node 2866, with up to eight simultaneous task trials: 11 previously graded round-1 results are locked, 70 tasks had not been sampled, and 8 interrupted ungraded attempts retain their original partial outputs and are labeled infrastructure replacements. At this snapshot, the continuation has {new_raw_responses} raw model responses, {active_recovery_trial_dirs} active trial directories, and the latest response at {new_raw_response_latest_utc}; these are activity indicators, not scores. The original controller verifies delegated batches before advancing, preventing duplicate scoring. The [first-round task audit](evidence/muse_nvfp4_exact_round1_audit.json) checks task coverage, duplicate draws, frozen original results, endpoint settings, rewards, and preserved raw reasoning; the final score is published only after all 89 tasks pass reconciliation. Additional GPU allocation states: {extra_gpu_status}. A watcher starts the pinned Muse service when one of these allocations is granted; evaluator task assignment still requires a disjoint-task handoff. This continuation is separate from both the legacy-image scores and the BF16 evaluation.

Scores are benchmark-recorded values. A targeted [Muse exact-TB spot check](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json) found returned reasoning in every raw response of the five completed successful recovery tasks checked. One agent created `/tests/filter.py` by copying the exposed, unchanged `/app/filter.py` to run the task's permitted local test; no filter/verifier rewrite was observed in its commands. This is not a full reward-hacking clearance. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.

The [exact-TB command screen](evidence/exact_tb_integrity_screen.json) and [anchored manual notes](evidence/exact_tb_integrity_manual_notes.json) flag two successful Muse NVFP4 trajectories (`password-recovery`, `configure-git-webserver`) that attempted verifier-log or host-boundary access. Inspected outputs did not show successful hidden-answer retrieval. Their raw benchmark rewards are retained; both are excluded from clean training export pending full review. Keyword screening does not clear other trajectories.
'''
(ROOT / 'README.md').write_text(readme)
chinese_report = f'''# 模型评测结果快照

更新时间：**{now}**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**{muse_exact_zh_done} | {muse_exact_zh_pending}SWE-Review 三组尚无完整官方 RRR |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）**{beam_exact_zh_done} | Pro Verified **{be['swe_bench_pro_verified']['graded']}/731 已判分、{be['swe_bench_pro_verified']['success']} 成功**；DeepSWE 首轮 **{be['deepswe']['1']['graded']}/113、{be['deepswe']['1']['success']} 成功**{beam_exact_zh_pending}；SWE-Review 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 首轮 **51/113（45.13%）**{opus_exact_zh_done} | Pro Verified **{op['swe_bench_pro_verified']['graded']}/731 已判分、{op['swe_bench_pro_verified']['success']} 成功**{opus_exact_zh_pending} |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | 暂无完整 benchmark 分数 | Pro Verified **{models['muse_bf16']['swe_bench_pro_verified']['graded']}/731 已判分**；**旧缓存镜像** TB2.1 首轮 **{models['muse_bf16']['tb2_1_legacy_cached_tag']['1']['graded']}/89 已判分**；精确镜像尚未启动，DeepSWE 运行中 |

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}**、**{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}**，尚无三轮均值。{mn_exact_note_zh}两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 {new_raw_responses} 条原始模型响应、{active_recovery_trial_dirs} 个运行中题目目录，最新响应时间为 {new_raw_response_latest_utc}；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。新增 GPU 申请状态：{extra_gpu_status}。监控器会在获配后自动启动同一 NVFP4 模型服务，题目移交仍需核对互不重叠的任务清单。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)标出了 Muse NVFP4 的两条成功轨迹：`password-recovery` 尝试访问 verifier 日志和容器边界路径，`configure-git-webserver` 尝试访问 verifier 日志；已检查的命令输出未显示成功取得隐藏答案。两条仍保留原始 benchmark 判分，但在全面复核前排除出“干净训练轨迹”。关键词未命中也不代表轨迹已获干净认证。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 {asset_count} 个归档，优先使用 SWE-Review 的 `*_review_full_io.tar.zst`（含 OpenHands completions）。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 {release_audit_label}**，逐项核验见 `evidence/release-assets-verification.json`。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `{latest_opus_exact_archive['archive_name']}`（{latest_opus_exact_archive['terminal_result_count']} 个终态结果）和 `{latest_beam_exact_archive['archive_name']}`（{latest_beam_exact_archive['terminal_result_count']} 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `{latest_legacy_deltas['opus47_legacy']['archive_name']}`、`{latest_legacy_deltas['beam_legacy']['archive_name']}`、`{latest_legacy_deltas['muse_bf16']['archive_name']}`；截止时间和文件范围见各自清单。
'''
(ROOT / 'REPORT.zh-CN.md').write_text(chinese_report)
print(json.dumps({'snapshot': now, 'files': len(files), 'repo': str(ROOT)}))
