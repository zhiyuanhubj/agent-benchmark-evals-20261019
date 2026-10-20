#!/usr/bin/env python3
"""Declare a single infrastructure correction for the ungraded TB2.1 task."""

import copy
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
OLD = WORK / 'configs/r2-completion-2866-b08-routed-2867.json'
ROUTE = STATE / 'future-routes/r2-completion-2866-b08-route.json'
OLD_JOB = 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b08'
NEW_JOB = 'muse-nvfp4-tb-v1-exact-r2-fasttext-expiry-2902-20261020'
NEW = WORK / 'configs/r2-fasttext-expiry-2902-20261020.json'
CLAIM = STATE / 'r2-fasttext-expiry-2902-20261020-claim.json'
READY = STATE / 'replicas-extra-20261020/2902/endpoint-ready.json'
PREFLIGHT = READY.with_name('reasoning-preflight.json')
IMAGES = ROOT / 'allocation-2919/images-ready.json'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not NEW.exists() and not CLAIM.exists()
    assert not (ROOT / 'results/muse_nvfp4' / NEW_JOB).exists()
    expired = subprocess.check_output(
        ['sacct', '-n', '-P', '-j', '2867', '--format=JobIDRaw,State,Start,End'],
        text=True).splitlines()[0].split('|')
    assert expired[0] == '2867' and expired[1] == 'TIMEOUT'
    expiry = datetime.fromisoformat(expired[3]).replace(tzinfo=timezone.utc)
    assert expired[3].startswith('2026-10-20T15:10:')
    assert subprocess.check_output(['squeue', '-h', '-j', '2902', '-o', '%T'],
                                   text=True).strip() == 'RUNNING'
    route = read(ROUTE)
    assert route['job_name'] == OLD_JOB and route['allocation'] == 2867
    assert route['effective_config'] == str(OLD)
    assert route['effective_sha256'] == sha(OLD)
    old = read(OLD)
    assert old['job_name'] == OLD_JOB and old['n_attempts'] == 1
    assert old['retry']['max_retries'] == 0
    assert old['agents'][0]['kwargs']['api_base'] == 'http://10.1.105.182:31321/v1'
    selected = [task for task in old['tasks'] if Path(task['path']).name == 'train-fasttext']
    assert len(selected) == 1
    task_path = Path(selected[0]['path'])
    assert task_path.is_dir() and (task_path / 'task.toml').is_file()
    trials = list((ROOT / 'results/muse_nvfp4' / OLD_JOB).glob('train-fasttext__*/result.json'))
    assert len(trials) == 1
    original_path = trials[0]
    original = read(original_path)
    assert original['finished_at'] and Path(original['config']['task']['path']) == task_path
    assert original['config']['agent']['kwargs']['api_base'] == old['agents'][0]['kwargs']['api_base']
    assert ((original.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
    failure = original['exception_info']
    assert failure['exception_type'] == 'ContextAccountingError'
    assert failure['exception_message'] == 'Authoritative model token counting failed'
    assert 'Connection refused' in failure['exception_traceback']
    assert datetime.fromisoformat(original['finished_at'].replace('Z', '+00:00')) > expiry
    raw = sorted((original_path.parent / 'agent/raw_responses').glob('*.json'))
    assert raw and max(path.stat().st_mtime for path in raw) < expiry.timestamp()
    raw_manifest_hash = hashlib.sha256()
    for path in raw:
        raw_manifest_hash.update(path.name.encode() + b'\0' + sha(path).encode() + b'\n')

    ready, preflight = read(READY), read(PREFLIGHT)
    assert ready['allocation'] == preflight['allocation'] == 2902
    assert ready['precision'] == 'NVFP4' and ready['model'] == 'muse-spark-open-nvfp4'
    assert ready['api_base'] == old['agents'][0]['kwargs']['api_base']
    assert preflight['nonempty_reasoning_content']
    assert preflight['response']['choices'][0]['message']['reasoning_content'].strip()
    assert ready['utc'] > expiry.timestamp()
    assert read(IMAGES)['all_archive_identities_verified']

    config = copy.deepcopy(old)
    config['job_name'] = NEW_JOB
    config['tasks'] = selected
    with NEW.open('x') as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    with CLAIM.open('x') as stream:
        json.dump({
            'prepared_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'One infrastructure correction for train-fasttext after old endpoint expired during authoritative token counting',
            'round': 2, 'task': 'train-fasttext', 'old_allocation': 2867,
            'old_allocation_sacct': expired, 'new_allocation': 2902,
            'job_name': NEW_JOB, 'config': str(NEW), 'config_sha256': sha(NEW),
            'source_job': OLD_JOB, 'source_config': str(OLD),
            'source_config_sha256': sha(OLD), 'route': str(ROUTE), 'route_sha256': sha(ROUTE),
            'source_result': str(original_path), 'source_result_sha256': sha(original_path),
            'source_trajectory_sha256': sha(original_path.parent / 'agent/trajectory.json'),
            'source_raw_response_count': len(raw),
            'source_raw_responses_manifest_sha256': raw_manifest_hash.hexdigest(),
            'task_toml_sha256': sha(task_path / 'task.toml'),
            'new_endpoint_ready': str(READY), 'new_endpoint_ready_sha256': sha(READY),
            'new_reasoning_preflight': str(PREFLIGHT),
            'new_reasoning_preflight_sha256': sha(PREFLIGHT),
            'image_proof': str(IMAGES), 'image_proof_sha256': sha(IMAGES),
            'same_task_and_sampling_settings': True, 'no_model_retry': True,
            'old_partial_model_trajectory_preserved': True, 'no_best_of_selection': True,
            'counting_policy': 'Count only a native grade from this single correction; preserve the 325-response original as an ungraded infrastructure interruption.',
        }, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'claim': str(CLAIM), 'config': str(NEW),
                      'source_raw_responses': len(raw)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
