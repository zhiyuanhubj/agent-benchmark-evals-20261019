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


def add_result(task, path, source, claimed_reward=None):
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

for item in recovery:
    config_path = Path(item['path'])
    if sha256(config_path) != item['sha256']:
        errors.append(f'recovery config changed: {item["job_name"]}')
    config = read(config_path)
    if config['job_name'] != item['job_name'] or config['retry']['max_retries'] != 0 or config['n_attempts'] != 1:
        errors.append(f'recovery draw settings changed: {item["job_name"]}')
    if config['agents'][0]['kwargs']['api_base'] != plan['endpoint']:
        errors.append(f'recovery endpoint changed: {item["job_name"]}')
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
        add_result(task, result, 'infrastructure_recovery')

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
    'graded_agent_timeout_tasks': sorted(task for task, value in graded.items() if value['exception_type'] == 'AgentTimeoutError'),
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
