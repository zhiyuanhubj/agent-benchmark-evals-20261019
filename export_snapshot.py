#!/usr/bin/env python3
"""Publish a reproducible, explicitly qualified snapshot of local eval state."""
import hashlib
import json
import shutil
import subprocess
import sys
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
subprocess.run([sys.executable, str(ROOT / 'audit_muse_bf16_exact_images.py')], check=True)
bf16_identity = read(ROOT / 'evidence/muse_bf16_exact_image_identity.json')
assert not bf16_identity['errors'] and bf16_identity['live_node_check']['checked'] == 89
opus48 = read(O48 / 'completed_full_evaluation_result.json')
nvfp4_recovery = read(B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/completion-2866-plan.json')
nvfp4_recovery_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-completion-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
nvfp4_parallel_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-parallel-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
extra_lane_units = {str(lane): subprocess.run(['systemctl', '--user', 'is-active', f'muse-nvfp4-exact-tb-extra-lane{lane}-2866-20261019.service'], capture_output=True, text=True).stdout.strip() for lane in (2, 3)}
extra_gpu_watcher_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-extra-gpu-watcher-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2867_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-serve-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2919_controller = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-handoff-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2867_r23_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-r23-replica-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_state = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867'
replica_handoff = read(replica_state / 'r1-b06-b07-handoff.json') if (replica_state / 'r1-b06-b07-handoff.json').exists() else None
replica_ready = (replica_state / 'endpoint-ready.json').exists()
replica_r23_status_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes/2867-controller-status.json'
replica_r23_status = read(replica_r23_status_path) if replica_r23_status_path.exists() else None
extra_gpu_jobs = (2923, 2924, 2927, 2928)
queued_gpu_result = subprocess.run(['squeue', '-h', '-j', ','.join(map(str, extra_gpu_jobs)), '-o', '%i|%T|%N|%S'], capture_output=True, text=True, check=True)
extra_gpu_allocations = {}
for line in queued_gpu_result.stdout.splitlines():
    job, state, nodes, start = line.split('|', 3)
    extra_gpu_allocations[job] = {'state': state, 'nodes': nodes, 'scheduler_start': start}
extra_gpu_status = ', '.join(f'{job} {extra_gpu_allocations.get(str(job), {}).get("state", "not_in_queue")}' for job in extra_gpu_jobs)
early_b05_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu/r1-b05-early-owner.json'
early_b05_owner = read(early_b05_path) if early_b05_path.exists() else None
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
        new_terminal_by_round[rnd][task] = {
            'reward': ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward'),
            'exception': (value.get('exception_info') or {}).get('exception_type'),
            'source': str(result),
        }
    if batch_raw_count:
        new_raw_response_by_batch[item['job_name']] = batch_raw_count
new_raw_response_latest_utc = datetime.fromtimestamp(new_raw_response_latest_mtime, timezone.utc).isoformat() if new_raw_response_latest_mtime is not None else None
for rnd, rows in new_terminal_by_round.items():
    nvfp4_rounds[rnd]['terminal'] += len(rows)
    nvfp4_rounds[rnd]['graded'] += sum(row['reward'] in (0, 1) for row in rows.values())
    nvfp4_rounds[rnd]['success'] += sum(row['reward'] == 1 for row in rows.values())
    for row in rows.values():
        if row['exception']:
            kind = row['exception']
            nvfp4_rounds[rnd]['exceptions'][kind] = nvfp4_rounds[rnd]['exceptions'].get(kind, 0) + 1
    nvfp4_rounds[rnd]['complete'] = nvfp4_rounds[rnd]['graded'] == 89
    nvfp4_rounds[rnd]['accuracy'] = nvfp4_rounds[rnd]['success'] / 89 if nvfp4_rounds[rnd]['complete'] else None


def tb_profile_status(rounds):
    if all(row['complete'] for row in rounds.values()):
        return 'complete_three_rounds'
    if rounds['1']['complete']:
        return 'round_1_complete_later_rounds_partial'
    return 'partial_no_full_score'


bf16_io_path = ROOT / 'evidence/muse_bf16_exact_io_coverage.json'
bf16_io = read(bf16_io_path) if bf16_io_path.exists() else {}
bf16_source_round1 = ex['muse_bf16']['tb']['1']
bf16_complete = (bf16_source_round1['graded'] == 89 and
                 bf16_io.get('qualification') == 'complete_verified' and
                 (bf16_io.get('scored_tasks'), bf16_io.get('success_count')) ==
                 (bf16_source_round1['graded'], bf16_source_round1['success']))
bf16_tb_round1 = metric(bf16_source_round1, '1', 'complete' if bf16_complete else 'partial_no_full_score') | {
    'complete': bf16_complete, 'accuracy': bf16_source_round1['success'] / 89 if bf16_complete else None,
    'qualification': 'Same native trials as the legacy-named BF16 field; all 89 supplied image identities and task paths verified before launch and on the running node. Partial counts only.',
}


opus_pro_source = ex['opus47']['pro']
assert opus_pro_source['scoring_run_id'] == 'opus47-pro-full-r1'
assert opus_pro_source['terminal'] == opus_pro_source['unique_tasks'] == 731
assert not opus_pro_source['duplicate_task_ids']
opus_crosshost_path = ROOT / 'evidence/opus47_pro_eval_crosshost_2922.json'
opus_crosshost = read(opus_crosshost_path) if opus_crosshost_path.exists() else {}
opus_crosshost_status = opus_crosshost.get('status', 'not_started')
assert opus_crosshost_status in ('not_started', 'running', 'completed', 'needs_review')
opus_crosshost_en = {
    'not_started': 'An independent-host verification has not started.',
    'running': 'An independent-host verification of the same saved patch is in progress.',
    'completed': 'The independent-host verification completed; its separately recorded result awaits explicit score reconciliation.',
    'needs_review': 'The independent-host verification ended without a reconciled native score and needs review.',
}[opus_crosshost_status]
opus_crosshost_zh = {
    'not_started': '独立节点补验尚未启动。',
    'running': '同一补丁已在另一 CPU 节点独立补验，仍在运行。',
    'completed': '独立节点补验已完成，其单独记录的结果仍待明确并入计分。',
    'needs_review': '独立节点补验未得到已核对的原生评分，需进一步检查。',
}[opus_crosshost_status]

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
            'tb2_1_exact_supplied_images': {'rounds': nvfp4_rounds, 'status': tb_profile_status(nvfp4_rounds), 'recovery': {'controller': nvfp4_recovery_unit, 'parallel_controller': nvfp4_parallel_unit, 'extra_lane_controllers': extra_lane_units, 'extra_gpu_watcher': extra_gpu_watcher_unit, 'replica_2867': {'model_server': replica_2867_unit, 'cpu_controller_2919': replica_2919_controller, 'endpoint_ready': replica_ready, 'claimed_batches': [row['job_name'] for row in replica_handoff['batches']] if replica_handoff else [], 'handoff_receipt': str(replica_state / 'r1-b06-b07-handoff.json') if replica_handoff else None}, 'existing_graded_round_1': len(nvfp4_recovery['existing_scored_results']['1']), 'queued_round_1': sum(len(c['tasks']) for c in nvfp4_recovery['configurations'] if c['round'] == 1), 'new_terminal_by_round': {k: len(v) for k, v in new_terminal_by_round.items()}, 'new_raw_model_responses': new_raw_responses, 'new_raw_model_responses_by_batch': new_raw_response_by_batch, 'latest_new_raw_model_response_utc': new_raw_response_latest_utc, 'active_recovery_trial_dirs': active_recovery_trial_dirs, 'user_cutover_interrupted_ungraded': len(nvfp4_recovery['user_cutover_interrupted_ungraded_trials']), 'extra_gpu_allocations': extra_gpu_allocations, 'b05_early_owner': early_b05_owner, 'qualification': nvfp4_recovery['qualification']}},
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
            'swe_bench_pro_verified': metric(opus_pro_source, 'pro', 'partial_no_full_score') | {
                'scoring_run_id': opus_pro_source['scoring_run_id'],
                'verifier_recovery_run_ids_excluded': opus_pro_source['excluded_verifier_recovery_run_ids'],
                'crosshost_verifier_recovery_status': opus_crosshost_status,
                'qualification': 'Only the original 731-task run is counted. Saved-patch verifier-only retries are separate provenance and cannot add tasks or successes to the first-round score.',
            },
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
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['tb'].items()} | {'qualification': 'Historical field name for this same BF16 run; do not add these trials to the exact-image field as independent attempts.'},
            'tb2_1_exact_supplied_images': {'rounds': {'1': bf16_tb_round1}, 'status': 'round_1_complete' if bf16_complete else 'partial_no_full_score',
                'same_trials_as_legacy_named_bf16_tb': True,
                'image_identity_audit': 'evidence/muse_bf16_exact_image_identity.json',
                'released_io_audit': 'evidence/muse_bf16_exact_io_coverage.json',
                'qualification': 'The 89 supplied archive image identities, task paths and agent settings were verified before BF16 round 1 launched and rechecked on the running node. A full-round accuracy awaits all 89 native results and task-level audit.'},
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
        'muse_bf16_exact_image_identity_audit': str(ROOT / 'evidence/muse_bf16_exact_image_identity.json'),
        'muse_bf16_exact_released_io_audit': str(bf16_io_path),
    },
}
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['replica_2867'].update({
    'round23_controller': replica_2867_r23_unit,
    'round23_status': replica_r23_status,
})
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
if replica_handoff:
    source = replica_state / 'r1-b06-b07-handoff.json'
    dest = ROOT / 'evidence/muse_nvfp4_exact_replica_handoff.json'
    shutil.copy2(source, dest)
    files[str(dest.relative_to(ROOT))] = {'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(), 'size_bytes': dest.stat().st_size, 'source': str(source)}
bf16_audit_path = ROOT / 'evidence/muse_bf16_exact_image_identity.json'
files[str(bf16_audit_path.relative_to(ROOT))] = {'sha256': hashlib.sha256(bf16_audit_path.read_bytes()).hexdigest(), 'size_bytes': bf16_audit_path.stat().st_size,
    'source': str(bf16_audit_path)}
if bf16_io_path.exists():
    files[str(bf16_io_path.relative_to(ROOT))] = {'sha256': hashlib.sha256(bf16_io_path.read_bytes()).hexdigest(),
        'size_bytes': bf16_io_path.stat().st_size, 'source': str(bf16_io_path)}
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
mn_audit = read(ROOT / 'evidence/muse_nvfp4_exact_round1_audit.json')
manual_notes = read(ROOT / 'evidence/exact_tb_integrity_manual_notes.json')['notes']
nvfp4_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_nvfp4'
                        and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
bf16_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_bf16'
                       and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
nvfp4_r2_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_nvfp4_r2'
                           and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
nvfp4_excluded_names = ', '.join(f'`{name}`' for name in nvfp4_excluded)
nvfp4_r2_excluded_names = ', '.join(f'`{name}`' for name in nvfp4_r2_excluded)
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
bf16_exact_zh_done = f'；指定精确镜像 TB2.1 首轮 {tb_zh(bf16_tb_round1)}' if bf16_tb_round1['complete'] else ''
bf16_exact_zh_pending = '' if bf16_tb_round1['complete'] else f'；指定精确镜像 TB2.1 首轮 {tb_zh(bf16_tb_round1)}'
mn_exact_note_zh = f"精确镜像首轮已完成：**{mn_tb['success']}/89（{mn_tb['accuracy']:.2%}）**。" if mn_tb['complete'] else f"精确镜像首轮只判分 {mn_tb['graded']}/89，不能当成最终准确率。"
mn_timeout_count = mn_tb['exceptions'].get('AgentTimeoutError', 0)
mn_timeout_en = f"Of the graded Muse exact-image tasks, {mn_timeout_count} received a verifier score after reaching the protocol's agent time limit. Their timeout status remains visible in the task audit; these tasks are not resampled within round 1.\n\n" if mn_timeout_count else ''
mn_timeout_zh = f"**超时判分说明。** Muse 精确镜像已判分题目中有 {mn_timeout_count} 题达到协议规定的 agent 时限后仍得到 verifier 分数；逐题审计保留超时标记，首轮不重抽这些题。\n\n" if mn_timeout_count else ''
if replica_handoff:
    replica_note_en = 'Two untouched round-1 batches (18 tasks) are assigned to the NVFP4 replica on GPU allocation 2867 with evaluator allocation 2919. The handoff records original and effective config hashes; only the endpoint and trial concurrency change.'
    replica_note_zh = '另有首轮 18 道尚未启动的题已按原配置哈希移交给 2867 的 NVFP4 副本和 2919 的评测器；只调整模型接口和任务并发数，保留原配置与结果。'
elif replica_2867_unit == 'active':
    replica_note_en = 'A second NVFP4 server is loading on GPU allocation 2867. Its evaluator on 2919 will claim two untouched batches (18 tasks) only after the model endpoint is ready.'
    replica_note_zh = '第二个 NVFP4 服务正在 2867 加载，2919 评测器待接口就绪后才会认领 18 道未启动的题。'
else:
    replica_note_en = ''
    replica_note_zh = ''
if replica_r23_status:
    replica_note_en += (f" On 2867, the disjoint round-2/3 controller is {replica_2867_r23_unit} "
                        f"with phase {replica_r23_status['phase']} and current batch "
                        f"{replica_r23_status.get('job_name', 'none')}; its ownership receipt prevents a duplicate draw.")
    replica_note_zh += (f" 2867 上独立的第 2/3 轮控制器状态为 {replica_2867_r23_unit}，"
                        f"阶段 {replica_r23_status['phase']}，当前批次 "
                        f"{replica_r23_status.get('job_name', '无')}；批次归属凭据阻止重复抽题。")
readme = f'''# Agent benchmark evaluation snapshot

Snapshot: **{now}**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/` and the [native archive release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot); each archive has a SHA-256 manifest.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | {tb_en(mn_tb)} | {review(mn['swe_review'])} |
| Beam BF16 | {partial(be['swe_bench_pro_verified'])} | {partial(be['deepswe']['1'])}, round 1 | **55.6%** (1000/1000 judged) | {tb_en(be_tb)} | {review(be['swe_review'])} |
| Opus 4.7 | {partial(op['swe_bench_pro_verified'])} | **51/113**, round 1 complete; round 2 partial | — | {tb_en(op_tb)} | — |
| Opus 4.8 (historical) | **503/731 = 68.81%**, completed run; 3 confirmed solution retrieval cases | — | — | — | — |
| Muse original BF16 | {partial(models['muse_bf16']['swe_bench_pro_verified'])} | {partial(models['muse_bf16']['deepswe']['1'])}, round 1 | Queued after Pro round 1 | {tb_en(bf16_tb_round1)}; [89 image identities verified](evidence/muse_bf16_exact_image_identity.json) | Queued after Pro round 1 |

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse NVFP4 legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse NVFP4 legacy rounds 2/3 remain **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}** and **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is {be['tb2_1_legacy_cached_tag']['1']['success']}/{be['tb2_1_legacy_cached_tag']['1']['graded']} graded and partial. The original BF16 run is an exception to the old file label: its 89 image identities and tasks match the supplied archive, so its historical `tb2_1_legacy_cached_tag` field and exact-image field refer to **the same trials**, not two samples. None of the partial counts is a full benchmark accuracy. Independent exact-image and legacy-image trials must not be pooled.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_canonical_results.json` maps all 339 graded DeepSWE trials to their exact native results. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; use the release archives and `input_output/archive_manifests/` to check coverage and SHA-256. For SWE-Review, use the `*_review_full_io` assets, which include OpenHands completion JSON in addition to trajectories.

Current exact-image TB2.1 native I/O snapshots: `{latest_opus_exact_archive['archive_name']}` contains {latest_opus_exact_archive['terminal_result_count']} terminal Opus 4.7 trials; `{latest_beam_exact_archive['archive_name']}` contains {latest_beam_exact_archive['terminal_result_count']} terminal Beam trials. These snapshots include in-progress trajectories but do not convert partial rounds into final benchmark scores.

The [Opus 4.7](evidence/opus47_exact_round1_audit.json) and [Beam](evidence/beam_bf16_exact_round1_audit.json) first-round audits reconcile each task with its reward and released input, raw response, and trajectory. A full round is reported only when all 89 task results pass this check.

The [Muse BF16 exact-image I/O audit](evidence/muse_bf16_exact_io_coverage.json) checks that every scored BF16 result, raw response and trajectory is present in SHA-verified release archives, along with all 89 task inputs. Of its currently scored raw replies, **{bf16_io.get('nonempty_reasoning_response_count', 0)}/{bf16_io.get('scored_raw_response_count', 0)}** contain nonempty thinking. It is the same BF16 trial set named by the historical cached-tag field.

For actively changing Pro/legacy/Deep results, apply each timestamped delta after its base archive, replacing earlier files with the same path. Current delta assets are `{latest_legacy_deltas['opus47_legacy']['archive_name']}`, `{latest_legacy_deltas['beam_legacy']['archive_name']}`, and `{latest_legacy_deltas['muse_bf16']['archive_name']}`. Their manifests state the cutoff and source scope.

The historical Opus 4.8 Pro Verified result has an existing 731-task trajectory archive in the release. Three confirmed solution retrieval cases are flagged; a conservative supplementary calculation withholding those three credits is **500/731 = 68.40%**. The raw benchmark value stays **503/731**.

The release has {asset_count} archive manifests; **{release_audit_label} assets** have a matching GitHub-reported SHA-256 digest and size in `evidence/release-assets-verification.json`. The latest exact-image TB archive is a timestamped snapshot containing both terminal results and ongoing trajectories; only terminal `result.json` files count as scores.

Muse NVFP4 round-one inputs are in `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst` (all 89 public `task.toml` files, original job configs, and image identity checks). The [I/O coverage audit](evidence/muse_nvfp4_exact_io_coverage.json) verifies that the released archives contain every scored result, its raw response and trajectory, and all task inputs.

The [round-one task audit](evidence/muse_nvfp4_exact_round1_audit.json) currently finds nonempty returned thinking in **{mn_audit.get('scored_nonempty_reasoning_response_count', 0)}/{mn_audit.get('scored_raw_response_count', 0)}** raw responses of scored Muse NVFP4 tasks. This is a field-preservation check, not a clean-trajectory verdict.

Muse NVFP4 exact-image TB2.1 stopped when two model nodes were reassigned to original BF16. Four disjoint continuation lanes are now active on the surviving NVFP4 node 2866, with up to eight simultaneous task trials: 11 previously graded round-1 results are locked, 70 tasks had not been sampled, and 8 interrupted ungraded attempts retain their original partial outputs and are labeled infrastructure replacements. At this snapshot, the continuation has {new_raw_responses} raw model responses, {active_recovery_trial_dirs} active trial directories, and the latest response at {new_raw_response_latest_utc}; these are activity indicators, not scores. The original controller verifies delegated batches before advancing, preventing duplicate scoring. The [first-round task audit](evidence/muse_nvfp4_exact_round1_audit.json) checks task coverage, duplicate draws, frozen original results, endpoint settings, rewards, and preserved raw reasoning; the final score is published only after all 89 tasks pass reconciliation. Additional GPU allocation states: {extra_gpu_status}. A watcher starts the pinned Muse service when a queued allocation is granted. A ready extra GPU atomically claims one untouched round-one batch from b03 or b05; the released 2812 allocation can claim up to two. The existing CPU evaluators retain their original tasks and images, and only the model endpoint changes. A batch that starts locally first cannot be redrawn on another node. This continuation is separate from both the legacy-image scores and the BF16 evaluation.

Scores are benchmark-recorded values. A targeted [Muse exact-TB spot check](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json) found returned reasoning in every raw response of the five completed successful recovery tasks checked. One agent created `/tests/filter.py` by copying the exposed, unchanged `/app/filter.py` to run the task's permitted local test; no filter/verifier rewrite was observed in its commands. This is not a full reward-hacking clearance. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.

The [exact-TB command screen](evidence/exact_tb_integrity_screen.json) and [anchored manual notes](evidence/exact_tb_integrity_manual_notes.json) currently exclude {len(nvfp4_excluded)} successful Muse NVFP4 trajectories and {len(bf16_excluded)} successful Muse BF16 trajectories from clean training export. The excluded NVFP4 tasks are {nvfp4_excluded_names}; their targeted notes document verifier-log probes, a copy into `/tests/filter.py`, or timing manipulation; the reviewed verifier probes did not confirm hidden-answer retrieval. Both BF16 and NVFP4 `largest-eigenval` scored reward 1.0 after patching timers and slowing the reference eigensolver. Their raw rewards are retained and [the NVFP4 final trajectory review](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json) is anchored by SHA-256, but neither reward demonstrates an unmodified speedup. A separate pre-score alert records NVFP4 [host-boundary probes on `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json); it does not prove successful access or a final score. Keyword screening does not clear other trajectories.
'''
readme = readme.replace('Additional GPU allocation states:', replica_note_en + ' Additional GPU allocation states:', 1)
readme = readme.replace('A batch that starts locally first cannot be redrawn on another node.', 'A batch that starts locally first cannot be redrawn on another node. The four queued extra GPU allocations are also prepared to take only untouched round-2/3 batches if granted after the round-1 handoffs are claimed. Per-batch locks and ownership receipts prevent the original controller from drawing the same task; the effective config changes only the model endpoint.', 1)
readme = readme.replace('Scores are benchmark-recorded values.', f'Opus 4.7 Pro counts only its original 731-task run; verifier-only saved-patch retries are retained as separate evidence and never increase the first-round task denominator. One original task still lacks a native verifier score after two 3600-second timeouts. {opus_crosshost_en}\n\nScores are benchmark-recorded values.', 1)
if nvfp4_r2_excluded:
    readme = readme.replace('Scores are benchmark-recorded values.',
                            f'Muse NVFP4 round-2 successful trajectories flagged for training exclusion pending full review: {nvfp4_r2_excluded_names}. A targeted review found a verifier-directory listing with no hidden output in the observed response; raw benchmark rewards are unchanged. See [the anchored notes](evidence/exact_tb_integrity_manual_notes.json) and [command screen](evidence/exact_tb_integrity_screen.json).\n\nScores are benchmark-recorded values.', 1)
readme = readme.replace('Scores are benchmark-recorded values.', mn_timeout_en + 'Scores are benchmark-recorded values.', 1)
if early_b05_owner:
    readme = readme.replace('This continuation is separate from both the legacy-image scores and the BF16 evaluation.', 'At this snapshot, b05 is running early on CPU allocation 2922 against GPU 2812; an ownership receipt makes sequential lane 3 verify its completed tasks and skip a duplicate draw. This continuation is separate from both the legacy-image scores and the BF16 evaluation.', 1)
readme = readme.replace('Keyword screening does not clear other trajectories.', 'Keyword screening does not clear other trajectories. Targeted [manual notes](evidence/exact_tb_integrity_manual_notes.json) also flag Opus 4.7 `break-filter-js-from-html` for an unsuccessful `/tests` probe and Beam BF16 on the same task for a temporary copy of the exposed filter into `/tests/filter.py` (removed before grading); neither inspected output confirms hidden-answer retrieval, and both are excluded from clean training pending full review. The Opus `torch-pipeline-parallelism` keyword hit was only a Python-executable listing.', 1)
db_wal_note = next((note for note in manual_notes if note['model'] == 'muse_nvfp4' and note['task'] == 'db-wal-recovery'), None)
if db_wal_note:
    assert db_wal_note['reward'] == 0.0
    old = 'A separate pre-score alert records NVFP4 [host-boundary probes on `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json); it does not prove successful access or a final score.'
    new = 'The earlier [host-boundary alert for `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json) now has a terminal result: the agent timed out after 10800 seconds with recorded reward 0. [Manual notes](evidence/exact_tb_integrity_manual_notes.json) exclude its trajectory from clean training; the inspected probes do not establish successful host access. The raw benchmark result remains unchanged.'
    assert readme.count(old) == 1
    readme = readme.replace(old, new, 1)
(ROOT / 'README.md').write_text(readme)
chinese_report = f'''# 模型评测结果快照

更新时间：**{now}**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**{muse_exact_zh_done} | {muse_exact_zh_pending}SWE-Review 三组尚无完整官方 RRR |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）**{beam_exact_zh_done} | Pro Verified **{be['swe_bench_pro_verified']['graded']}/731 已判分、{be['swe_bench_pro_verified']['success']} 成功**；DeepSWE 首轮 **{be['deepswe']['1']['graded']}/113、{be['deepswe']['1']['success']} 成功**{beam_exact_zh_pending}；SWE-Review 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**；DeepSWE 首轮 **51/113（45.13%）**{opus_exact_zh_done} | Pro Verified **{op['swe_bench_pro_verified']['graded']}/731 已判分、{op['swe_bench_pro_verified']['success']} 成功**{opus_exact_zh_pending} |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | {'暂无完整 benchmark 分数' if not bf16_tb_round1['complete'] else bf16_exact_zh_done.lstrip('；')} | Pro Verified **{models['muse_bf16']['swe_bench_pro_verified']['graded']}/731 已判分**{bf16_exact_zh_pending}；DeepSWE 运行中 |

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}**、**{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。{mn_exact_note_zh}两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 {new_raw_responses} 条原始模型响应、{active_recovery_trial_dirs} 个运行中题目目录，最新响应时间为 {new_raw_response_latest_utc}；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。新增 GPU 申请状态：{extra_gpu_status}。排队节点获配后监控器会启动同一 NVFP4 模型服务，并逐批加锁领取 b03、b05 中尚未启动的一批；early95 结束后腾出的 2812 最多可领取两批。原 CPU 评测器继续使用原题目和镜像，仅模型端点变化；若本地批次先启动，不会在其他节点重复抽题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 {len(nvfp4_excluded)} 条、Muse BF16 的 {len(bf16_excluded)} 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 {nvfp4_excluded_names}；逐题核查记录了 verifier 日志探查、向 `/tests/filter.py` 复制公开文件或计时篡改；已检查的 verifier 探查输出没有确认获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval` 都通过修改计时函数、拖慢参考特征值求解器拿到原始 reward 1；原始分数保留，NVFP4 的[最终轨迹审计](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)有哈希锚定，但这两条高分不能当作未经篡改的加速证据。另一份判分前预警记录了 NVFP4 [`db-wal-recovery` 对宿主边界的探查](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)，它不证明边界探查成功，也不是最终分数。关键词未命中也不代表轨迹已获干净认证。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 {asset_count} 个归档，优先使用 SWE-Review 的 `*_review_full_io.tar.zst`（含 OpenHands completions）。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 {release_audit_label}**，逐项核验见 `evidence/release-assets-verification.json`。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **{mn_audit.get('scored_nonempty_reasoning_response_count', 0)}/{mn_audit.get('scored_raw_response_count', 0)} 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **{bf16_io.get('nonempty_reasoning_response_count', 0)}/{bf16_io.get('scored_raw_response_count', 0)} 条含非空 thinking**。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `{latest_opus_exact_archive['archive_name']}`（{latest_opus_exact_archive['terminal_result_count']} 个终态结果）和 `{latest_beam_exact_archive['archive_name']}`（{latest_beam_exact_archive['terminal_result_count']} 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `{latest_legacy_deltas['opus47_legacy']['archive_name']}`、`{latest_legacy_deltas['beam_legacy']['archive_name']}`、`{latest_legacy_deltas['muse_bf16']['archive_name']}`；截止时间和文件范围见各自清单。
'''
chinese_report = chinese_report.replace('新增 GPU 申请状态：', replica_note_zh + ' 新增 GPU 申请状态：', 1)
if nvfp4_r2_excluded:
    chinese_report = chinese_report.replace('仍在增长的 Pro/旧镜像/DeepSWE 结果，',
        f'第 2 轮 Muse NVFP4 的成功轨迹 {nvfp4_r2_excluded_names} 曾探查 verifier 目录；已检查的返回为空，未证实获得隐藏答案。原始 reward 保留，轨迹暂不进入干净训练数据，见[哈希锚定核查](evidence/exact_tb_integrity_manual_notes.json)和[命令筛查](evidence/exact_tb_integrity_screen.json)。\n\n仍在增长的 Pro/旧镜像/DeepSWE 结果，', 1)
chinese_report = chinese_report.replace('若本地批次先启动，不会在其他节点重复抽题。', '若本地批次先启动，不会在其他节点重复抽题。另有四个排队 GPU 节点获配后只领取第 2/3 轮尚未启动的批次；逐批文件锁和接管凭据阻止原控制器重复抽题，实际配置仅修改模型端点。', 1)
chinese_report = chinese_report.replace('**审计限制。**', f'Opus 4.7 Pro 只统计原始运行的 731 道题；同一补丁的纯验证重试单独留证，不能增加首轮题数或成功数。原始运行仍有 1 题在两次 3600 秒验证超时后缺少有效评分。{opus_crosshost_zh}\n\n**审计限制。**', 1)
chinese_report = chinese_report.replace('**审计限制。**', mn_timeout_zh + '**审计限制。**', 1)
if early_b05_owner:
    chinese_report = chinese_report.replace('若本地批次先启动，不会在其他节点重复抽题。', '若本地批次先启动，不会在其他节点重复抽题。本次快照中 b05 已由 CPU 节点 2922 提前启动，调用 GPU 节点 2812；原顺序控制器稍后会核查同一批终态结果并跳过重复抽题。', 1)
chinese_report = chinese_report.replace('关键词未命中也不代表轨迹已获干净认证。', '关键词未命中也不代表轨迹已获干净认证。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)还标记了 Opus 4.7 在 `break-filter-js-from-html` 上对不存在的 `/tests` 的探查，以及 Beam BF16 在同题中把公开的过滤器临时复制到 `/tests/filter.py`、在判分前删除的行为；检查到的输出均未确认获得隐藏答案，两条轨迹暂不作为干净训练数据。Opus `torch-pipeline-parallelism` 的关键词命中只是列举 Python 可执行文件。', 1)
if db_wal_note:
    old = '另一份判分前预警记录了 NVFP4 [`db-wal-recovery` 对宿主边界的探查](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)，它不证明边界探查成功，也不是最终分数。'
    new = '此前的 NVFP4 [`db-wal-recovery` 宿主边界探查预警](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)现已有终态：agent 运行 10800 秒后超时，原始奖励为 0。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)将该轨迹排除出干净训练数据；抽查输出未证明成功越过宿主边界，原始评测结果保持不变。'
    assert chinese_report.count(old) == 1
    chinese_report = chinese_report.replace(old, new, 1)
(ROOT / 'REPORT.zh-CN.md').write_text(chinese_report)
print(json.dumps({'snapshot': now, 'files': len(files), 'repo': str(ROOT)}))
