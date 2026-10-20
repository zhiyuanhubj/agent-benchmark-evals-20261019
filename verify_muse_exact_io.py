#!/usr/bin/env python3
"""Check released Muse exact-TB archives cover every scored input and output."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
MANIFESTS = ROOT / 'input_output/archive_manifests'
EVIDENCE = ROOT / 'evidence'
audit = json.loads((EVIDENCE / 'muse_nvfp4_exact_round1_audit.json').read_text())
names = [
    'muse_exact_tb.json',
    'muse_nvfp4_exact_tb_round1_inputs_20261019.json',
    sorted(MANIFESTS.glob('muse_nvfp4_exact_tb_live_*.json'))[-1].name,
]
manifests = [json.loads((MANIFESTS / name).read_text()) for name in names]
live_stamp = names[-1].removesuffix('.json').rsplit('_live_', 1)[1]
live_archive_started = datetime.strptime(live_stamp, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
score_generated = datetime.fromisoformat(json.loads((ROOT / 'results/scores.json').read_text())['generated_utc'])
deferred_post_score_results = []


def finished_by_score_snapshot(result):
    if not result.exists():
        return False
    finished = json.loads(result.read_text()).get('finished_at')
    if not finished:
        return False
    if datetime.fromisoformat(finished.replace('Z', '+00:00')) > score_generated:
        deferred_post_score_results.append(str(result.relative_to(BASE)))
        return False
    return True


entries = set()
for manifest in manifests:
    archive = ROOT / '.release_assets' / manifest['archive_name']
    listed = subprocess.run(
        ['tar', '--use-compress-program=zstd', '-tf', str(archive)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    entries.update(listed.stdout.splitlines())

task_inputs = set()
for shard in (1, 2, 3):
    config = json.loads((BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/configs/r1-shard{shard}.json').read_text())
    for item in config['tasks']:
        task_inputs.add(str((Path(item['path']) / 'task.toml').relative_to(BASE)))
assert len(task_inputs) == 89
missing_inputs = sorted(task_inputs - entries)
missing_results = []
missing_raw = []
missing_trajectories = []
for task, row in audit['tasks'].items():
    result = row['result_path']
    if result not in entries:
        missing_results.append(task)
    trial_prefix = result.removesuffix('result.json')
    if not any(path.startswith(trial_prefix + 'agent/raw_responses/') for path in entries):
        missing_raw.append(task)
    if trial_prefix + 'agent/trajectory.json' not in entries:
        missing_trajectories.append(task)
required_handoff_files = []
if audit.get('replica_handoff'):
    required_handoff_files.append(str((BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867/r1-b06-b07-handoff.json').relative_to(BASE)))
    required_handoff_files.extend(str(Path(row['effective_config']).relative_to(BASE)) for row in audit['replica_handoff']['batches'])
for route in audit.get('opportunistic_routes_extra_gpu', []):
    required_handoff_files.append(str(Path(route['receipt_path']).relative_to(BASE)))
    required_handoff_files.append(str(Path(route['effective_config']).relative_to(BASE)))
    ready_path = BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu/{route["allocation"]}-ready.json'
    required_handoff_files.append(str(ready_path.relative_to(BASE)))
if audit.get('early_b05_handoff'):
    handoff = audit['early_b05_handoff']
    required_handoff_files.append(str(Path(handoff['owner_path']).relative_to(BASE)))
    if handoff.get('exit_path'):
        required_handoff_files.append(str(Path(handoff['exit_path']).relative_to(BASE)))
missing_handoff_files = sorted(set(required_handoff_files) - entries)

connection_claim = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-connection-recovery-20261020-claim.json'
connection_config = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/configs/r2-connection-recovery-20261020.json'
connection_job = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4/muse-nvfp4-tb-v1-exact-r2-connection-recovery-20261020'
missing_connection_files = []
missing_connection_results = []
missing_connection_raw = []
missing_connection_trajectories = []
if connection_claim.exists():
    for path in (connection_claim, connection_config, ROOT / 'prepare_muse_nvfp4_r2_connection_recovery.py'):
        if str(path.relative_to(BASE)) not in entries:
            missing_connection_files.append(str(path.relative_to(BASE)))
    for trial in connection_job.glob('*'):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not finished_by_score_snapshot(result):
            continue
        result_name = str(result.relative_to(BASE))
        if result_name not in entries:
            missing_connection_results.append(trial.name)
        raw_dir = trial / 'agent/raw_responses'
        if any(raw_dir.glob('*.json')) and not any(
                path.startswith(str(raw_dir.relative_to(BASE)) + '/') for path in entries):
            missing_connection_raw.append(trial.name)
        trajectory = trial / 'agent/trajectory.json'
        if trajectory.exists() and str(trajectory.relative_to(BASE)) not in entries:
            missing_connection_trajectories.append(trial.name)

expiry_claim_path = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-expiry-correction-2902-20261020-claim.json'
missing_expiry_files = []
missing_expiry_results = []
missing_expiry_raw = []
missing_expiry_trajectories = []
if expiry_claim_path.exists():
    expiry_claim = json.loads(expiry_claim_path.read_text())
    for path in (expiry_claim_path, Path(expiry_claim['config']),
                 Path(expiry_claim['new_endpoint_ready']), Path(expiry_claim['new_reasoning_preflight']),
                 ROOT / 'protocol/prepare_muse_nvfp4_r2_expiry_correction_20261020.py',
                 ROOT / 'protocol/run_muse_nvfp4_r2_expiry_correction_20261020.py'):
        if str(path.relative_to(BASE)) not in entries:
            missing_expiry_files.append(str(path.relative_to(BASE)))
    expiry_job = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4' / expiry_claim['job_name']
    for trial in expiry_job.glob('*'):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not finished_by_score_snapshot(result):
            continue
        if str(result.relative_to(BASE)) not in entries:
            missing_expiry_results.append(trial.name)
        raw_dir = trial / 'agent/raw_responses'
        if any(raw_dir.glob('*.json')) and not any(
                path.startswith(str(raw_dir.relative_to(BASE)) + '/') for path in entries):
            missing_expiry_raw.append(trial.name)
        trajectory = trial / 'agent/trajectory.json'
        if trajectory.exists() and str(trajectory.relative_to(BASE)) not in entries:
            missing_expiry_trajectories.append(trial.name)

missing_fasttext_files = []
missing_fasttext_results = []
missing_fasttext_raw = []
missing_fasttext_trajectories = []
for label in ('fasttext-expiry', 'fasttext-tmux'):
    claim_path = BASE / ('.private/beam_20261018/tb_v1_exact_images_20261019/'
                         f'muse_nvfp4/state/r2-{label}-2902-20261020-claim.json')
    if not claim_path.exists():
        continue
    claim = json.loads(claim_path.read_text())
    required = [claim_path, Path(claim['config']), Path(claim['source_result']),
                ROOT / f'protocol/prepare_muse_nvfp4_r2_{label.replace("-", "_")}_20261020.py',
                ROOT / f'protocol/run_muse_nvfp4_r2_{label.replace("-", "_")}_20261020.py']
    if label == 'fasttext-tmux':
        required.extend((Path(claim['preflight']), Path(claim['harness_tool_class']),
                         ROOT / 'protocol/preinstalled_tmux_isolated_docker.py',
                         ROOT / 'protocol/probe_muse_nvfp4_fasttext_tmux_20261020.py'))
    for suffix in ('start', 'exit'):
        marker = claim_path.with_name(f'r2-{label}-2902-20261020-{suffix}.json')
        if marker.exists() and marker.stat().st_mtime <= live_archive_started.timestamp():
            required.append(marker)
    missing_fasttext_files.extend(str(path.relative_to(BASE)) for path in required
                                  if str(path.relative_to(BASE)) not in entries)
    job = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4' / claim['job_name']
    for trial in job.glob('*'):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not finished_by_score_snapshot(result):
            continue
        if str(result.relative_to(BASE)) not in entries:
            missing_fasttext_results.append(trial.name)
        raw_dir = trial / 'agent/raw_responses'
        if any(raw_dir.glob('*.json')) and not any(
                path.startswith(str(raw_dir.relative_to(BASE)) + '/') for path in entries):
            missing_fasttext_raw.append(trial.name)
        trajectory = trial / 'agent/trajectory.json'
        if trajectory.exists() and str(trajectory.relative_to(BASE)) not in entries:
            missing_fasttext_trajectories.append(trial.name)

r3_state = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r3-infra-replacement-2900'
missing_r3_continuation_files = []
missing_r3_continuation_results = []
missing_r3_continuation_raw = []
missing_r3_continuation_trajectories = []
b07_path = r3_state / 'b07-2900-continuation.json'
if b07_path.exists():
    b07 = json.loads(b07_path.read_text())
    required = [b07_path, Path(b07['effective_config']),
                ROOT / 'protocol/continue_muse_nvfp4_r3_b07_2900_20261020.py']
    for suffix in ('started', 'exit'):
        marker = r3_state / f'b07-2900-{suffix}.json'
        if marker.exists() and marker.stat().st_mtime <= live_archive_started.timestamp():
            required.append(marker)
    missing_r3_continuation_files.extend(str(path.relative_to(BASE)) for path in required
                                         if str(path.relative_to(BASE)) not in entries)
expired_path = r3_state / 'expired2869-continuation-2900-claim.json'
if expired_path.exists():
    expired = json.loads(expired_path.read_text())
    required = [expired_path, Path(expired['config']), Path(expired['model_ready']),
                ROOT / 'protocol/continue_muse_nvfp4_r3_expired2869_2900_20261020.py']
    for suffix in ('start', 'exit'):
        marker = r3_state / f'expired2869-continuation-2900-{suffix}.json'
        if marker.exists() and marker.stat().st_mtime <= live_archive_started.timestamp():
            required.append(marker)
    for row in expired['tasks']:
        for raw in row['source_partial_raw']:
            required.append(Path(raw['path']))
    missing_r3_continuation_files.extend(str(path.relative_to(BASE)) for path in required
                                         if str(path.relative_to(BASE)) not in entries)
for job_name in ('muse-nvfp4-tb-v1-exact-r3-infra-replacement-2900-b07',
                 'muse-nvfp4-tb-v1-exact-r3-expired2869-continuation-2900-20261020'):
    job = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4' / job_name
    for trial in job.glob('*'):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not finished_by_score_snapshot(result):
            continue
        if str(result.relative_to(BASE)) not in entries:
            missing_r3_continuation_results.append(trial.name)
        raw_dir = trial / 'agent/raw_responses'
        if any(raw_dir.glob('*.json')) and not any(
                path.startswith(str(raw_dir.relative_to(BASE)) + '/') for path in entries):
            missing_r3_continuation_raw.append(trial.name)
        trajectory = trial / 'agent/trajectory.json'
        if trajectory.exists() and str(trajectory.relative_to(BASE)) not in entries:
            missing_r3_continuation_trajectories.append(trial.name)

remote_audit = json.loads((EVIDENCE / 'release-assets-verification.json').read_text())
verified_names = {item['asset'] for item in remote_audit['items'] if item.get('sha256_matches') and item.get('bytes_match')}
unverified = sorted(manifest['archive_name'] for manifest in manifests if manifest['archive_name'] not in verified_names)
errors = []
if missing_inputs:
    errors.append(f'{len(missing_inputs)} task input files missing')
if missing_results:
    errors.append(f'{len(missing_results)} scored result files missing')
if missing_raw:
    errors.append(f'{len(missing_raw)} scored raw-response sets missing')
if missing_trajectories:
    errors.append(f'{len(missing_trajectories)} scored trajectories missing')
if missing_handoff_files:
    errors.append(f'{len(missing_handoff_files)} replica handoff configs/receipt missing')
if missing_connection_files:
    errors.append(f'{len(missing_connection_files)} round-2 connection recovery inputs missing')
if missing_connection_results:
    errors.append(f'{len(missing_connection_results)} round-2 connection recovery results missing')
if missing_connection_raw:
    errors.append(f'{len(missing_connection_raw)} round-2 connection recovery raw-response sets missing')
if missing_connection_trajectories:
    errors.append(f'{len(missing_connection_trajectories)} round-2 connection recovery trajectories missing')
if missing_expiry_files:
    errors.append(f'{len(missing_expiry_files)} allocation-expiry correction inputs/proofs missing')
if missing_expiry_results:
    errors.append(f'{len(missing_expiry_results)} allocation-expiry correction results missing')
if missing_expiry_raw:
    errors.append(f'{len(missing_expiry_raw)} allocation-expiry correction raw-response sets missing')
if missing_expiry_trajectories:
    errors.append(f'{len(missing_expiry_trajectories)} allocation-expiry correction trajectories missing')
if missing_fasttext_files:
    errors.append(f'{len(missing_fasttext_files)} fasttext correction inputs/proofs missing')
if missing_fasttext_results:
    errors.append(f'{len(missing_fasttext_results)} fasttext correction results missing')
if missing_fasttext_raw:
    errors.append(f'{len(missing_fasttext_raw)} fasttext correction raw-response sets missing')
if missing_fasttext_trajectories:
    errors.append(f'{len(missing_fasttext_trajectories)} fasttext correction trajectories missing')
if missing_r3_continuation_files:
    errors.append(f'{len(missing_r3_continuation_files)} round-3 continuation inputs/proofs missing')
if missing_r3_continuation_results:
    errors.append(f'{len(missing_r3_continuation_results)} round-3 continuation results missing')
if missing_r3_continuation_raw:
    errors.append(f'{len(missing_r3_continuation_raw)} round-3 continuation raw-response sets missing')
if missing_r3_continuation_trajectories:
    errors.append(f'{len(missing_r3_continuation_trajectories)} round-3 continuation trajectories missing')
if unverified:
    errors.append(f'{len(unverified)} release assets not SHA/size verified')

record = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'live_archive_started_utc': live_archive_started.isoformat(),
    'score_generated_utc': score_generated.isoformat(),
    'deferred_post_score_snapshot_results': sorted(set(deferred_post_score_results)),
    'archives': [manifest['archive_name'] for manifest in manifests],
    'expected_inputs': 89,
    'covered_inputs': 89 - len(missing_inputs),
    'audited_scored_tasks': len(audit['tasks']),
    'covered_results': len(audit['tasks']) - len(missing_results),
    'covered_raw_response_sets': len(audit['tasks']) - len(missing_raw),
    'covered_trajectories': len(audit['tasks']) - len(missing_trajectories),
    'missing_inputs': missing_inputs,
    'missing_results': missing_results,
    'missing_raw_responses': missing_raw,
    'missing_trajectories': missing_trajectories,
    'missing_handoff_files': missing_handoff_files,
    'missing_connection_files': missing_connection_files,
    'missing_connection_results': missing_connection_results,
    'missing_connection_raw_responses': missing_connection_raw,
    'missing_connection_trajectories': missing_connection_trajectories,
    'missing_expiry_files': missing_expiry_files,
    'missing_expiry_results': missing_expiry_results,
    'missing_expiry_raw_responses': missing_expiry_raw,
    'missing_expiry_trajectories': missing_expiry_trajectories,
    'missing_fasttext_files': missing_fasttext_files,
    'missing_fasttext_results': missing_fasttext_results,
    'missing_fasttext_raw_responses': missing_fasttext_raw,
    'missing_fasttext_trajectories': missing_fasttext_trajectories,
    'missing_r3_continuation_files': missing_r3_continuation_files,
    'missing_r3_continuation_results': missing_r3_continuation_results,
    'missing_r3_continuation_raw_responses': missing_r3_continuation_raw,
    'missing_r3_continuation_trajectories': missing_r3_continuation_trajectories,
    'unverified_assets': unverified,
    'errors': errors,
    'qualification': 'complete_verified' if not errors and audit['qualification'] == 'complete_verified' else 'partial_or_needs_review',
}
(EVIDENCE / 'muse_nvfp4_exact_io_coverage.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('covered_inputs', 'covered_results', 'covered_raw_response_sets', 'covered_trajectories', 'errors', 'qualification')}))
