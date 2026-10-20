#!/usr/bin/env python3
"""Publish a reproducible, explicitly qualified snapshot of local eval state."""
import hashlib
import json
import re
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


def completed_jsonl_ids(path):
    if not path.exists():
        return set()
    ids = set()
    with path.open() as stream:
        for line in stream:
            if not line.endswith('\n'):
                break  # A producer may still be writing its last JSONL record.
            if not line.strip():
                continue
            value = json.loads(line)
            item = value['instance_id']
            assert item not in ids, f'Duplicate native JSONL instance: {item}'
            ids.add(item)
    return ids


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
review_da = read(ROOT / 'evidence/swe_review_complete_split_da.json')
native_review_da = read(ROOT / 'evidence/swe_review_native_complete_da.json')
review_recovery = read(ROOT / 'evidence/swe_review_recovery_control.json')
review_revision_progress = read(ROOT / 'evidence/swe_review_revision_gateway_progress.json')
review_rrr = read(ROOT / 'evidence/swe_review_official_rrr.json') if (ROOT / 'evidence/swe_review_official_rrr.json').exists() else {'complete_splits': {}}
opus_review_progress = read(ROOT / 'evidence/opus47_swe_review_progress.json')
review_revision_rows = {(row['reviewer'], row['split']): row for row in review_revision_progress['groups']}
review_revision_muse_coder = review_revision_rows['muse-nvfp4', 'qwen3_coder_30b_500']
review_revision_muse_instruct = review_revision_rows['muse-nvfp4', 'qwen3_30b_instruct2507_500']
review_revision_beam_coder = review_revision_rows['beam-bf16', 'qwen3_coder_30b_500']
review_revision_beam_instruct = review_revision_rows['beam-bf16', 'qwen3_30b_instruct2507_500']
for split, row in review_da['reviewers'].get('muse-nvfp4', {}).items():
    assert mr['swe_review'][split]['terminal'] == row['expected']
    assert mr['swe_review'][split]['metrics_on_terminal_subset'] == row['metrics']
for split, row in native_review_da['splits'].items():
    assert mr['swe_review'][split]['terminal'] == row['expected']
    assert mr['swe_review'][split]['metrics_on_terminal_subset'] == row['metrics']
ex = read(B / 'expanded-current.json')
beam_pro = ex['beam_bf16']['pro']
assert beam_pro['expected'] == 731
assert not beam_pro['duplicate_task_ids'], 'Beam Pro task IDs overlap across original and handoff runs'
handoff_evidence = read(ROOT / 'evidence/beam_pro_disjoint_handoff_20261020.json')
assert handoff_evidence['declared_count'] == 603
assert handoff_evidence['terminal_count'] + handoff_evidence['pending_count'] == 603
assert not (set(handoff_evidence['terminal_ids']) & set(handoff_evidence['pending_ids']))
write('evidence/beam_pro_handoff_progress.json', {
    'generated_utc': now,
    'handoff_plan_evidence': 'evidence/beam_pro_disjoint_handoff_20261020.json',
    'expected': beam_pro['expected'],
    'terminal': beam_pro['terminal'],
    'graded': beam_pro['graded'],
    'success': beam_pro['success'],
    'missing_result_task_count': beam_pro['missing_result_task_count'],
    'duplicate_task_ids': beam_pro['duplicate_task_ids'],
    'qualification': 'Partial native first-round progress; all original and disjoint handoff task IDs are counted at most once. Not a full-set accuracy.',
})
bf16_expiry_recovery = read(ROOT / 'evidence/muse_bf16_2865_expiry_recovery.json')
assert bf16_expiry_recovery['pro_scoring_run_id'] == ex['muse_bf16']['pro']['scoring_run_id']
assert bf16_expiry_recovery['original_completed_pro_tasks_reused_once'] == ex['muse_bf16']['pro']['reused_original_completed_tasks']
br = read(B / 'current.json')
for split, row in review_da['reviewers'].get('beam-bf16', {}).items():
    assert br['swe_review'][split]['terminal'] == row['expected']
beam_malformed = read(ROOT / 'evidence/beam_swe_review_malformed_reports.json')
beam_malformed_count = sum(row['invalid_report_count'] for row in beam_malformed['splits'].values())
beam_prep_phase = (br.get('revision_preparation') or {}).get('phase', 'unknown')
exact = read(B / 'tb_v1_exact_images_20261019/status-current.json')
subprocess.run([sys.executable, str(ROOT / 'audit_muse_bf16_exact_images.py')], check=True)
bf16_identity = read(ROOT / 'evidence/muse_bf16_exact_image_identity.json')
assert not bf16_identity['errors'] and bf16_identity['live_node_check']['checked'] == 89
opus48 = read(O48 / 'completed_full_evaluation_result.json')
nvfp4_recovery = read(B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/completion-2866-plan.json')
local2866_audit = read(ROOT / 'evidence/muse_nvfp4_local2866_route_audit.json')
assert local2866_audit['route_count'] >= 1 and local2866_audit['claimed_task_count'] >= 1
r2_ungraded_evidence = read(ROOT / 'evidence/muse_nvfp4_r2_password_recovery_ungraded.json')
assert r2_ungraded_evidence['native_verifier_reward'] is None
r2_replacement_claim_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/r2-password-recovery-infra-replacement-claim.json'
r2_replacement_claim = read(r2_replacement_claim_path)
assert hashlib.sha256(Path(r2_replacement_claim['original_result_path']).read_bytes()).hexdigest() == r2_replacement_claim['original_result_sha256']
assert hashlib.sha256(Path(r2_replacement_claim['replacement_job_config']).read_bytes()).hexdigest() == r2_replacement_claim['replacement_job_config_sha256']
(ROOT / 'evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json').write_bytes(r2_replacement_claim_path.read_bytes())
password_replacement_integrity = read(ROOT / 'evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json')
assert password_replacement_integrity['training_disposition'] == 'exclude_from_clean_training'
assert password_replacement_integrity['native_reward'] == 1
prove_ungraded_evidence = read(ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json')
assert prove_ungraded_evidence['native_verifier_reward'] is None
assert prove_ungraded_evidence['model_raw_response_count'] == 0
prove_replacement_claim_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/r2-prove-plus-comm-infra-replacement-claim.json'
prove_replacement_claim = read(prove_replacement_claim_path)
assert hashlib.sha256(Path(prove_replacement_claim['original_result_path']).read_bytes()).hexdigest() == prove_replacement_claim['original_result_sha256']
assert hashlib.sha256(Path(prove_replacement_claim['replacement_job_config']).read_bytes()).hexdigest() == prove_replacement_claim['replacement_job_config_sha256']
assert hashlib.sha256(Path(prove_replacement_claim['original_ungraded_evidence']).read_bytes()).hexdigest() == prove_replacement_claim['original_ungraded_evidence_sha256']
(ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json').write_bytes(prove_replacement_claim_path.read_bytes())
prove_transport_failure = read(ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json')
assert prove_transport_failure['native_verifier_reward'] is None
assert prove_transport_failure['model_raw_response_count'] == 0
assert hashlib.sha256(Path(prove_transport_failure['result_path']).read_bytes()).hexdigest() == prove_transport_failure['result_sha256']
prove_transport_claim_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/r2-prove-plus-comm-transport-correction-claim.json'
prove_transport_claim = read(prove_transport_claim_path)
assert hashlib.sha256(Path(prove_transport_claim['failed_transport_evidence']).read_bytes()).hexdigest() == prove_transport_claim['failed_transport_evidence_sha256']
assert hashlib.sha256(Path(prove_transport_claim['replacement_job_config']).read_bytes()).hexdigest() == prove_transport_claim['replacement_job_config_sha256']
(ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json').write_bytes(prove_transport_claim_path.read_bytes())
pytorch_ungraded_evidence = read(ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json')
assert pytorch_ungraded_evidence['native_verifier_reward'] is None
pytorch_replacement_claim_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/r2-pytorch-model-cli-storage-replacement-claim.json'
pytorch_replacement_claim = read(pytorch_replacement_claim_path)
assert hashlib.sha256(Path(pytorch_replacement_claim['original_result_path']).read_bytes()).hexdigest() == pytorch_replacement_claim['original_result_sha256']
assert hashlib.sha256(Path(pytorch_replacement_claim['replacement_job_config']).read_bytes()).hexdigest() == pytorch_replacement_claim['replacement_job_config_sha256']
assert hashlib.sha256(Path(pytorch_replacement_claim['original_ungraded_evidence']).read_bytes()).hexdigest() == pytorch_replacement_claim['original_ungraded_evidence_sha256']
(ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json').write_bytes(pytorch_replacement_claim_path.read_bytes())
pytorch_replacement_integrity = read(ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json')
assert pytorch_replacement_integrity['claim_sha256'] == hashlib.sha256(pytorch_replacement_claim_path.read_bytes()).hexdigest()
assert pytorch_replacement_integrity['replacement_native_reward'] == 1
nvfp4_recovery_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-completion-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
nvfp4_parallel_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-parallel-2866-20261019.service'], capture_output=True, text=True).stdout.strip()
extra_lane_units = {str(lane): subprocess.run(['systemctl', '--user', 'is-active', f'muse-nvfp4-exact-tb-extra-lane{lane}-2866-20261019.service'], capture_output=True, text=True).stdout.strip() for lane in (2, 3)}
extra_gpu_watcher_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-extra-gpu-watcher-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2867_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-serve-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2919_controller = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-tb-handoff-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2867_r23_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-exact-r23-replica-2867-20261019.service'], capture_output=True, text=True).stdout.strip()
replica_2867_slot1_unit = subprocess.run(['systemctl', '--user', 'is-active', 'muse-nvfp4-r23-2867-slot1-20261020.service'], capture_output=True, text=True).stdout.strip()
replica_state = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867'
replica_handoff = read(replica_state / 'r1-b06-b07-handoff.json') if (replica_state / 'r1-b06-b07-handoff.json').exists() else None
replica_ready = (replica_state / 'endpoint-ready.json').exists()
replica_r23_status_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes/2867-controller-status.json'
replica_r23_status = read(replica_r23_status_path) if replica_r23_status_path.exists() else None
replica_2867_slot1_status_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes/2867-slot1-controller-status.json'
replica_2867_slot1_status = read(replica_2867_slot1_status_path) if replica_2867_slot1_status_path.exists() else None
extra_gpu_jobs = (2923, 2924, 2927, 2928)
queued_gpu_result = subprocess.run(['squeue', '-h', '-j', ','.join(map(str, extra_gpu_jobs)), '-o', '%i|%T|%N|%S'], capture_output=True, text=True, check=True)
extra_gpu_allocations = {}
for line in queued_gpu_result.stdout.splitlines():
    job, state, nodes, start = line.split('|', 3)
    extra_gpu_allocations[job] = {'state': state, 'nodes': nodes, 'scheduler_start': start}
extra_gpu_status = ', '.join(f'{job} {extra_gpu_allocations.get(str(job), {}).get("state", "not_in_queue")}' for job in extra_gpu_jobs)
early_b05_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu/r1-b05-early-owner.json'
early_b05_owner = read(early_b05_path) if early_b05_path.exists() else None
early_b05_exit_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu/r1-b05-early-exit.json'
early_b05_exit = read(early_b05_exit_path) if early_b05_exit_path.exists() else None
replica_2812_r23_status_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes/2812-controller-status.json'
replica_2812_r23_status = read(replica_2812_r23_status_path) if replica_2812_r23_status_path.exists() else None
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
round2_first_draw = {
    'terminal': len(new_terminal_by_round['2']),
    'graded': sum(row['reward'] in (0, 1) for row in new_terminal_by_round['2'].values()),
    'success': sum(row['reward'] == 1 for row in new_terminal_by_round['2'].values()),
    'qualification': 'Original first draws only; ungraded native exceptions remain ungraded. Separately declared replacements are excluded.',
}
r2_replacement_result = None
replacement_job = B / 'tb_v1_exact_images_20261019/results/muse_nvfp4' / r2_replacement_claim['replacement_job_name']
assert len([path for path in replacement_job.glob('password-recovery__*') if path.is_dir()]) <= 1, \
    'Multiple infrastructure replacement trial directories'
replacement_trials = [path for path in replacement_job.glob('*/result.json') if read(path).get('task_name')]
assert len(replacement_trials) <= 1, 'Multiple infrastructure replacement draws'
if replacement_trials:
    path = replacement_trials[0]
    value = read(path)
    assert Path(value['task_name']).name == 'password-recovery'
    assert Path(value['config']['task']['path']).name == 'password-recovery'
    assert value['config']['agent']['kwargs']['api_base'] == r2_replacement_claim['model_endpoint']
    if value.get('finished_at'):
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        r2_replacement_result = {'result_path': str(path), 'reward': reward,
                                 'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if reward in (0, 1):
            original = new_terminal_by_round['2']['password-recovery']
            assert original['reward'] is None
            assert original['source'] == str(Path('/fsx/home/zhiyuan') / r2_ungraded_evidence['result_path'])
            original['reward'] = reward
            original['replacement'] = r2_replacement_result
assert r2_replacement_result is not None
assert r2_replacement_result['result_sha256'] == password_replacement_integrity['result_sha256']
r2_replacement_reward_en = ('running/pending' if r2_replacement_result is None else
                            'ungraded after native exception' if r2_replacement_result['reward'] not in (0, 1)
                            else str(r2_replacement_result['reward']))
r2_replacement_reward_zh = ('运行中/待判分' if r2_replacement_result is None else
                            '原生异常后仍未判分' if r2_replacement_result['reward'] not in (0, 1)
                            else str(r2_replacement_result['reward']))
prove_replacement_result = None
prove_job = B / 'tb_v1_exact_images_20261019/results/muse_nvfp4' / prove_replacement_claim['replacement_job_name']
assert len([path for path in prove_job.glob('prove-plus-comm__*') if path.is_dir()]) <= 1, \
    'Multiple prove-plus-comm infrastructure replacement trial directories'
prove_trials = [path for path in prove_job.glob('*/result.json') if read(path).get('task_name')]
assert len(prove_trials) <= 1, 'Multiple prove-plus-comm replacement draws'
if prove_trials:
    path = prove_trials[0]
    value = read(path)
    assert Path(value['task_name']).name == 'prove-plus-comm'
    assert Path(value['config']['task']['path']).name == 'prove-plus-comm'
    assert value['config']['agent']['kwargs']['api_base'] == prove_replacement_claim['model_endpoint']
    if value.get('finished_at'):
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        prove_replacement_result = {'result_path': str(path), 'reward': reward,
                                    'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if reward in (0, 1):
            original = new_terminal_by_round['2']['prove-plus-comm']
            assert original['reward'] is None
            assert original['source'] == prove_ungraded_evidence['result_path']
            original['reward'] = reward
            original['replacement'] = prove_replacement_result
prove_replacement_reward_en = ('running/pending' if prove_replacement_result is None else
                               'ungraded after native exception' if prove_replacement_result['reward'] not in (0, 1)
                               else str(prove_replacement_result['reward']))
prove_replacement_reward_zh = ('运行中/待判分' if prove_replacement_result is None else
                               '原生异常后仍未判分' if prove_replacement_result['reward'] not in (0, 1)
                               else str(prove_replacement_result['reward']))
assert prove_replacement_result is not None and prove_replacement_result['reward'] is None
assert prove_replacement_result['result_sha256'] == prove_transport_failure['result_sha256']
prove_transport_result = None
transport_job = B / 'tb_v1_exact_images_20261019/results/muse_nvfp4' / prove_transport_claim['replacement_job_name']
assert len([path for path in transport_job.glob('prove-plus-comm__*') if path.is_dir()]) <= 1, \
    'Multiple prove-plus-comm transport correction trial directories'
transport_trials = [path for path in transport_job.glob('*/result.json') if read(path).get('task_name')]
assert len(transport_trials) <= 1, 'Multiple prove-plus-comm transport correction draws'
if transport_trials:
    path = transport_trials[0]
    value = read(path)
    assert Path(value['task_name']).name == 'prove-plus-comm'
    assert Path(value['config']['task']['path']).name == 'prove-plus-comm'
    assert value['config']['agent']['kwargs']['api_base'] == prove_transport_claim['model_endpoint']
    if value.get('finished_at'):
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        prove_transport_result = {'result_path': str(path), 'reward': reward,
                                  'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if reward in (0, 1):
            original = new_terminal_by_round['2']['prove-plus-comm']
            assert original['reward'] is None
            assert original['source'] == prove_ungraded_evidence['result_path']
            original['reward'] = reward
            original['replacement'] = prove_transport_result
prove_transport_reward_en = ('running/pending' if prove_transport_result is None else
                             'ungraded after native exception' if prove_transport_result['reward'] not in (0, 1)
                             else str(prove_transport_result['reward']))
prove_transport_reward_zh = ('运行中/待判分' if prove_transport_result is None else
                             '原生异常后仍未判分' if prove_transport_result['reward'] not in (0, 1)
                             else str(prove_transport_result['reward']))
pytorch_replacement_result = None
pytorch_job = B / 'tb_v1_exact_images_20261019/results/muse_nvfp4' / pytorch_replacement_claim['replacement_job_name']
assert len([path for path in pytorch_job.glob('pytorch-model-cli__*') if path.is_dir()]) <= 1, \
    'Multiple pytorch-model-cli storage replacement trial directories'
pytorch_trials = [path for path in pytorch_job.glob('*/result.json') if read(path).get('task_name')]
assert len(pytorch_trials) <= 1, 'Multiple pytorch-model-cli storage replacement draws'
if pytorch_trials:
    path = pytorch_trials[0]
    value = read(path)
    assert Path(value['task_name']).name == 'pytorch-model-cli'
    assert Path(value['config']['task']['path']).name == 'pytorch-model-cli'
    assert value['config']['agent']['kwargs']['api_base'] == pytorch_replacement_claim['model_endpoint']
    if value.get('finished_at'):
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        pytorch_replacement_result = {'result_path': str(path), 'reward': reward,
                                      'result_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        if reward in (0, 1):
            original = new_terminal_by_round['2']['pytorch-model-cli']
            assert original['reward'] is None
            assert original['source'] == pytorch_ungraded_evidence['result_path']
            assert pytorch_replacement_integrity['result_sha256'] == pytorch_replacement_result['result_sha256']
            original['reward'] = reward
            original['replacement'] = pytorch_replacement_result
pytorch_replacement_reward_en = ('running/pending' if pytorch_replacement_result is None else
                                 'ungraded after native exception' if pytorch_replacement_result['reward'] not in (0, 1)
                                 else str(pytorch_replacement_result['reward']))
pytorch_replacement_reward_zh = ('运行中/待判分' if pytorch_replacement_result is None else
                                 '原生异常后仍未判分' if pytorch_replacement_result['reward'] not in (0, 1)
                                 else str(pytorch_replacement_result['reward']))
for rnd, rows in new_terminal_by_round.items():
    nvfp4_rounds[rnd]['terminal'] += len(rows)
    nvfp4_rounds[rnd]['graded'] += sum(row['reward'] in (0, 1) for row in rows.values())
    nvfp4_rounds[rnd]['success'] += sum(row['reward'] == 1 for row in rows.values())
    nvfp4_rounds[rnd]['ungraded'] = nvfp4_rounds[rnd]['terminal'] - nvfp4_rounds[rnd]['graded']
    assert nvfp4_rounds[rnd]['ungraded'] >= 0
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
bf16_swr_alignment_path = ROOT / 'evidence/muse_bf16_swr_alignment.json'
bf16_swr_alignment = read(bf16_swr_alignment_path) if bf16_swr_alignment_path.exists() else {}
bf16_swr_final = bf16_swr_alignment.get('final_score') or {}
bf16_swr_complete = bf16_swr_final.get('qualification') == 'complete_verified'
bf16_review_progress_path = ROOT / 'evidence/muse_bf16_swe_review_progress.json'
bf16_review_progress = read(bf16_review_progress_path) if bf16_review_progress_path.exists() else {}
assert not bf16_review_progress.get('errors', [])
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
            'swe_review': {key: metric(value, key, 'final_da_rrr_pending' if key in review_da['reviewers'].get('muse-nvfp4', {}) else 'supplementary_complete_da_rrr_pending') |
                           {'DA': native_review_da['splits'][key]['metrics'], 'RRR': None,
                            'evidence': ('evidence/swe_review_complete_split_da.json' if key in review_da['reviewers'].get('muse-nvfp4', {})
                                         else 'evidence/swe_review_native_complete_da.json'),
                            'native_verifier_complete_without_harbor_summary': len(native_review_da['splits'][key]['native_verifier_complete_without_harbor_summary'])}
                           for key, value in mr['swe_review'].items() if isinstance(value, dict) and 'expected' in value},
            'swe_review_execution': {
                'old_controller': review_recovery['old_controller'],
                'never_claimed_continuation': review_recovery['disjoint_never_claimed_continuation'],
                'no_trial_continuation': review_recovery['disjoint_no_trial_continuation'],
                'interrupted_partial_sampled_count': review_recovery['interrupted_tasks_with_partial_sampled_trajectory_preserved'],
                'original_native_verifier_complete_without_harbor_summary_count': len(review_recovery['original_native_verifier_complete_without_harbor_summary']),
                'unfinished_report_replacement': review_recovery['unfinished_report_replacement'],
                'evidence': 'evidence/swe_review_recovery_control.json',
            },
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
            'swe_review': {key: metric(value, key, 'final_da_rrr_pending' if key in review_da['reviewers'].get('beam-bf16', {}) else 'partial_no_full_rrr') |
                           ({'DA': review_da['reviewers']['beam-bf16'][key]['metrics'], 'RRR': None,
                             'evidence': 'evidence/swe_review_complete_split_da.json',
                             'invalid_report_count': review_da['reviewers']['beam-bf16'][key]['invalid_report_count']}
                            if key in review_da['reviewers'].get('beam-bf16', {}) else {})
                           for key, value in br['swe_review'].items() if isinstance(value, dict) and 'expected' in value},
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
            'swe_review': opus_review_progress['splits'],
        },
        'opus_4_8_historical': {
            'model': 'Claude Opus 4.8',
            'swe_bench_pro_verified': {'status': 'complete_historical_run', 'expected': 731, 'graded': 731, 'success': opus48['all731']['correct'], 'accuracy': opus48['all731']['correct'] / 731, 'confirmed_solution_retrieval_cases': opus48['confirmed_solution_retrieval_count'], 'conservative_noncredit_for_confirmed_retrieval': opus48['conservative_noncredit_confirmed_retrieval'], 'qualification': 'Three confirmed solution retrieval cases; raw benchmark score is unchanged and not a claim all other trajectories are clean.'},
        },
        'muse_bf16': {
            'model': 'meta-models/Muse-Spark-Open-816B-A42B',
            'revision': '0fb02478b02565b2ce7fc57e6051c91172774ac9',
            'status': 'in_progress',
            'swe_bench_pro_verified': metric(ex['muse_bf16']['pro'], 'pro', 'partial_no_full_score') | {
                key: ex['muse_bf16']['pro'][key] for key in
                ('scoring_run_id', 'source_run_id', 'reused_original_completed_tasks',
                 'original_unreused_failed_tasks', 'recovery_qualification')
            } | {'recovery_evidence': 'evidence/muse_bf16_2865_expiry_recovery.json'},
            'tb2_1_legacy_cached_tag': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['tb'].items()} | {'qualification': 'Historical field name for this same BF16 run; do not add these trials to the exact-image field as independent attempts.'},
            'tb2_1_exact_supplied_images': {'rounds': {'1': bf16_tb_round1}, 'status': 'round_1_complete' if bf16_complete else 'partial_no_full_score',
                'same_trials_as_legacy_named_bf16_tb': True,
                'image_identity_audit': 'evidence/muse_bf16_exact_image_identity.json',
                'released_io_audit': 'evidence/muse_bf16_exact_io_coverage.json',
                'qualification': 'The 89 supplied archive image identities, task paths and agent settings were verified before BF16 round 1 launched and rechecked on the running node. A full-round accuracy awaits all 89 native results and task-level audit.'},
            'deepswe': {k: metric(v, k, 'partial_no_full_score') for k, v in ex['muse_bf16']['deep'].items()},
            'swrbench': {
                'status': 'complete' if bf16_swr_complete else 'partial_no_full_score',
                'expected': 1000,
                'generated': bf16_swr_alignment.get('generated', 0),
                'judged': bf16_swr_alignment.get('judged', 0),
                'accuracy': bf16_swr_final.get('accuracy') if bf16_swr_complete else None,
                'f1': bf16_swr_final.get('f1') if bf16_swr_complete else None,
                'point_f1': bf16_swr_final.get('point_f1') if bf16_swr_complete else None,
                'judge': 'gpt-5.5',
                'evidence': 'evidence/muse_bf16_swr_alignment.json',
            },
            'swe_review': {
                'status': 'partial_no_final_da_or_rrr',
                'native_terminal': bf16_review_progress.get('total_native_terminal', 0),
                'native_graded': bf16_review_progress.get('total_native_graded', 0),
                'expected': bf16_review_progress.get('total_expected', 1384),
                'splits': {name: {key: value[key] for key in ('expected', 'native_terminal', 'native_graded')}
                           for name, value in bf16_review_progress.get('splits', {}).items()},
                'DA': None, 'RRR': None,
                'evidence': 'evidence/muse_bf16_swe_review_progress.json',
            },
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
    'round23_extra_slot_controller': replica_2867_slot1_unit,
    'round23_extra_slot_status': replica_2867_slot1_status,
})
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['local_2866_backfill'] = {
    'evidence': 'evidence/muse_nvfp4_local2866_route_audit.json',
    'ready_proof': 'evidence/muse_nvfp4_local2866_ready.json',
    'route_count': local2866_audit['route_count'],
    'claimed_task_count': local2866_audit['claimed_task_count'],
    'terminal': sum(row['terminal'] for row in local2866_audit['routes']),
}
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['round_2_password_recovery_replacement'] = {
    'claim': 'evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json',
    'original_native_reward': None,
    'replacement_result': r2_replacement_result,
    'training_disposition': password_replacement_integrity['training_disposition'],
    'integrity_evidence': 'evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json',
    'counted_as_one_task': True,
    'no_best_of_selection': True,
}
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['round_2_prove_plus_comm_replacement'] = {
    'claim': 'evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json',
    'original_native_reward': None,
    'original_model_response_count': 0,
    'replacement_result': prove_replacement_result,
    'transport_correction_claim': 'evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json',
    'transport_correction_result': prove_transport_result,
    'counted_as_one_task': True,
    'no_best_of_selection': True,
}
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['round_2_original_first_draw'] = round2_first_draw
snapshot['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']['round_2_pytorch_model_cli_storage_replacement'] = {
    'claim': 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json',
    'original_native_reward': None,
    'original_ungraded_evidence': 'evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json',
    'replacement_result': pytorch_replacement_result,
    'replacement_integrity': 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json',
    'counted_as_one_task_in_repaired_round': True,
    'no_best_of_selection': True,
}
for reviewer, model_key in (('muse-nvfp4', 'muse_nvfp4'), ('beam-bf16', 'beam_bf16'),
                            ('muse-bf16', 'muse_bf16')):
    for split, value in snapshot['models'][model_key].get('swe_review', {}).items():
        if not isinstance(value, dict):
            continue
        official = review_rrr['complete_splits'].get(f'{reviewer}/{split}')
        if official:
            assert value['DA'] == official['DA']
            value.update(status='final_split_da_rrr_complete', RRR=official['RRR'],
                         rrr_evidence=official['native_evidence'],
                         rrr_summary=official['summary'])
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
if bf16_swr_alignment_path.exists():
    files[str(bf16_swr_alignment_path.relative_to(ROOT))] = {
        'sha256': hashlib.sha256(bf16_swr_alignment_path.read_bytes()).hexdigest(),
        'size_bytes': bf16_swr_alignment_path.stat().st_size,
        'source': str(bf16_swr_alignment_path)}
if bf16_review_progress_path.exists():
    files[str(bf16_review_progress_path.relative_to(ROOT))] = {
        'sha256': hashlib.sha256(bf16_review_progress_path.read_bytes()).hexdigest(),
        'size_bytes': bf16_review_progress_path.stat().st_size,
        'source': str(bf16_review_progress_path)}
shared_timeout_path = ROOT / 'evidence/shared_element_hq_eval_timeout.json'
assert shared_timeout_path.is_file()
files[str(shared_timeout_path.relative_to(ROOT))] = {
    'sha256': hashlib.sha256(shared_timeout_path.read_bytes()).hexdigest(),
    'size_bytes': shared_timeout_path.stat().st_size,
    'source': str(shared_timeout_path),
}
for evidence_name in ('swe_review_revision_queue_recovery_20261020.json',
                      'swe_review_revision_gateway_progress.json',
                      'beam_coder_pre_model_port_mismatch.json',
                      'muse_nvfp4_r2_password_recovery_ungraded.json',
                      'muse_nvfp4_r2_password_recovery_replacement_claim.json',
                      'muse_nvfp4_r2_password_replacement_integrity_alert.json',
                      'muse_nvfp4_r2_prove_plus_comm_ungraded.json',
                      'muse_nvfp4_r2_prove_plus_comm_replacement_claim.json',
                      'muse_nvfp4_r2_prove_plus_comm_transport_failure.json',
                      'muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json',
                      'muse_nvfp4_local2866_ready.json',
                      'muse_nvfp4_local2866_route_audit.json',
                      'muse_nvfp4_r2_pytorch_model_cli_ungraded.json',
                      'muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json',
                      'muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json',
                      'swe_review_official_rrr.json'):
    path = ROOT / 'evidence' / evidence_name
    assert path.is_file()
    files[str(path.relative_to(ROOT))] = {
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'size_bytes': path.stat().st_size,
        'source': str(path),
    }
for row in review_rrr['complete_splits'].values():
    for name in ('summary', 'native_evidence'):
        path = ROOT / row[name]
        files[str(path.relative_to(ROOT))] = {
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'size_bytes': path.stat().st_size,
            'source': str(path),
        }
write('input_output/manifest.json', {'generated_utc': now, 'files': files})

def partial(d):
    return f"{d['graded']}/{d['expected']} graded; {d['success']} success (partial)" if d.get('graded') else f"0/{d['expected']} graded"

def review(d):
    return ', '.join((f"{v['terminal']}/{v['expected']} task outcomes; {v['DA']['produced']} parseable decisions; "
                      f"{'final split DA' if v['status'] in ('final_da_rrr_pending', 'final_split_da_rrr_complete') else 'audited supplementary DA'} {v['DA']['DA']}% "
                      f"(DA_total_50 {v['DA']['DA_total_50']}%)"
                      + (f"; final split RRR {v['RRR']['RRR']}%" if v.get('RRR') else '') if v.get('DA')
                      else f"{v['terminal']}/{v['expected']} terminal")
                     for v in d.values()) + '; overall official RRR incomplete'

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
opus_review_en = ', '.join(
    f"{split}: {row.get('completed_trials', 0)}/{row['expected']} task outcomes"
    for split, row in op['swe_review'].items()
) + '; DA/RRR pending'
opus_review_zh = '、'.join(
    f"{split} {row.get('completed_trials', 0)}/{row['expected']} 题终态"
    for split, row in op['swe_review'].items()
) + '；DA/RRR 待官方判分'
review_instruct_da = mn['swe_review']['qwen3_30b_instruct2507_500']['DA']
review_glm_da = mn['swe_review']['glm5_500']['DA']
review_coder_da = mn['swe_review']['qwen3_coder_30b_500']['DA']
muse_review_instruct_rrr = mn['swe_review']['qwen3_30b_instruct2507_500'].get('RRR')
muse_review_coder_rrr = mn['swe_review']['qwen3_coder_30b_500'].get('RRR')
muse_coder_rrr_en_note = (
    f"The Coder split also has {muse_review_coder_rrr['revised']} verified native revisions: "
    f"**RRR {muse_review_coder_rrr['RRR']}%** (baseline RR "
    f"{muse_review_coder_rrr['baseline_RR']}%, delta +{muse_review_coder_rrr['delta']} points). "
    if muse_review_coder_rrr else '')
muse_coder_rrr_zh_note = (
    f"Coder 组也已核验 {muse_review_coder_rrr['revised']} 条原生修订："
    f"**RRR {muse_review_coder_rrr['RRR']}%**，baseline RR "
    f"{muse_review_coder_rrr['baseline_RR']}%，提升 {muse_review_coder_rrr['delta']} 个百分点。"
    if muse_review_coder_rrr else '')
muse_rrr_en_note = (
    f"The [released native RRR evidence](evidence/swe_review_official_rrr.json) verifies all "
    f"{muse_review_instruct_rrr['revised']} original-generator revisions for the Instruct split: "
    f"**RRR {muse_review_instruct_rrr['RRR']}%** (baseline RR "
    f"{muse_review_instruct_rrr['baseline_RR']}%, delta +{muse_review_instruct_rrr['delta']} points). "
    f"{muse_coder_rrr_en_note}The GLM5 split and overall RRR remain unfinished."
    if muse_review_instruct_rrr else 'Original-generator revisions are still being graded; RRR remains pending.')
muse_rrr_zh_table = (f"；SWE-Review Instruct 组官方 RRR **{muse_review_instruct_rrr['RRR']}%**"
                     if muse_review_instruct_rrr else '')
muse_rrr_zh_table += (f"；Coder 组官方 RRR **{muse_review_coder_rrr['RRR']}%**"
                      if muse_review_coder_rrr else '')
muse_rrr_zh_note = (
    f"[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了 Instruct 组全部 "
    f"{muse_review_instruct_rrr['revised']} 条原始生成模型修订："
    f"**RRR {muse_review_instruct_rrr['RRR']}%**，原始 baseline RR "
    f"{muse_review_instruct_rrr['baseline_RR']}%，提升 "
    f"{muse_review_instruct_rrr['delta']} 个百分点。{muse_coder_rrr_zh_note}GLM5 组及整体 RRR 尚未完成。"
    if muse_review_instruct_rrr else '原始生成模型修订仍在判分；RRR 尚未生成。')
beam_review_instruct_da = be['swe_review']['qwen3_30b_instruct2507_500'].get('DA')
beam_review_instruct_rrr = be['swe_review']['qwen3_30b_instruct2507_500'].get('RRR')
beam_rrr_en_note = (
    f"The [released native RRR evidence](evidence/swe_review_official_rrr.json) verifies all "
    f"{beam_review_instruct_rrr['revised']} original-generator revisions and the unchanged official "
    f"split metric: **RRR {beam_review_instruct_rrr['RRR']}%** (baseline RR "
    f"{beam_review_instruct_rrr['baseline_RR']}%, delta +{beam_review_instruct_rrr['delta']} points). "
    f"The GLM5 and Coder splits and overall RRR remain unfinished."
    if beam_review_instruct_rrr else 'The GLM5 and Coder splits and all RRR revision grades remain incomplete.')
beam_rrr_zh_table = (f"；SWE-Review Instruct 组官方 RRR **{beam_review_instruct_rrr['RRR']}%**"
                     if beam_review_instruct_rrr else '')
beam_rrr_zh_note = (
    f"[已归档的原生 RRR 证据](evidence/swe_review_official_rrr.json)核对了全部 "
    f"{beam_review_instruct_rrr['revised']} 条原始生成模型修订和未改动的官方分组指标："
    f"**RRR {beam_review_instruct_rrr['RRR']}%**，原始 baseline RR "
    f"{beam_review_instruct_rrr['baseline_RR']}%，提升 "
    f"{beam_review_instruct_rrr['delta']} 个百分点。GLM5/Coder 两组及整体 RRR 尚未完成。"
    if beam_review_instruct_rrr else 'GLM5/Coder 两组和全部 RRR 修复判分仍未完成。')
mn_tb = mn['tb2_1_exact_supplied_images']['rounds']['1']
mn_audit = read(ROOT / 'evidence/muse_nvfp4_exact_round1_audit.json')
manual_notes = read(ROOT / 'evidence/exact_tb_integrity_manual_notes.json')['notes']
opus_thinking_path = ROOT / 'evidence/opus47_r3_thinking_transport_audit.json'
opus_thinking_audit = read(opus_thinking_path) if opus_thinking_path.exists() else None
nvfp4_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_nvfp4'
                        and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
bf16_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_bf16'
                       and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
nvfp4_r2_excluded = sorted(n['task'] for n in manual_notes if n['model'] == 'muse_nvfp4_r2'
                           and n['reward'] == 1 and n['training_disposition'].startswith('exclude_'))
nvfp4_excluded_names = ', '.join(f'`{name}`' for name in nvfp4_excluded)
bf16_excluded_names = ', '.join(f'`{name}`' for name in bf16_excluded)
nvfp4_r2_excluded_names = ', '.join(f'`{name}`' for name in nvfp4_r2_excluded)
beam_tb_rounds = be['tb2_1_exact_supplied_images']['rounds']
be_tb = beam_tb_rounds['1']
op_tb = op['tb2_1_exact_supplied_images']['rounds']['1']


def tb_en(row):
    return f"**{row['success']}/89 = {row['accuracy']:.2%}**, round 1 complete" if row['complete'] else f"{row['graded']}/89 graded; {row['success']} success, round 1 partial"


def tb_zh(row):
    return f"**{row['success']}/89（{row['accuracy']:.2%}）**，首轮完整" if row['complete'] else f"**{row['graded']}/89 已判分、{row['success']} 成功**，首轮未完成"


muse_exact_zh_done = f'；精确镜像 TB2.1 首轮 {tb_zh(mn_tb)}' if mn_tb['complete'] else ''
muse_exact_zh_pending = '' if mn_tb['complete'] else f'精确镜像 TB2.1 首轮 {tb_zh(mn_tb)}；'
beam_exact_zh_done = f'；精确镜像 TB2.1 首轮 {tb_zh(be_tb)}' if be_tb['complete'] else ''
beam_exact_zh_pending = '' if be_tb['complete'] else f'；精确镜像 TB2.1 首轮 {tb_zh(be_tb)}'
beam_exact_en = '; '.join(
    f"r{number} {row['success']}/89 complete" if row['complete']
    else f"r{number} {row['success']}/{row['graded']} graded (partial)"
    for number, row in beam_tb_rounds.items() if row['graded'] or row['complete']
)
beam_exact_zh_done += ''.join(
    f"；精确镜像 TB2.1 第{number}轮 **{row['success']}/89**"
    for number, row in beam_tb_rounds.items() if number != '1' and row['complete']
)
beam_exact_zh_pending += ''.join(
    f"；精确镜像 TB2.1 第{number}轮 {row['graded']}/89 已判分、{row['success']} 成功，未完成"
    for number, row in beam_tb_rounds.items() if number != '1' and not row['complete'] and row['graded']
)
opus_tb_rounds = op['tb2_1_exact_supplied_images']['rounds']
opus_exact_en = '; '.join(
    f"r{number} {row['success']}/89 complete" if row['complete']
    else f"r{number} {row['success']}/{row['graded']} graded (partial)"
    for number, row in opus_tb_rounds.items()
)
opus_exact_zh_done = ''.join(
    f"；精确镜像 TB2.1 第{number}轮 **{row['success']}/89**"
    for number, row in opus_tb_rounds.items() if row['complete']
)
opus_exact_zh_pending = ''.join(
    f"；精确镜像 TB2.1 第{number}轮 {row['graded']}/89 已判分、{row['success']} 成功，未完成"
    for number, row in opus_tb_rounds.items() if not row['complete'] and row['graded']
)
opus_deep_rounds = op['deepswe']
opus_deep_en = '; '.join(
    f"r{number} {row['success']}/113 complete" if row['status'] == 'complete'
    else f"r{number} {row['success']}/{row['graded']} graded (partial)"
    for number, row in opus_deep_rounds.items()
)
opus_deep_zh_done = ''.join(
    f"；DeepSWE 第{number}轮 **{row['success']}/113**"
    for number, row in opus_deep_rounds.items() if row['status'] == 'complete'
)
opus_deep_zh_pending = ''.join(
    f"；DeepSWE 第{number}轮 {row['graded']}/113 已判分、{row['success']} 成功，未完成"
    for number, row in opus_deep_rounds.items() if row['status'] != 'complete' and row['graded']
)
bf16_exact_zh_done = f'；指定精确镜像 TB2.1 首轮 {tb_zh(bf16_tb_round1)}' if bf16_tb_round1['complete'] else ''
bf16_exact_zh_pending = '' if bf16_tb_round1['complete'] else f'；指定精确镜像 TB2.1 首轮 {tb_zh(bf16_tb_round1)}'
bf16_review_state_path = BF / 'review_bench/state/current.json'
bf16_review_state = read(bf16_review_state_path) if bf16_review_state_path.exists() else {}
bf16_review_phase = bf16_review_state.get('phase')
bf16_swr_generated = completed_jsonl_ids(BF / 'review_bench/swrbench/generation.jsonl')
bf16_swr_judged = completed_jsonl_ids(BF / 'review_bench/swrbench/evaluation-gpt-5.5.json.tmp.jsonl')
assert bf16_swr_judged <= bf16_swr_generated
assert len(bf16_swr_generated) <= 1000
bf16_review_ready_images = sum(
    read(path).get('phase') == 'image_ready'
    for path in (BF / 'review_bench/queue/images').glob('*.json'))
if bf16_review_phase == 'queued_for_verified_2886_bf16_endpoint':
    bf16_review_en = 'Queued on verified BF16 pair 2886'
    bf16_review_zh = '；SWE-Review 已排到 2886 双节点'
elif bf16_review_phase == 'verified_2886_swr_generation_judging_and_review_pipeline_started':
    bf16_review_en = f'{bf16_review_ready_images} SWE-Review task images prepared; revision score pending'
    bf16_review_zh = f'；SWE-Review 已预建 {bf16_review_ready_images} 个任务镜像，最终分数待完成'
else:
    bf16_review_en = 'Incomplete; current launch state needs review'
    bf16_review_zh = '；SWE-Review 尚未完成，启动状态待核查'
if bf16_review_progress:
    splits = bf16_review_progress['splits']
    glm_progress = splits['glm5_500']['native_terminal']
    coder_progress = splits['qwen3_coder_30b_500']['native_terminal']
    instruct_progress = splits['qwen3_30b_instruct2507_500']['native_terminal']
    review_total = bf16_review_progress['total_native_terminal']
    review_expected = bf16_review_progress['total_expected']
    bf16_review_en = (f'{review_total}/{review_expected} native outcomes '
                      f'(GLM {glm_progress}/500, Coder {coder_progress}/462, '
                      f'Instruct {instruct_progress}/422); official DA/RRR pending')
    bf16_review_zh = (f'；SWE-Review 原生任务终态 {review_total}/{review_expected}'
                      f'（GLM {glm_progress}/500、Coder {coder_progress}/462、'
                      f'Instruct {instruct_progress}/422），官方 DA/RRR 待完成；'
                      f'已预建 {bf16_review_ready_images} 个任务镜像')
bf16_swr_en = (f"**{bf16_swr_final['accuracy']:.1%}** ({bf16_swr_final['judged']}/1000 judged), "
                f"PR F1 **{bf16_swr_final['f1']:.4f}**") if bf16_swr_complete else (
                f'{len(bf16_swr_generated)}/1000 generated, {len(bf16_swr_judged)}/1000 judged; score pending')
bf16_swr_zh = (f"SWRBench GPT-5.5 裁判 **{bf16_swr_final['accuracy']:.1%}（1000/1000）**，"
                f"PR 分类 F1 **{bf16_swr_final['f1']:.4f}**") if bf16_swr_complete else ''
bf16_swr_note_en = ('The final 1000-task official score is reconciled with the generation, judge, '
                    f"result and metric receipts. Accuracy and F1 are PR-level metrics; the issue-point F1 is {bf16_swr_final['point_f1']:.4f}."
                    if bf16_swr_complete else 'These are live I/O checks, not a final accuracy.')
bf16_swr_note_zh = ('1000 题官方结果已与生成、裁判、结果文件及指标收据核对；准确率统计 PR 分类，'
                    f"PR 分类 F1 为 {bf16_swr_final['f1']:.4f}，逐问题点 F1 为 {bf16_swr_final['point_f1']:.4f}。"
                    if bf16_swr_complete else '这仅是进行中输入输出核验，不是最终准确率。')
mn_exact_note_zh = f"精确镜像首轮已完成：**{mn_tb['success']}/89（{mn_tb['accuracy']:.2%}）**。" if mn_tb['complete'] else f"精确镜像首轮只判分 {mn_tb['graded']}/89，不能当成最终准确率。"
if not mn_tb['complete'] and mn_tb['graded'] == 88 and mn_audit['missing_graded_tasks'] == ['mteb-leaderboard']:
    lower = mn_tb['success'] / 89
    upper = (mn_tb['success'] + 1) / 89
    mn_exact_note_zh += (f'已判分 {mn_tb["success"]} 题成功；若最后一题按协议得到有效评分，'
                         f'完整首轮将是 {mn_tb["success"]}/89（{lower:.2%}）或 '
                         f'{mn_tb["success"] + 1}/89（{upper:.2%}），目前尚不能确定是哪一个。')
mteb_timeout_note_zh = ''
if not mn_tb['complete'] and mn_audit['missing_graded_tasks'] == ['mteb-leaderboard']:
    mteb_card = Path('/fsx/home/zhiyuan/bench/strict_four_models_20261008/sources/terminal-bench-2-1/mteb-leaderboard/task.toml')
    mteb_trial = B / 'tb_v1_exact_images_20261019/results/muse_nvfp4/muse-nvfp4-tb-v1-exact-r1-completion-2866-b03/mteb-leaderboard__EAhfXHh/config.json'
    agent_section = mteb_card.read_text().split('\n[agent]\n', 1)[1].split('\n[', 1)[0]
    card_timeout = float(re.search(r'(?m)^timeout_sec\s*=\s*([0-9.]+)\s*$', agent_section).group(1))
    timeout_multiplier = read(mteb_trial)['agent_timeout_multiplier']
    mteb_timeout_note_zh = (f'最后未判分的是 `mteb-leaderboard`：题卡 agent 超时 {card_timeout:g} 秒，'
                            f'本轮协议乘数 {timeout_multiplier:g}，agent 阶段上限 '
                            f'{card_timeout * timeout_multiplier / 3600:g} 小时；运行中的原始首抽不提前记错。')
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
if replica_2867_slot1_status:
    replica_note_en += (f" A second locked controller slot on 2867 is {replica_2867_slot1_unit}, "
                        f"running untouched batch {replica_2867_slot1_status.get('job_name', 'none')} "
                        "through the same verified NVFP4 endpoint.")
    replica_note_zh += (f" 2867 上第二条独立加锁通道状态为 {replica_2867_slot1_unit}，"
                        f"运行未抽样批次 {replica_2867_slot1_status.get('job_name', '无')}，"
                        "使用同一已核验 NVFP4 端点。")
readme = f'''# Agent benchmark evaluation snapshot

Snapshot: **{now}**. This repository is private because the native task inputs, model outputs and thinking trajectories may contain sensitive text. The score table separates finished evaluations from partial runs. Input/output artifacts are in `input_output/` and the [native archive release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot); each archive has a SHA-256 manifest.

| Model / precision | SWE-bench Pro Verified | DeepSWE | SWRBench (GPT-5.5 judge) | TB2.1 exact supplied images | SWE-Review |
|---|---|---|---|---|---|
| Muse NVFP4 | **496/731 = 67.85%**, round 1 complete | **57/113, 59/113, 63/113**; 3-round mean **52.80%** | **55.4%** (1000/1000 judged) | {tb_en(mn_tb)} | {review(mn['swe_review'])} |
| Beam BF16 | {partial(be['swe_bench_pro_verified'])} | {partial(be['deepswe']['1'])}, round 1 | **55.6%** (1000/1000 judged) | {beam_exact_en} | {review(be['swe_review'])} |
| Opus 4.7 | {partial(op['swe_bench_pro_verified'])} | {opus_deep_en} | — | {opus_exact_en} | {opus_review_en} |
| Opus 4.8 (historical) | **503/731 = 68.81%**, completed run; 3 confirmed solution retrieval cases | — | — | — | — |
| Muse original BF16 | {partial(models['muse_bf16']['swe_bench_pro_verified'])} | {partial(models['muse_bf16']['deepswe']['1'])}, round 1 | {bf16_swr_en} | {tb_en(bf16_tb_round1)}; [89 image identities verified](evidence/muse_bf16_exact_image_identity.json) | {bf16_review_en} |

Opus 4.7 SWE-Review uses the unchanged official task cards and one review attempt per task. Its [model-visible inputs](input_output/archive_manifests/opus47_review_inputs.json) and [native outputs, completions and trajectories](input_output/archive_manifests/opus47_review_full_io.json) are SHA-verified Release assets. The output archive is a partial snapshot; later deltas preserve ongoing trials. Review-stage outcomes alone do not establish DA or RRR.

Muse BF16's original GPU allocation expired during Pro, TB2.1 and DeepSWE runs. The [recovery audit](evidence/muse_bf16_2865_expiry_recovery.json) identifies the original and derived Pro run IDs: **137 completed original tasks are reused once**, while 10 failed and four active original attempts are preserved separately. Its live Pro score reads only the derived native run, so partial counts may temporarily fall as interrupted tasks are resumed. The two interrupted original TB trials and two DeepSWE trials are available as separate SHA-verified [TB](input_output/archive_manifests/muse_bf16_interrupted_tb_delta_20261020T072043Z.json) and [DeepSWE](input_output/archive_manifests/muse_bf16_interrupted_deep_delta_20261020T072043Z.json) I/O assets; they remain ungraded infrastructure interruptions.

Muse NVFP4 now has [sealed official DA receipts for all three SWE-Review splits](evidence/swe_review_complete_split_da.json): GLM5 **{review_glm_da['DA']}%** on {review_glm_da['produced']} parseable decisions (500 task outcomes), Qwen3-Coder **{review_coder_da['DA']}%** on {review_coder_da['produced']} (462 outcomes), and Qwen3-30B-Instruct **{review_instruct_da['DA']}%** on {review_instruct_da['produced']} (422 outcomes). [The v2 receipt audit](evidence/muse_swe_review_revision_v2_receipts.json) verifies 8 GLM5 and 2 Coder task-generation-only adapters for finished native verifier reports lacking Harbor summaries; no adapter is a model result. {muse_rrr_en_note}

The [revision infrastructure audit](evidence/swe_review_revision_queue_recovery_20261020.json) records two task input formats, preparation failures, and a sandbox-to-model connection timeout before any model response. Those native failures remain excluded from model scores. Two synthetic Harbor trials then completed model generation, terminal tool use, and native verification through the Docker host bridge; they do not enter benchmark metrics. Four declared original-generator recovery queues have run or are running with the [bridge agent](protocol/muse_review_revision_v2/revision_agents_bridge_v4.py) and the original task inputs. The [live native-grade audit](evidence/swe_review_revision_gateway_progress.json) has Muse Coder **{review_revision_muse_coder['native_graded_revisions']}/{review_revision_muse_coder['expected_revisions']}**, Muse Instruct **{review_revision_muse_instruct['native_graded_revisions']}/{review_revision_muse_instruct['expected_revisions']}**, Beam Coder **{review_revision_beam_coder['native_graded_revisions']}/{review_revision_beam_coder['expected_revisions']}**, and Beam Instruct **{review_revision_beam_instruct['native_graded_revisions']}/{review_revision_beam_instruct['expected_revisions']}** revisions graded; split RRR is reported only after every required native grade and released evidence is verified. The [v3 scorer](protocol/muse_review_revision_v2/revision_score_v3.py) reads only the corrected gateway results, preserves five malformed Beam review reports as model failures, and exactly reproduces all four sealed DA split metrics.

The [Beam Coder port-mismatch audit](evidence/beam_coder_pre_model_port_mismatch.json) preserves 16 first-batch infrastructure failures: the sandbox allowed port 31411 while the Qwen3-Coder model served port 31410, so none received a model response or native grade. They are excluded from model scores. The separate [corrected 224-task queue](protocol/beam_review_revision_v2/beam_coder_portfix/queue-plan.json) allows port 31410; its [independent synthetic preflight](protocol/beam_review_revision_v2/beam_coder_portfix/synthetic-portfix-r2-passed.json) completed model generation and native verification. Synthetic output is excluded from scores, and each rejected PR receives one native model attempt in the corrected queue.

The [SWE-Review controller audit](evidence/swe_review_recovery_control.json) records that the old reviewer queue was killed at 03:17 UTC. Two disjoint continuations now own the 11 tasks never claimed and the 23 claimed tasks for which no native trial directory existed, using the same Muse NVFP4 model. Of the 16 interrupted trials with partial model output, 10 had already finished their agent step and native verifier report/reward; their original reports remain preserved, and no replacement draw is scheduled for them. The other 6 lacked a final report and now have a separately declared infrastructure replacement attempt. The stale old health file is not evidence of an active controller.

Beam SWE-Review has [**{beam_malformed_count} sampled reports with invalid JSON**](evidence/beam_swe_review_malformed_reports.json). The original task-preparation controller failed while reading one. A [source-pinned v2 preparation protocol](protocol/beam_review_revision_v2/task-preparation-plan-v2.json) preserves the raw files and applies the official generator's missing-decision fallback; its current phase is `{beam_prep_phase}`. The remaining review splits are still running.

Beam BF16's Qwen3-30B-Instruct SWE-Review split has a [sealed official DA](evidence/swe_review_complete_split_da.json) of **{beam_review_instruct_da['DA']}%** on {beam_review_instruct_da['produced']} parseable decisions from 422 task outcomes. Its {be['swe_review']['qwen3_30b_instruct2507_500']['invalid_report_count']} malformed reports are preserved as model failures. {beam_rrr_en_note}

The TB2.1 **legacy cached-tag image profile is separate** from the exact user-supplied-image profile. Muse NVFP4 legacy round 1 was **68/88 graded on raw first draw** (one ungraded); its separately labeled score after declared infrastructure replacement draws is **71/89**. Muse NVFP4 legacy rounds 2/3 remain **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}** and **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}** graded. Opus 4.7 completed legacy round 1 at **70/89**; Beam legacy round 1 is {be['tb2_1_legacy_cached_tag']['1']['success']}/{be['tb2_1_legacy_cached_tag']['1']['graded']} graded and partial. The original BF16 run is an exception to the old file label: its 89 image identities and tasks match the supplied archive, so its historical `tb2_1_legacy_cached_tag` field and exact-image field refer to **the same trials**, not two samples. None of the partial counts is a full benchmark accuracy. Independent exact-image and legacy-image trials must not be pooled.

`input_output/swrbench/*/generation.jsonl` holds each exact input prompt and generated review; the adjacent judge JSON holds per-item GPT-5.5 scoring details. `evidence/muse_pro_identity.json` maps all 731 Pro tasks to native result files and hashes. `evidence/muse_deep_canonical_results.json` maps all 339 graded DeepSWE trials to their exact native results. Native per-task I/O, tool traces and returned thinking are too large for ordinary Git objects; use the release archives and `input_output/archive_manifests/` to check coverage and SHA-256. For SWE-Review, use the `*_review_full_io` assets, which include OpenHands completion JSON in addition to trajectories. The `*_review_verifier.tar.zst` assets preserve the original verifier review reports, grade reports and rewards, including ten interrupted Muse trials with complete native verification but missing Harbor summary files.

SWE-Review original-generator revision inputs are in the [Muse](input_output/archive_manifests/muse_review_revision_inputs.json) and [Beam](input_output/archive_manifests/beam_review_revision_inputs.json) base archives and timestamped deltas. Their native outputs, completions, trajectories and verifier records are in the separate [Muse](input_output/archive_manifests/muse_revision_review_full_io.json) and [Beam](input_output/archive_manifests/beam_revision_review_full_io.json) archive chains. The [release coverage audit](evidence/review_revision_release_coverage.json) gives the current prepared and active-queue task-card counts and confirms their inclusion, along with preserved old failure files, in SHA-verified assets. The old host-IP failures and scored gateway-recovery trials have distinct paths; apply later deltas in timestamp order as live trials finish.

Current exact-image TB2.1 native I/O snapshots: `{latest_opus_exact_archive['archive_name']}` contains {latest_opus_exact_archive['terminal_result_count']} terminal Opus 4.7 trials; `{latest_beam_exact_archive['archive_name']}` contains {latest_beam_exact_archive['terminal_result_count']} terminal Beam trials. These snapshots include in-progress trajectories but do not convert partial rounds into final benchmark scores.

The [Opus 4.7](evidence/opus47_exact_round1_audit.json) and [Beam](evidence/beam_bf16_exact_round1_audit.json) first-round audits reconcile each task with its reward and released input, raw response, and trajectory. A full round is reported only when all 89 task results pass this check.

The [Opus 4.7 round-2 audit](evidence/opus47_exact_round2_audit.json) and [round-3 audit](evidence/opus47_exact_round3_audit.json) apply the same task-level release checks to later rounds. All three 89-task rounds are complete and reconciled: **70/89, 71/89, 69/89**, with a three-round mean of **210/267 = 78.65%**.

Beam exact-image TB round 2 runs on the verified BF16 replica at allocation 2887 while round 1 remains on its original endpoint. The [handoff proof](evidence/beam_exact_r23_2887_handoff.json) pins the model revision, Docker image, source and effective configs, and task ownership. A round-2 native result counts once; partial results are never treated as full-round accuracy.

The [Muse BF16 exact-image I/O audit](evidence/muse_bf16_exact_io_coverage.json) checks that every scored BF16 result, raw response and trajectory is present in SHA-verified release archives, along with all 89 task inputs. Of its currently scored raw replies, **{bf16_io.get('nonempty_reasoning_response_count', 0)}/{bf16_io.get('scored_raw_response_count', 0)}** contain nonempty thinking. It is the same BF16 trial set named by the historical cached-tag field.

The [job-2886 BF16 deployment audit](evidence/muse_bf16_2886_deployment_audit.json) verifies both hosts' 78 pinned weight files, the fixed SGLang image, 16-GPU NCCL/EFA preflight, BF16 endpoint, nonbenchmark tool/thinking roundtrip and the separate review sandbox route. It does not certify a benchmark score.

The BF16 SWRBench [source dataset, generation, GPT-5.5 judge and raw-response archive manifest](input_output/archive_manifests/muse_bf16_swr.json) identifies the Release asset; later `muse_bf16_swr_delta_*` archives replace growing paths in timestamp order.

For actively changing Pro/legacy/Deep results, apply each timestamped delta after its base archive, replacing earlier files with the same path. Current delta assets are `{latest_legacy_deltas['opus47_legacy']['archive_name']}`, `{latest_legacy_deltas['beam_legacy']['archive_name']}`, and `{latest_legacy_deltas['muse_bf16']['archive_name']}`. Their manifests state the cutoff and source scope.

The historical Opus 4.8 Pro Verified result has an existing 731-task trajectory archive in the release. Three confirmed solution retrieval cases are flagged; a conservative supplementary calculation withholding those three credits is **500/731 = 68.40%**. The raw benchmark value stays **503/731**.

The release has {asset_count} archive manifests; **{release_audit_label} assets** have a matching GitHub-reported SHA-256 digest and size in `evidence/release-assets-verification.json`. The latest exact-image TB archive is a timestamped snapshot containing both terminal results and ongoing trajectories; only terminal `result.json` files count as scores.

Muse NVFP4 round-one inputs are in `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst` (all 89 public `task.toml` files, original job configs, and image identity checks). The [I/O coverage audit](evidence/muse_nvfp4_exact_io_coverage.json) verifies that the released archives contain every scored result, its raw response and trajectory, and all task inputs.

The [round-one task audit](evidence/muse_nvfp4_exact_round1_audit.json) currently finds nonempty returned thinking in **{mn_audit.get('scored_nonempty_reasoning_response_count', 0)}/{mn_audit.get('scored_raw_response_count', 0)}** raw responses of scored Muse NVFP4 tasks. This is a field-preservation check, not a clean-trajectory verdict.

Round 2 currently has **{nvfp4_rounds['2']['terminal']} terminal tasks, {nvfp4_rounds['2']['graded']} native grades, and {nvfp4_rounds['2']['success']} successes**. Its original `password-recovery` attempt lost the tmux session before verification; [the anchored record](evidence/muse_nvfp4_r2_password_recovery_ungraded.json) preserves the native exception, trajectory and {r2_ungraded_evidence['model_raw_response_count']} raw model responses. That original attempt remains ungraded. A [separately declared one-task infrastructure replacement](evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json) uses the same task, image and sampling settings on an equivalent pinned NVFP4 replica; its native reward is **{r2_replacement_reward_en}**. The round counts at most one grade for this task, with no best-of selection.

The graded `password-recovery` replacement has a [trajectory integrity alert](evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json): {password_replacement_integrity['host_boundary_probe_count']} tool calls probed host mount or block-device paths, including `nsenter` attempts that returned permission denied. Its raw reward remains recorded, but this trajectory is excluded from clean training. The inspected output does not establish successful host access or hidden-answer retrieval.

The original `prove-plus-comm` trial [timed out during agent setup](evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json) before any model response or verification. Its first [declared replacement](evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json) also ended ungraded, before a model reply, because the transient service lacked an API-key environment variable; the [failure receipt](evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json) is retained. One [service-environment correction](evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json) is declared separately; its native reward is **{prove_transport_reward_en}**. Only its first native grade may fill the missing grade; all attempts remain archived, with no best-of selection.

The original NVFP4 service on GPU allocation 2866 is also taking untouched round-2/3 batches. Its [ready proof](evidence/muse_nvfp4_local2866_ready.json), [live route audit](evidence/muse_nvfp4_local2866_route_audit.json), and [controller code](protocol/muse_nvfp4_local2866/README.md) show {local2866_audit['route_count']} locked route(s) owning {local2866_audit['claimed_task_count']} distinct tasks at this snapshot; completed tasks are counted only from their native results.

The round-2 **original first draws** currently have {round2_first_draw['terminal']} terminal tasks, {round2_first_draw['graded']} native grades, and {round2_first_draw['success']} successes; the repaired-round count above includes only explicitly declared replacement grades. `pytorch-model-cli` [lost its tmux channel with the shared 500 GB Docker backing disk at 100%](evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json), leaving its original reward unknown. A [single storage-isolated replacement](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json) on CPU allocation 2922 has native reward **{pytorch_replacement_reward_en}**. Its [limited command and thinking audit](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json) found 13/13 raw replies with reasoning and no visible verifier, grader, hidden-test, or reward access in 40 bash commands; this is not full reward-hacking clearance. The original draw remains ungraded and both trajectories are retained; the full-disk observation alone does not establish which process consumed the space.

Muse NVFP4 exact-image TB2.1 stopped when two model nodes were reassigned to original BF16. Four disjoint continuation lanes are now active on the surviving NVFP4 node 2866, with up to eight simultaneous task trials: 11 previously graded round-1 results are locked, 70 tasks had not been sampled, and 8 interrupted ungraded attempts retain their original partial outputs and are labeled infrastructure replacements. At this snapshot, the continuation has {new_raw_responses} raw model responses, {active_recovery_trial_dirs} active trial directories, and the latest response at {new_raw_response_latest_utc}; these are activity indicators, not scores. The original controller verifies delegated batches before advancing, preventing duplicate scoring. The [first-round task audit](evidence/muse_nvfp4_exact_round1_audit.json) checks task coverage, duplicate draws, frozen original results, endpoint settings, rewards, and preserved raw reasoning; the final score is published only after all 89 tasks pass reconciliation. Additional GPU allocation states: {extra_gpu_status}. A watcher starts the pinned Muse service when a queued allocation is granted. A ready extra GPU atomically claims one untouched round-one batch from b03 or b05; the released 2812 allocation can claim up to two. The existing CPU evaluators retain their original tasks and images, and only the model endpoint changes. A batch that starts locally first cannot be redrawn on another node. This continuation is separate from both the legacy-image scores and the BF16 evaluation.

Scores are benchmark-recorded values. A targeted [Muse exact-TB spot check](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json) found returned reasoning in every raw response of the five completed successful recovery tasks checked. One agent created `/tests/filter.py` by copying the exposed, unchanged `/app/filter.py` to run the task's permitted local test; no filter/verifier rewrite was observed in its commands. This is not a full reward-hacking clearance. The Muse DeepSWE successful trajectory `ipython-session-bundle-replay` attempted to inspect verifier logs, but the returned directory was empty; it remains flagged for training-data review. One successful Muse Pro task lacks a trajectory and is unsuitable for thinking-data export. Source paths and hashes are in `results/scores.json` and `input_output/manifest.json`; raw API credentials and model weights are excluded.

The [exact-TB command screen](evidence/exact_tb_integrity_screen.json) and [anchored manual notes](evidence/exact_tb_integrity_manual_notes.json) currently exclude {len(nvfp4_excluded)} successful Muse NVFP4 trajectories and {len(bf16_excluded)} successful Muse BF16 trajectories from clean training export. The excluded NVFP4 tasks are {nvfp4_excluded_names}; their targeted notes document verifier-log probes, a copy into `/tests/filter.py`, or timing manipulation; the reviewed verifier probes did not confirm hidden-answer retrieval. Both BF16 and NVFP4 `largest-eigenval` scored reward 1.0 after patching timers and slowing the reference eigensolver. Their raw rewards are retained and [the NVFP4 final trajectory review](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json) is anchored by SHA-256, but neither reward demonstrates an unmodified speedup. A separate pre-score alert records NVFP4 [host-boundary probes on `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json); it does not prove successful access or a final score. Keyword screening does not clear other trajectories.
'''
readme = readme.replace('Additional GPU allocation states:', replica_note_en + ' Additional GPU allocation states:', 1)
if bf16_excluded:
    readme = readme.replace('Both BF16 and NVFP4 `largest-eigenval`',
        f'The excluded BF16 tasks are {bf16_excluded_names}; see the per-task notes for their distinct reasons. The newly reviewed verifier and host-boundary probes did not confirm hidden-answer retrieval in the inspected output. Both BF16 and NVFP4 `largest-eigenval`', 1)
readme = readme.replace('A batch that starts locally first cannot be redrawn on another node.', 'A batch that starts locally first cannot be redrawn on another node. The four queued extra GPU allocations are also prepared to take only untouched round-2/3 batches if granted after the round-1 handoffs are claimed. Per-batch locks and ownership receipts prevent the original controller from drawing the same task; the effective config changes only the model endpoint.', 1)
if (ROOT / 'input_output/archive_manifests/muse_bf16_review_inputs.json').exists():
    readme = readme.replace('For actively changing Pro/legacy/Deep results,',
        'The [Muse BF16 SWE-Review input archive](input_output/archive_manifests/muse_bf16_review_inputs.json) contains the 96 prepared model-visible task cards, instructions, Dockerfiles and public task data, plus queue and image receipts. It excludes hidden solutions and tests. Review outputs will be archived separately as trials finish.\n\nFor actively changing Pro/legacy/Deep results,', 1)
if bf16_swr_alignment:
    assert not bf16_swr_alignment['errors']
    readme = readme.replace('For actively changing Pro/legacy/Deep results,',
        f"The [BF16 SWRBench generation/judge alignment audit](evidence/muse_bf16_swr_alignment.json) at {bf16_swr_alignment['generated_utc']} matches {bf16_swr_alignment['judged']} judged IDs to {bf16_swr_alignment['generated']} generated reviews, with no mismatched review after the pinned official evaluator's apostrophe normalization ({bf16_swr_alignment['official_apostrophe_normalization_count']} affected rows). {bf16_swr_note_en}\n\nFor actively changing Pro/legacy/Deep results,", 1)
if bf16_review_progress:
    readme = readme.replace('For actively changing Pro/legacy/Deep results,',
        'The [Muse BF16 SWE-Review native progress audit](evidence/muse_bf16_swe_review_progress.json) matches each terminal result to its planned task and BF16 model configuration. These outcomes are only review-stage progress; split DA and overall RRR require the official downstream scoring stages.\n\nFor actively changing Pro/legacy/Deep results,', 1)
slot1_route_path = B / 'tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes/r2-completion-2866-b02-route.json'
if slot1_route_path.exists():
    slot1_route = read(slot1_route_path)
    assert slot1_route['allocation'] == 2812 and slot1_route['round'] == 2
    assert slot1_route['job_name'] == 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b02'
    readme = readme.replace('Scores are benchmark-recorded values.',
        'On allocation 2812, an additional controller slot claimed untouched exact-image round-2 batch b02 while b01\'s final task was still running. Both controllers use the same pinned NVFP4 endpoint, with two task trials per batch and the server\'s eight-request limit. The [controller source](protocol/muse_nvfp4_exact_future_round_controller_20261019.py) uses separate slot locks and the existing per-batch atomic claim; the b02 route receipt and original/effective config hashes are included in live I/O snapshots. Neither round-1 task nor a previously sampled round-2 task was redrawn.\n\nScores are benchmark-recorded values.', 1)
readme = readme.replace('Scores are benchmark-recorded values.', f'Opus 4.7 Pro counts only its original 731-task run; verifier-only saved-patch retries are retained as separate evidence and never increase the first-round task denominator. Its original `element-hq` task and both saved-patch verifier-only retries timed out after 3600 seconds. [The same task in Beam BF16’s original run](evidence/shared_element_hq_eval_timeout.json) also timed out in the native evaluate phase; neither original task has a valid binary score. This shared observation does not establish the cause or either model’s outcome. {opus_crosshost_en}\n\nScores are benchmark-recorded values.', 1)
if nvfp4_r2_excluded:
    readme = readme.replace('Scores are benchmark-recorded values.',
                            f'Muse NVFP4 round-2 successful trajectories flagged for training exclusion pending full review: {nvfp4_r2_excluded_names}. A targeted review found a verifier-directory listing with no hidden output in the observed response; raw benchmark rewards are unchanged. See [the anchored notes](evidence/exact_tb_integrity_manual_notes.json) and [command screen](evidence/exact_tb_integrity_screen.json).\n\nScores are benchmark-recorded values.', 1)
if opus_thinking_audit:
    oc = opus_thinking_audit['counts']
    readme = readme.replace('Scores are benchmark-recorded values.',
        f'The [Opus 4.7 round-3 thinking transport audit](evidence/opus47_r3_thinking_transport_audit.json), generated {opus_thinking_audit["generated_utc"]}, covers {oc["scored_tasks"]} terminal tasks: {oc["with_thinking_text"]}/{oc["raw_responses"]} archived replies contain thinking text, {oc["without_text_zero_reasoning_tokens"]} report zero reasoning tokens, and {oc["without_text_positive_reasoning_tokens"]} report positive reasoning tokens but have no thinking text even in saved upstream SSE. Those upstream events contain signed empty thinking blocks. Do not use the latter replies as full-thinking training examples.\n\nScores are benchmark-recorded values.', 1)
readme = readme.replace('Scores are benchmark-recorded values.', mn_timeout_en + 'Scores are benchmark-recorded values.', 1)
if early_b05_owner:
    if early_b05_exit and early_b05_exit['returncode'] == 0:
        b05_note = 'The b05 first-round batch finished on GPU 2812 and CPU 2922 with all 10 native results; its ownership receipt prevents a duplicate draw.'
        if replica_2812_r23_status:
            b05_note += (f" GPU 2812 now runs an untouched round-2/3 batch "
                         f"{replica_2812_r23_status.get('job_name', 'none')} under a separate locked route; only the model endpoint changes.")
    else:
        b05_note = 'The b05 batch runs early on CPU allocation 2922 against GPU 2812; its ownership receipt prevents a duplicate draw.'
    readme = readme.replace('This continuation is separate from both the legacy-image scores and the BF16 evaluation.', b05_note + ' This continuation is separate from both the legacy-image scores and the BF16 evaluation.', 1)
readme = readme.replace('Keyword screening does not clear other trajectories.', 'Keyword screening does not clear other trajectories. Targeted [manual notes](evidence/exact_tb_integrity_manual_notes.json) also flag Opus 4.7 `break-filter-js-from-html` for an unsuccessful `/tests` probe and Beam BF16 on the same task for a temporary copy of the exposed filter into `/tests/filter.py` (removed before grading); neither inspected output confirms hidden-answer retrieval, and both are excluded from clean training pending full review. The Opus `torch-pipeline-parallelism` keyword hit was only a Python-executable listing.', 1)
db_wal_note = next((note for note in manual_notes if note['model'] == 'muse_nvfp4' and note['task'] == 'db-wal-recovery'), None)
if db_wal_note:
    assert db_wal_note['reward'] == 0.0
    old = 'A separate pre-score alert records NVFP4 [host-boundary probes on `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json); it does not prove successful access or a final score.'
    new = 'The earlier [host-boundary alert for `db-wal-recovery`](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json) now has a terminal result: the agent timed out after 10800 seconds with recorded reward 0. [Manual notes](evidence/exact_tb_integrity_manual_notes.json) exclude its trajectory from clean training; the inspected probes do not establish successful host access. The raw benchmark result remains unchanged.'
    assert readme.count(old) == 1
    readme = readme.replace(old, new, 1)
if (ROOT / 'input_output/archive_manifests/muse_bf16_review_inputs.json').exists():
    assert readme.count('The [Muse BF16 SWE-Review input archive]') == 1
if slot1_route_path.exists():
    assert readme.count('an additional controller slot claimed untouched') == 1
if bf16_swr_alignment:
    assert readme.count('[BF16 SWRBench generation/judge alignment audit]') == 1
(ROOT / 'README.md').write_text(readme)
chinese_report = f'''# 模型评测结果快照

更新时间：**{now}**。逐题原始输入、输出、thinking/轨迹及 SHA-256 清单见 [GitHub Release](https://github.com/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tag/2026-10-19-snapshot) 和 `input_output/archive_manifests/`。当前仓库为私有。

| 模型 | 已完成、可汇报的结果 | 尚未完成的项目 |
|---|---|---|
| Muse NVFP4 | SWE-bench Pro Verified **496/731（67.85%）**，首轮；DeepSWE 三轮 **57/113、59/113、63/113**，均值 **52.80%**；SWRBench GPT-5.5 裁判 **55.4%（1000/1000）**；SWE-Review 三组官方 DA：GLM5 **{review_glm_da['DA']}%（500 题）**、Coder **{review_coder_da['DA']}%（462 题）**、Instruct **{review_instruct_da['DA']}%（422 题）**{muse_rrr_zh_table}{muse_exact_zh_done} | {muse_exact_zh_pending}SWE-Review 整体 RRR 尚未完成 |
| Beam BF16 | SWRBench GPT-5.5 裁判 **55.6%（1000/1000）**；SWE-Review Instruct 组封存 DA **{beam_review_instruct_da['DA']}%（422 题）**{beam_rrr_zh_table}{beam_exact_zh_done} | Pro Verified **{be['swe_bench_pro_verified']['graded']}/731 已判分、{be['swe_bench_pro_verified']['success']} 成功**；DeepSWE 首轮 **{be['deepswe']['1']['graded']}/113、{be['deepswe']['1']['success']} 成功**{beam_exact_zh_pending}；SWE-Review 另两组与整体 RRR 未完成 |
| Opus 4.7 | 旧缓存镜像 TB2.1 首轮 **70/89（78.65%）**{opus_deep_zh_done}{opus_exact_zh_done} | Pro Verified **{op['swe_bench_pro_verified']['graded']}/731 已判分、{op['swe_bench_pro_verified']['success']} 成功**{opus_deep_zh_pending}{opus_exact_zh_pending}；SWE-Review {opus_review_zh} |
| Opus 4.8（历史） | Pro Verified **503/731（68.81%）**，其中 3 例确认检索到答案；保守扣除后 **500/731（68.40%）** | 不能把该补充计算当作原始分数 |
| Muse 原始 BF16 | {'；'.join(part for part in (bf16_swr_zh, bf16_exact_zh_done.lstrip('；')) if part) or '暂无完整 benchmark 分数'} | Pro Verified **{models['muse_bf16']['swe_bench_pro_verified']['graded']}/731 已判分**{bf16_exact_zh_pending}；DeepSWE 运行中{'; SWRBench ' + bf16_swr_en if not bf16_swr_complete else ''}{bf16_review_zh} |

Opus 4.7 SWE-Review 使用未改动的官方题卡，每题仅一次评审抽样。[模型可见输入](input_output/archive_manifests/opus47_review_inputs.json)及[原生输出、逐次回复和轨迹](input_output/archive_manifests/opus47_review_full_io.json)已作为带 SHA 校验的 Release 资产保存。输出归档是运行中的局部快照，后续增量归档会续传；仅凭评审阶段结果不能报告 DA 或 RRR。

Muse BF16 原节点在 Pro、TB2.1、DeepSWE 运行中到期。[恢复审计](evidence/muse_bf16_2865_expiry_recovery.json)记录了原始及续跑 ID：**137 道已完成的 Pro 题仅复用一次**，原运行的 10 道失败题和 4 道中断题单独保留。当前 Pro 进度只统计续跑的原生结果，故恢复初期局部已判分数可能暂时下降。另有两道 TB 和两道 DeepSWE 的中断原始输入输出及轨迹，分别保存在已做 SHA 校验的 [TB](input_output/archive_manifests/muse_bf16_interrupted_tb_delta_20261020T072043Z.json) 与 [DeepSWE](input_output/archive_manifests/muse_bf16_interrupted_deep_delta_20261020T072043Z.json) 归档中；这些原记录尚未判分，不计为模型失败。

**SWE-Review 三组 DA 均已有封存收据。** 官方 `compute_da.py` 在 GLM5 {review_glm_da['produced']} 个可解析决定上得 **{review_glm_da['DA']}%**（500 题终态），Qwen3-Coder {review_coder_da['produced']} 个得 **{review_coder_da['DA']}%**（462 题），Qwen3-30B-Instruct {review_instruct_da['produced']} 个得 **{review_instruct_da['DA']}%**（422 题）。[逐题哈希和官方评分核验](evidence/swe_review_complete_split_da.json)覆盖全部三组。[新版任务准备收据审计](evidence/muse_swe_review_revision_v2_receipts.json)确认 GLM5 的 8 道、Coder 的 2 道只缺 Harbor 汇总：它们的真实原生报告参与 DA，标明用途的适配文件仅供官方修复任务生成，绝非模型结果。{muse_rrr_zh_note}

[修订阶段基础设施审计](evidence/swe_review_revision_queue_recovery_20261020.json)记录了两种任务输入格式、准备错误，以及沙箱在首个模型回复前的连接超时；这些原生失败不计入模型成绩。随后两条合成 Harbor 任务经 Docker 宿主桥接地址完成模型生成、终端工具调用及原生验证，且不纳入 benchmark。四条正式生成补测队列已用[桥接地址 agent](protocol/muse_review_revision_v2/revision_agents_bridge_v4.py)和原任务输入启动，部分分组已完成。[原生实时判分审计](evidence/swe_review_revision_gateway_progress.json)显示 Muse Coder **{review_revision_muse_coder['native_graded_revisions']}/{review_revision_muse_coder['expected_revisions']}**、Muse Instruct **{review_revision_muse_instruct['native_graded_revisions']}/{review_revision_muse_instruct['expected_revisions']}**、Beam Coder **{review_revision_beam_coder['native_graded_revisions']}/{review_revision_beam_coder['expected_revisions']}**、Beam Instruct **{review_revision_beam_instruct['native_graded_revisions']}/{review_revision_beam_instruct['expected_revisions']}** 道修订已判分；只有分组内全部原生判分与已归档证据核验通过才报告该分组 RRR。[v3 评分脚本](protocol/muse_review_revision_v2/revision_score_v3.py)只读取修正后的桥接队列结果，将 Beam 的 5 份非法评审报告保留为模型失败，并逐项复现四组已封存 DA。

[Beam Coder 端口错误审计](evidence/beam_coder_pre_model_port_mismatch.json)保留了首批 16 道基础设施失败：沙箱放行 31411 端口，Qwen3-Coder 模型实际服务于 31410，因此均未收到模型回复或原生判分，不计入模型成绩。独立的[修正后 224 题队列](protocol/beam_review_revision_v2/beam_coder_portfix/queue-plan.json)放行 31410；其[独立合成预检](protocol/beam_review_revision_v2/beam_coder_portfix/synthetic-portfix-r2-passed.json)已完成模型生成和原生验证。合成输出不计入成绩，修正队列中的每道被拒绝 PR 只抽样一次。

[SWE-Review 控制器核验](evidence/swe_review_recovery_control.json)确认旧队列于 03:17 UTC 中断：11 题从未领取、23 题虽被领取却没有任何原生题目目录；这 34 题已拆成互不重叠的两条续跑队列，继续用同一 Muse NVFP4 模型。另有 16 题留下部分模型输出：其中 10 题的 agent 结束步骤及原生验证报告、reward 都已保存，只缺 Harbor 汇总文件，原结果保留且未重抽；其余 6 题无最终评审报告，已另列基础设施中断补测。旧状态文件中的 healthy 是停机前的记录，不能当作当前运行状态。

Beam SWE-Review 有[**{beam_malformed_count} 份已抽样但 JSON 无法解析的报告**](evidence/beam_swe_review_malformed_reports.json)，旧任务准备控制器因此失败。[带源码哈希的新版本准备协议](protocol/beam_review_revision_v2/task-preparation-plan-v2.json)保留原始文件，并按官方生成器的缺失决定回退处理；当前阶段为 `{beam_prep_phase}`。另两组评审仍在继续。

Beam BF16 的 SWE-Review Instruct 组已有[封存的官方 DA](evidence/swe_review_complete_split_da.json)：422 题终态中 {beam_review_instruct_da['produced']} 个决定可解析，**DA {beam_review_instruct_da['DA']}%**。其中 {be['swe_review']['qwen3_30b_instruct2507_500']['invalid_report_count']} 份格式错误的原始报告保留，按模型无有效决定处理。{beam_rrr_zh_note}

**TB2.1 镜像口径必须分开。** Muse NVFP4 的旧缓存镜像首轮原始首抽为 **68/88 判分、1 题无分**；事先记录的基础设施修复重跑后为 **71/89**。旧镜像第 2、3 轮目前分别是 **{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['2']['graded']}**、**{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['success']}/{mn['tb2_1_legacy_cached_tag']['rounds_2_3']['3']['graded']}**，尚无三轮均值。BF16 的历史字段虽名为 `tb2_1_legacy_cached_tag`，[镜像身份审计](evidence/muse_bf16_exact_image_identity.json)已证实启动前及运行节点上的 89 个镜像与指定归档一致，题目和推理设置也一致；它与精确镜像字段指向**同一轮测试**，不能相加。{mn_exact_note_zh}{mteb_timeout_note_zh}两节点切给原始 BF16 后，该评测中断；现在已在保留的 2866 节点恢复，首轮拆成四条互不重叠的队列，最多 8 题并行。本次快照中恢复任务已有 {new_raw_responses} 条原始模型响应、{active_recovery_trial_dirs} 个运行中题目目录，最新响应时间为 {new_raw_response_latest_utc}；这些是活跃度，不是分数。原来 8 个未判分但已有部分模型响应的记录仍保留，后续尝试明确标为基础设施重跑；[首轮逐题核验](evidence/muse_nvfp4_exact_round1_audit.json)会检查重复、缺题、原始结果哈希、判分和 thinking 原始响应，满 89 题且核验通过后才发布首轮准确率。新增 GPU 申请状态：{extra_gpu_status}。排队节点获配后监控器会启动同一 NVFP4 模型服务，并逐批加锁领取 b03、b05 中尚未启动的一批；early95 结束后腾出的 2812 最多可领取两批。原 CPU 评测器继续使用原题目和镜像，仅模型端点变化；若本地批次先启动，不会在其他节点重复抽题。

**审计限制。** [Muse 精确镜像 TB 抽查](evidence/muse_nvfp4_exact_recovery_success_spotcheck.json)显示，当时新增的 5 道成功题每条原始响应都有 reasoning 字段。其中一题把题目公开的 `/app/filter.py` 原样复制到 `/tests/filter.py` 做本地测试；检查到的命令没有改写过滤器或 verifier，但这只是定点核查，不能宣称所有轨迹都干净。Muse DeepSWE 有一条成功轨迹尝试查看 verifier 日志，但返回的目录为空；这条轨迹已单独标记供训练数据筛查，现有证据不能断言读到了隐藏答案。Muse Pro Verified 有一条成功记录缺少轨迹，不应作为带 thinking 的训练样本。SWE-Review 的完整官方 RRR 尚未生成，任何已结束题数都不等于最终成绩。

[精确镜像 TB 命令筛查](evidence/exact_tb_integrity_screen.json)及[哈希锚定的人工核查](evidence/exact_tb_integrity_manual_notes.json)目前将 Muse NVFP4 的 {len(nvfp4_excluded)} 条、Muse BF16 的 {len(bf16_excluded)} 条成功轨迹排除出“干净训练轨迹”候选。排除的 NVFP4 题目是 {nvfp4_excluded_names}；逐题核查记录了 verifier 日志探查、向 `/tests/filter.py` 复制公开文件或计时篡改；已检查的 verifier 探查输出没有确认获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval` 都通过修改计时函数、拖慢参考特征值求解器拿到原始 reward 1；原始分数保留，NVFP4 的[最终轨迹审计](evidence/muse_nvfp4_largest_eigenval_live_integrity_alert.json)有哈希锚定，但这两条高分不能当作未经篡改的加速证据。另一份判分前预警记录了 NVFP4 [`db-wal-recovery` 对宿主边界的探查](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)，它不证明边界探查成功，也不是最终分数。关键词未命中也不代表轨迹已获干净认证。

逐题证据可从 `evidence/` 和 release archive 检查。`input_output/swrbench/*/generation.jsonl` 直接包含逐题 prompt、模型响应和 review，旁边的 GPT-5.5 评判 JSON 包含逐题裁判详情。Release 共 {asset_count} 个归档，SWE-Review 的 `*_review_full_io.tar.zst` 含 OpenHands completions；`*_review_verifier.tar.zst` 含原生验证器的评审报告、判分报告和 reward，其中包括 10 道缺 Harbor 汇总文件但已完成原生验证的 Muse 题。最新 `muse_nvfp4_exact_tb_live_*.tar.zst` 同时包含已有判分结果和仍在运行题目的原始输入输出；只有终态 `result.json` 才计入分数。**GitHub 返回的 SHA-256 与提交的清单核对为 {release_audit_label}**，逐项核验见 `evidence/release-assets-verification.json`。

SWE-Review 原始生成模型的修订输入见 [Muse](input_output/archive_manifests/muse_review_revision_inputs.json) 和 [Beam](input_output/archive_manifests/beam_review_revision_inputs.json) 基础归档及按时间命名的增量归档；原生输出、completions、轨迹及 verifier 记录见独立的 [Muse](input_output/archive_manifests/muse_revision_review_full_io.json) 和 [Beam](input_output/archive_manifests/beam_revision_review_full_io.json) 归档链。[Release 覆盖审计](evidence/review_revision_release_coverage.json)给出当前各模型已准备及已进入桥接补测队列的任务卡数量，并确认这些输入与旧故障文件都在 SHA 校验通过的归档中。旧节点地址导致的首回复前失败与可判分的桥接补测分属不同路径；后续增量归档按时间覆盖仍在增长的文件。

Muse NVFP4 首轮全部 89 题的公开 `task.toml`、原始分题配置和镜像身份校验在 `muse_nvfp4_exact_tb_round1_inputs_20261019.tar.zst`；[输入输出覆盖核验](evidence/muse_nvfp4_exact_io_coverage.json)逐题确认已判分结果、原始响应、轨迹和任务输入均在远端校验过的归档中。

[Muse NVFP4 首轮逐题审计](evidence/muse_nvfp4_exact_round1_audit.json)目前确认已判分题的原始回复中 **{mn_audit.get('scored_nonempty_reasoning_response_count', 0)}/{mn_audit.get('scored_raw_response_count', 0)} 条含非空 thinking**。这只核验字段留存，不表示轨迹可直接作为干净训练数据。

第 2 轮目前 **{nvfp4_rounds['2']['terminal']} 题终态、{nvfp4_rounds['2']['graded']} 题有原生判分、{nvfp4_rounds['2']['success']} 题成功**。原始 `password-recovery` 尝试在验证前失去 tmux 会话；[哈希锚定记录](evidence/muse_nvfp4_r2_password_recovery_ungraded.json)保留了原生异常、轨迹和 {r2_ungraded_evidence['model_raw_response_count']} 条模型原始回复，原尝试仍未判分。[单题基础设施补测声明](evidence/muse_nvfp4_r2_password_recovery_replacement_claim.json)固定原题、镜像和采样设置，使用已核验的等价 NVFP4 副本；补测原生 reward 当前为 **{r2_replacement_reward_zh}**。本轮该题最多计一个有效判分，不择优取样。

`password-recovery` 已判分补跑有[轨迹完整性警报](evidence/muse_nvfp4_r2_password_replacement_integrity_alert.json)：{password_replacement_integrity['host_boundary_probe_count']} 次工具调用探查宿主挂载或块设备路径，其中 `nsenter` 返回权限不足。原始 reward 保留，但这条轨迹排除出干净训练集；所检查的输出不能证明成功进入宿主或读取隐藏答案。

`prove-plus-comm` 原始尝试在 agent 初始化时[超时](evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json)，模型没有产生回复，也没有原生判分。首次[已声明补跑](evidence/muse_nvfp4_r2_prove_plus_comm_replacement_claim.json)因服务进程缺少 API-key 环境变量，在模型首回复前再次失败且未判分；[故障记录](evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json)保留了原始证据。随后另行声明[服务环境修正](evidence/muse_nvfp4_r2_prove_plus_comm_transport_correction_claim.json)，其原生 reward 当前为 **{prove_transport_reward_zh}**。本题只允许修正后的首个有效原生判分填补缺失值；所有尝试均保留，不择优取样。

原 NVFP4 服务节点 2866 也开始领取第 2/3 轮尚未启动的批次。[节点就绪凭据](evidence/muse_nvfp4_local2866_ready.json)、[实时路由审计](evidence/muse_nvfp4_local2866_route_audit.json)及[控制器代码](protocol/muse_nvfp4_local2866/README.md)显示，本次快照已有 {local2866_audit['route_count']} 条加锁路由，独占 {local2866_audit['claimed_task_count']} 道不同题；只按原生结果统计完成题。

第 2 轮**原始首抽**目前有 {round2_first_draw['terminal']} 题终态、{round2_first_draw['graded']} 题有效原生判分、{round2_first_draw['success']} 题成功；上面的修复后统计只补入已单独声明的有效补跑判分。`pytorch-model-cli` 的[原尝试](evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json)在共用 500 GB Docker 底盘占满时失去 tmux 通道，原始 reward 未知。[单次隔离存储补跑](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json)改用 CPU 节点 2922，当前原生 reward 为 **{pytorch_replacement_reward_zh}**。[局部命令与 thinking 核验](evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json)显示原始回复 13/13 条含推理，40 条 bash 命令中未见访问裁判、隐藏测试或 reward 的迹象；这不等于完整排除 reward hacking。原始首抽仍未判分，两次轨迹都保留；磁盘占满本身不能证明由哪个进程消耗了空间。

[Muse BF16 精确镜像输入输出核验](evidence/muse_bf16_exact_io_coverage.json)逐题确认 BF16 已判分结果、原始回复和轨迹都在远端校验过的 BF16 归档中，89 道题输入由相同的指定镜像任务输入归档覆盖；当前已判分题的原始回复中 **{bf16_io.get('nonempty_reasoning_response_count', 0)}/{bf16_io.get('scored_raw_response_count', 0)} 条含非空 thinking**。

[BF16 2886 双节点部署核验](evidence/muse_bf16_2886_deployment_audit.json)记录两台节点各 78 个固定权重文件的校验、SGLang 镜像版本、16 卡 NCCL/EFA 预检、BF16 接口，以及与正式评测分开的工具调用和 thinking 往返检查；这不是 benchmark 成绩。

BF16 SWRBench 的[逐题源数据、生成、GPT-5.5 裁判及原始回复归档清单](input_output/archive_manifests/muse_bf16_swr.json)指向 GitHub Release 资产；后续 `muse_bf16_swr_delta_*` 归档按时间覆盖仍在增长的同路径文件。

Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照分别是 `{latest_opus_exact_archive['archive_name']}`（{latest_opus_exact_archive['terminal_result_count']} 个终态结果）和 `{latest_beam_exact_archive['archive_name']}`（{latest_beam_exact_archive['terminal_result_count']} 个终态结果）。其中运行中的轨迹不算已判分，未满 89 题的轮次不报告最终准确率。

[Opus 4.7 首轮核验](evidence/opus47_exact_round1_audit.json)与 [Beam 首轮核验](evidence/beam_bf16_exact_round1_audit.json)逐题核对判分、任务输入、原始响应和轨迹；满 89 题且核验通过后才报告完整准确率。

[Opus 4.7 第 2 轮核验](evidence/opus47_exact_round2_audit.json)和[第 3 轮核验](evidence/opus47_exact_round3_audit.json)按相同规则逐题检查后续轮次。三轮各 89 题均已完整且核验通过：**70/89、71/89、69/89**，三轮均值 **210/267 = 78.65%**。

Beam 精确镜像 TB 第 2 轮现由 2887 上核验过的 BF16 副本独立执行，第 1 轮继续使用原接口。[接管凭据](evidence/beam_exact_r23_2887_handoff.json)固定模型版本、镜像、原始及有效配置哈希和轮次归属；第 2 轮逐题只计一次，未满 89 题不报告整轮准确率。

仍在增长的 Pro/旧镜像/DeepSWE 结果，需在基准归档之后按时间叠加增量归档，同路径文件以后者为准。目前三个增量分别是 `{latest_legacy_deltas['opus47_legacy']['archive_name']}`、`{latest_legacy_deltas['beam_legacy']['archive_name']}`、`{latest_legacy_deltas['muse_bf16']['archive_name']}`；截止时间和文件范围见各自清单。
'''
chinese_report = chinese_report.replace('新增 GPU 申请状态：', replica_note_zh + ' 新增 GPU 申请状态：', 1)
if bf16_excluded:
    chinese_report = chinese_report.replace('BF16 和 NVFP4 的 `largest-eigenval`',
        f'排除的 BF16 题目是 {bf16_excluded_names}，各题原因见逐题核查；新核查的 verifier 与宿主边界探查在已检查输出中未证实获得隐藏答案。BF16 和 NVFP4 的 `largest-eigenval`', 1)
if nvfp4_r2_excluded:
    chinese_report = chinese_report.replace('仍在增长的 Pro/旧镜像/DeepSWE 结果，',
        f'第 2 轮 Muse NVFP4 的成功轨迹 {nvfp4_r2_excluded_names} 曾探查 verifier 目录；已检查的返回为空，未证实获得隐藏答案。原始 reward 保留，轨迹暂不进入干净训练数据，见[哈希锚定核查](evidence/exact_tb_integrity_manual_notes.json)和[命令筛查](evidence/exact_tb_integrity_screen.json)。\n\n仍在增长的 Pro/旧镜像/DeepSWE 结果，', 1)
if opus_thinking_audit:
    oc = opus_thinking_audit['counts']
    chinese_report = chinese_report.replace('仍在增长的 Pro/旧镜像/DeepSWE 结果，',
        f'[Opus 4.7 第 3 轮 thinking 传输核查](evidence/opus47_r3_thinking_transport_audit.json)生成于 {opus_thinking_audit["generated_utc"]}，覆盖 {oc["scored_tasks"]} 道终态题：{oc["raw_responses"]} 条归档回复中 {oc["with_thinking_text"]} 条有可读 thinking，{oc["without_text_zero_reasoning_tokens"]} 条用量显示 reasoning token 为零，另 {oc["without_text_positive_reasoning_tokens"]} 条虽计入 reasoning token，但上游原始流也没有可读 thinking，仅有签名。后者不能作为带完整 thinking 的训练样本。\n\n仍在增长的 Pro/旧镜像/DeepSWE 结果，', 1)
chinese_report = chinese_report.replace('若本地批次先启动，不会在其他节点重复抽题。', '若本地批次先启动，不会在其他节点重复抽题。另有四个排队 GPU 节点获配后只领取第 2/3 轮尚未启动的批次；逐批文件锁和接管凭据阻止原控制器重复抽题，实际配置仅修改模型端点。', 1)
chinese_report = chinese_report.replace('**审计限制。**', f'Opus 4.7 Pro 只统计原始运行的 731 道题；同一补丁的纯验证重试单独留证，不能增加首轮题数或成功数。原始运行的 `element-hq` 与两次纯验证重试均在 3600 秒后超时；[Beam BF16 原始运行的同一道题](evidence/shared_element_hq_eval_timeout.json)也在原生 evaluate 阶段超时，两边原始结果都没有有效二元评分。这一共同现象不能证明根因，也不能判定任一模型在该题上成功或失败。{opus_crosshost_zh}\n\n**审计限制。**', 1)
chinese_report = chinese_report.replace('**审计限制。**', mn_timeout_zh + '**审计限制。**', 1)
if early_b05_owner:
    if early_b05_exit and early_b05_exit['returncode'] == 0:
        b05_note_zh = '首轮 b05 已在 GPU 2812、CPU 2922 完成 10 道原生题；归属凭据阻止重复抽题。'
        if replica_2812_r23_status:
            b05_note_zh += (f"GPU 2812 现以独立加锁接管运行未抽取的第 2/3 轮批次 "
                            f"{replica_2812_r23_status.get('job_name', '无')}；仅改变模型端点。")
    else:
        b05_note_zh = '首轮 b05 正在 CPU 2922、GPU 2812 运行；归属凭据阻止重复抽题。'
    chinese_report = chinese_report.replace('若本地批次先启动，不会在其他节点重复抽题。', '若本地批次先启动，不会在其他节点重复抽题。' + b05_note_zh, 1)
chinese_report = chinese_report.replace('关键词未命中也不代表轨迹已获干净认证。', '关键词未命中也不代表轨迹已获干净认证。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)还标记了 Opus 4.7 在 `break-filter-js-from-html` 上对不存在的 `/tests` 的探查，以及 Beam BF16 在同题中把公开的过滤器临时复制到 `/tests/filter.py`、在判分前删除的行为；检查到的输出均未确认获得隐藏答案，两条轨迹暂不作为干净训练数据。Opus `torch-pipeline-parallelism` 的关键词命中只是列举 Python 可执行文件。', 1)
if (ROOT / 'input_output/archive_manifests/muse_bf16_review_inputs.json').exists():
    chinese_report = chinese_report.replace('Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照',
        '[BF16 SWE-Review 输入归档](input_output/archive_manifests/muse_bf16_review_inputs.json)保存了 96 道已准备题目的模型可见任务卡、指令、Dockerfile、公开题目数据，以及队列与镜像记录；不含隐藏解法和测试。正式轨迹与判分将在任务完成后另行归档。\n\nOpus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照', 1)
if bf16_swr_alignment:
    assert not bf16_swr_alignment['errors']
    chinese_report = chinese_report.replace('Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照',
        f"[BF16 SWRBench 生成与裁判对齐核验](evidence/muse_bf16_swr_alignment.json)于 {bf16_swr_alignment['generated_utc']} 将 {bf16_swr_alignment['judged']} 条裁判记录逐题对到 {bf16_swr_alignment['generated']} 条生成记录；按固定官方评分代码的撇号规范化后没有 review 文本错配（涉及 {bf16_swr_alignment['official_apostrophe_normalization_count']} 条）。{bf16_swr_note_zh}\n\nOpus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照", 1)
if bf16_review_progress:
    chinese_report = chinese_report.replace('Opus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照',
        '[Muse BF16 SWE-Review 原生进度核验](evidence/muse_bf16_swe_review_progress.json)逐题对照队列任务及 BF16 模型配置；终态数量只表示评审阶段进度，分组 DA 和整体 RRR 仍需官方后续评分。\n\nOpus 4.7 与 Beam 精确镜像 TB2.1 的当前原始输入输出快照', 1)
if slot1_route_path.exists():
    chinese_report = chinese_report.replace('Opus 4.7 Pro 只统计原始运行的 731 道题',
        'GPU 2812 的第二个控制器槽在 b01 最后一题仍运行时领取了未抽样的精确镜像第 2 轮 b02 批次；两条控制器共用已固定的 NVFP4 服务，各批次并发 2 题，服务上限为 8 个请求。[控制器源码](protocol/muse_nvfp4_exact_future_round_controller_20261019.py)使用独立槽锁和原有逐批原子领取；b02 接管凭据及原始/实际配置哈希收录于原始输入输出快照。首轮题目及已抽样的第 2 轮题目均未重抽。\n\nOpus 4.7 Pro 只统计原始运行的 731 道题', 1)
if db_wal_note:
    old = '另一份判分前预警记录了 NVFP4 [`db-wal-recovery` 对宿主边界的探查](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)，它不证明边界探查成功，也不是最终分数。'
    new = '此前的 NVFP4 [`db-wal-recovery` 宿主边界探查预警](evidence/muse_nvfp4_db_wal_recovery_live_integrity_alert.json)现已有终态：agent 运行 10800 秒后超时，原始奖励为 0。[人工核查记录](evidence/exact_tb_integrity_manual_notes.json)将该轨迹排除出干净训练数据；抽查输出未证明成功越过宿主边界，原始评测结果保持不变。'
    assert chinese_report.count(old) == 1
    chinese_report = chinese_report.replace(old, new, 1)
if (ROOT / 'input_output/archive_manifests/muse_bf16_review_inputs.json').exists():
    assert chinese_report.count('[BF16 SWE-Review 输入归档]') == 1
if slot1_route_path.exists():
    assert chinese_report.count('GPU 2812 的第二个控制器槽') == 1
if bf16_swr_alignment:
    assert chinese_report.count('[BF16 SWRBench 生成与裁判对齐核验]') == 1
(ROOT / 'REPORT.zh-CN.md').write_text(chinese_report)
print(json.dumps({'snapshot': now, 'files': len(files), 'repo': str(ROOT)}))
