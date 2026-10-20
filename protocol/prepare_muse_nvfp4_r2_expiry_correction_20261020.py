#!/usr/bin/env python3
"""Declare one TB2.1 infrastructure correction after allocation 2867 expired."""

import copy
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'muse_nvfp4'
OLD_JOB = 'muse-nvfp4-tb-v1-exact-r2-connection-recovery-20261020'
NEW_JOB = 'muse-nvfp4-tb-v1-exact-r2-expiry-correction-2902-20261020'
OLD_CONFIG = WORK / 'configs/r2-connection-recovery-20261020.json'
OLD_CLAIM = WORK / 'state/r2-connection-recovery-20261020-claim.json'
OLD_RESULTS = ROOT / 'results/muse_nvfp4' / OLD_JOB
NEW_CONFIG = WORK / 'configs/r2-expiry-correction-2902-20261020.json'
NEW_CLAIM = WORK / 'state/r2-expiry-correction-2902-20261020-claim.json'
NEW_RESULTS = ROOT / 'results/muse_nvfp4' / NEW_JOB
NEW_READY = WORK / 'state/replicas-extra-20261020/2902/endpoint-ready.json'
NEW_PREFLIGHT = NEW_READY.with_name('reasoning-preflight.json')
IMAGES = ROOT / 'allocation-2919/images-ready.json'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reward(value):
    return ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')


assert not NEW_CONFIG.exists() and not NEW_CLAIM.exists() and not NEW_RESULTS.exists()
assert subprocess.check_output(['squeue', '-h', '-j', '2902', '-o', '%T'], text=True).strip() == 'RUNNING'
expired = subprocess.check_output(
    ['sacct', '-n', '-P', '-j', '2867', '--format=JobIDRaw,State,Start,End'], text=True,
).splitlines()[0].split('|')
assert expired[0] == '2867' and expired[1] == 'TIMEOUT' and expired[3].startswith('2026-10-20T15:10:')
expiry_time = datetime.fromisoformat(expired[3]).replace(tzinfo=timezone.utc)

old_claim, old_config = read(OLD_CLAIM), read(OLD_CONFIG)
assert old_claim['job_name'] == old_config['job_name'] == OLD_JOB
assert old_claim['config_sha256'] == digest(OLD_CONFIG)
assert old_claim['ready_proof_sha256'] == digest(Path(old_claim['ready_proof']))
assert old_claim['image_proof_sha256'] == digest(IMAGES)
assert len(old_claim['origins']) == len(old_config['tasks']) == 10
assert old_config['retry']['max_retries'] == 0 and old_config['n_attempts'] == 1
assert old_config['n_concurrent_trials'] == 2
assert read(IMAGES)['all_archive_identities_verified']

ready, preflight = read(NEW_READY), read(NEW_PREFLIGHT)
assert ready['allocation'] == preflight['allocation'] == 2902
assert ready['precision'] == 'NVFP4' and ready['model'] == 'muse-spark-open-nvfp4'
assert ready['api_base'] == old_config['agents'][0]['kwargs']['api_base']
assert preflight['nonempty_reasoning_content'] is True
assert Path(preflight['endpoint_ready']) == NEW_READY
assert preflight['response']['choices'][0]['message']['reasoning_content'].strip()
assert preflight['request']['chat_template_kwargs']['reasoning_effort'] == 'xhigh'
assert ready['utc'] > expiry_time.timestamp()

origins = {row['task']: row for row in old_claim['origins']}
assert len(origins) == 10
assert {Path(item['path']).name for item in old_config['tasks']} == set(origins)
trial_dirs = [path for path in OLD_RESULTS.iterdir() if path.is_dir()]
assert all(any(path.name.startswith(name + '__') for name in origins) for path in trial_dirs)
assert len(trial_dirs) == 6, 'Unexpected old trial count; reconcile before correcting'

rows = []
for task in old_config['tasks']:
    name = Path(task['path']).name
    origin = origins[name]
    assert digest(Path(origin['original_result'])) == origin['original_result_sha256']
    assert digest(Path(task['path']) / 'task.toml') == origin['task_toml_sha256']
    matched = [path for path in trial_dirs if path.name.startswith(name + '__')]
    assert len(matched) <= 1
    row = {'task': name, 'source_original_result': origin['original_result'],
           'source_original_result_sha256': origin['original_result_sha256'],
           'previous_recovery_trial': str(matched[0]) if matched else None}
    if not matched:
        row['previous_recovery_state'] = 'never_started'
    else:
        trial = matched[0]
        result_path = trial / 'result.json'
        responses = sorted((trial / 'agent/raw_responses').glob('*.json'))
        row['previous_recovery_raw_response_count'] = len(responses)
        if result_path.exists():
            value = read(result_path)
            exception = value.get('exception_info') or {}
            assert value['finished_at'] and reward(value) is None
            assert exception.get('exception_type') == 'InternalServerError'
            assert 'Connection error' in exception.get('exception_message', '')
            assert value['config']['agent']['kwargs']['api_base'] == ready['api_base']
            assert datetime.fromisoformat(value['finished_at'].replace('Z', '+00:00')) > expiry_time
            row.update(previous_recovery_state='ungraded_connection_after_allocation_expiry',
                       previous_recovery_result=str(result_path),
                       previous_recovery_result_sha256=digest(result_path),
                       previous_recovery_exception=exception['exception_type'])
        else:
            assert len(responses) == 0, 'Interrupted trial has model replies; audit before correction'
            row['previous_recovery_state'] = 'interrupted_without_model_reply'
    rows.append(row)

assert [row['previous_recovery_state'] for row in rows].count('ungraded_connection_after_allocation_expiry') == 4
assert [row['previous_recovery_state'] for row in rows].count('interrupted_without_model_reply') == 2
assert [row['previous_recovery_state'] for row in rows].count('never_started') == 4

effective = copy.deepcopy(old_config)
effective['job_name'] = NEW_JOB
with NEW_CONFIG.open('x') as stream:
    json.dump(effective, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
with NEW_CLAIM.open('x') as stream:
    json.dump({
        'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'One infrastructure correction per ungraded or unstarted TB2.1 round-2 task after allocation 2867 timed out',
        'old_allocation': 2867, 'old_allocation_sacct': expired, 'new_allocation': 2902,
        'same_physical_ip_reallocated': True,
        'job_name': NEW_JOB, 'config': str(NEW_CONFIG), 'config_sha256': digest(NEW_CONFIG),
        'source_job_name': OLD_JOB, 'source_config': str(OLD_CONFIG),
        'source_config_sha256': digest(OLD_CONFIG), 'source_claim': str(OLD_CLAIM),
        'source_claim_sha256': digest(OLD_CLAIM), 'new_endpoint_ready': str(NEW_READY),
        'new_endpoint_ready_sha256': digest(NEW_READY), 'new_reasoning_preflight': str(NEW_PREFLIGHT),
        'new_reasoning_preflight_sha256': digest(NEW_PREFLIGHT),
        'image_proof': str(IMAGES), 'image_proof_sha256': digest(IMAGES),
        'same_tasks_and_sampling_settings': True, 'no_model_retry': True,
        'old_results_preserved': True, 'no_best_of_selection': True,
        'counting_policy': 'For each task, count only the first native grade from the declared correction. Old ungraded infrastructure failures remain archived and are never scored as model failures.',
        'tasks': rows,
    }, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({'claim': str(NEW_CLAIM), 'config': str(NEW_CONFIG),
                  'tasks': len(rows), 'new_allocation': 2902}, ensure_ascii=False))
