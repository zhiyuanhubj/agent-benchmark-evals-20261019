#!/usr/bin/env python3
"""Reconcile every Muse NVFP4 exact-image TB2.1 first-round task draw."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = SOURCE / 'muse_nvfp4'
RESULTS = SOURCE / 'results/muse_nvfp4'
OUT = Path(__file__).resolve().parent / 'evidence/muse_nvfp4_exact_round1_audit.json'


def read(path):
    return json.loads(path.read_text())


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


plan = read(WORK / 'state/completion-2866-plan.json')
expected = {}
for shard in (1, 2, 3):
    config = read(WORK / f'configs/r1-shard{shard}.json')
    for item in config['tasks']:
        task = Path(item['path']).name
        assert task not in expected
        expected[task] = str(Path(item['path']).relative_to(BASE))
assert len(expected) == 89

original = plan['existing_scored_results']['1']
recovery = [item for item in plan['configurations'] if item['round'] == 1]
assert len(original) == 11 and sum(len(item['tasks']) for item in recovery) == 78
assert set(original).isdisjoint({task for item in recovery for task in item['tasks']})
assert set(original) | {task for item in recovery for task in item['tasks']} == set(expected)

errors = []
rows = {}
active = []
ungraded = []


def add_result(task, path, source, claimed_reward=None, expected_endpoint=None):
    if task in rows:
        errors.append(f'duplicate terminal task: {task}')
        return
    value = read(path)
    actual = Path(value['config']['task']['path']).name
    if actual != task or task not in expected:
        errors.append(f'result task mismatch: {task}, {actual}')
    if not value.get('finished_at'):
        active.append(task)
        return
    actual_endpoint = value['config']['agent']['kwargs']['api_base']
    if expected_endpoint is not None and actual_endpoint != expected_endpoint:
        errors.append(f'result endpoint mismatch: {task}: {actual_endpoint}')
    reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    if claimed_reward is not None and reward != claimed_reward:
        errors.append(f'frozen original reward changed: {task}')
    raw_dir = path.parent / 'agent/raw_responses'
    raw_files = sorted(raw_dir.glob('*.json'))
    if not raw_files:
        errors.append(f'terminal task missing raw model responses: {task}')
    reasoning_count = 0
    for raw in raw_files:
        try:
            response = read(raw)
            choices = response.get('choices') or []
            if any((choice.get('message') or {}).get('reasoning_content') for choice in choices):
                reasoning_count += 1
        except (OSError, ValueError, TypeError) as exc:
            errors.append(f'invalid raw response for {task}: {raw.name}: {exc}')
    rows[task] = {
        'reward': reward,
        'exception_type': (value.get('exception_info') or {}).get('exception_type'),
        'source': source,
        'api_base': actual_endpoint,
        'result_path': str(path.relative_to(BASE)),
        'result_sha256': sha256(path),
        'finished_at': value['finished_at'],
        'raw_response_count': len(raw_files),
        'responses_with_reasoning_content': reasoning_count,
    }
    if reward not in (0, 1):
        ungraded.append(task)


for task, frozen in original.items():
    result = Path(frozen['result'])
    if not result.is_file():
        errors.append(f'frozen original result missing: {task}')
        continue
    if sha256(result) != frozen['sha256']:
        errors.append(f'frozen original result changed: {task}')
    add_result(task, result, 'original_exact_image_shard', frozen['reward'])

handoff_path = WORK / 'state/reassigned-2867/r1-b06-b07-handoff.json'
handoff = read(handoff_path) if handoff_path.exists() else None
handoff_batches = {row['job_name']: row for row in handoff['batches']} if handoff else {}
if handoff:
    expected_handoff_names = {f'muse-nvfp4-tb-v1-exact-r1-completion-2866-b{idx:02d}' for idx in (6, 7)}
    if set(handoff_batches) != expected_handoff_names or handoff['destination_allocation'] != 2867:
        errors.append('unexpected Muse replica handoff batches or allocation')

routes_extra = {}
for batch, lane in (('b03', 2), ('b05', 3)):
    receipt_path = WORK / f'state/extra_gpu/r1-{batch}-extra-route.json'
    if not receipt_path.exists():
        continue
    route = read(receipt_path)
    job_name = f'muse-nvfp4-tb-v1-exact-r1-completion-2866-{batch}'
    allocation = route.get('allocation')
    status_path = WORK / f'state/extra_gpu/{allocation}-ready.json'
    status = read(status_path) if status_path.exists() else {}
    if (route.get('batch') != batch or route.get('lane') != lane or
            allocation not in (2812, 2923, 2924, 2927, 2928) or route.get('job_name') != job_name or
            route.get('endpoint') != status.get('endpoint') or
            status.get('phase') != 'ready' or status.get('model') != 'muse-spark-open-nvfp4' or
            not route.get('sampling_profile_unchanged')):
        errors.append(f'invalid extra GPU route receipt: {batch}')
    if (WORK / f'state/extra_gpu/r1-{batch}-local-started.json').exists():
        errors.append(f'local and extra GPU route both claimed: {batch}')
    routes_extra[job_name] = {'receipt_path': str(receipt_path), **route}

for item in recovery:
    config_path = Path(item['path'])
    if sha256(config_path) != item['sha256']:
        errors.append(f'recovery config changed: {item["job_name"]}')
    config = read(config_path)
    if config['job_name'] != item['job_name'] or config['retry']['max_retries'] != 0 or config['n_attempts'] != 1:
        errors.append(f'recovery draw settings changed: {item["job_name"]}')
    if config['agents'][0]['kwargs']['api_base'] != plan['endpoint']:
        errors.append(f'recovery endpoint changed: {item["job_name"]}')
    effective_endpoint = plan['endpoint']
    if item['job_name'] in handoff_batches:
        moved = handoff_batches[item['job_name']]
        effective_path = Path(moved['effective_config'])
        if moved['original_sha256'] != item['sha256'] or moved['tasks'] != item['tasks']:
            errors.append(f'handoff source mismatch: {item["job_name"]}')
        if not effective_path.is_file() or sha256(effective_path) != moved['effective_sha256']:
            errors.append(f'handoff effective config mismatch: {item["job_name"]}')
        else:
            effective_config = read(effective_path)
            expected_config = json.loads(json.dumps(config))
            expected_config['agents'][0]['kwargs']['api_base'] = handoff['endpoint']
            expected_config['n_concurrent_trials'] = 3
            if effective_config != expected_config:
                errors.append(f'handoff changed benchmark profile: {item["job_name"]}')
        effective_endpoint = handoff['endpoint']
    if item['job_name'] in routes_extra:
        if item['job_name'] in handoff_batches:
            errors.append(f'two replica routes claim batch: {item["job_name"]}')
        moved = routes_extra[item['job_name']]
        effective_path = Path(moved['effective_config'])
        if (moved['original_config'] != str(config_path) or moved['original_sha256'] != item['sha256']
                or moved['tasks'] != item['tasks']):
            errors.append(f'extra GPU route source mismatch: {item["job_name"]}')
        if not effective_path.is_file() or sha256(effective_path) != moved['effective_sha256']:
            errors.append(f'extra GPU route effective config mismatch: {item["job_name"]}')
        else:
            expected_config = json.loads(json.dumps(config))
            expected_config['agents'][0]['kwargs']['api_base'] = moved['endpoint']
            if read(effective_path) != expected_config:
                errors.append(f'extra GPU route changed benchmark profile: {item["job_name"]}')
        effective_endpoint = moved['endpoint']
    allowed = set(item['tasks'])
    seen = set()
    job_dir = RESULTS / item['job_name']
    for trial in job_dir.glob('*'):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not result.exists():
            active.append(trial.name)
            continue
        value = read(result)
        task = Path(value['config']['task']['path']).name
        if task not in allowed or task in seen:
            errors.append(f'unexpected or duplicate recovery task: {item["job_name"]}: {task}')
            continue
        seen.add(task)
        add_result(task, result, 'infrastructure_recovery', expected_endpoint=effective_endpoint)

for interrupted in plan['user_cutover_interrupted_ungraded_trials'].values():
    result = Path(interrupted['trial']) / 'result.json'
    if result.exists():
        value = read(result)
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        if value.get('finished_at') and reward in (0, 1):
            errors.append(f'cutover trial unexpectedly graded: {result}')

graded = {task: value for task, value in rows.items() if value['reward'] in (0, 1)}
missing = sorted(set(expected) - set(graded))
audit = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'profile': plan['profile'],
    'model': plan['model'],
    'expected_task_count': 89,
    'graded_task_count': len(graded),
    'success_count': sum(value['reward'] == 1 for value in graded.values()),
    'scored_raw_response_count': sum(value['raw_response_count'] for value in graded.values()),
    'scored_nonempty_reasoning_response_count': sum(value['responses_with_reasoning_content'] for value in graded.values()),
    'graded_agent_timeout_tasks': sorted(task for task, value in graded.items() if value['exception_type'] == 'AgentTimeoutError'),
    'replica_handoff': handoff,
    'opportunistic_routes_extra_gpu': list(routes_extra.values()),
    'ungraded_terminal_tasks': sorted(set(ungraded)),
    'missing_graded_tasks': missing,
    'active_or_unfinished_trials': sorted(active),
    'errors': errors,
    'qualification': 'complete_verified' if len(graded) == 89 and not errors and not ungraded else 'partial_or_needs_review',
    'score': sum(value['reward'] == 1 for value in graded.values()) / 89 if len(graded) == 89 and not errors and not ungraded else None,
    'reasoning_note': 'Counts nonempty reasoning_content in preserved raw API responses; this does not certify that a trajectory is free of reward hacking.',
    'tasks': {task: rows[task] for task in sorted(rows)},
}
OUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: audit[key] for key in ('graded_task_count', 'success_count', 'qualification', 'errors')}))
