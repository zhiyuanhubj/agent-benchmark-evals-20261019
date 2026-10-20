#!/usr/bin/env python3
"""Declare one model draw after the previous correction failed before sampling."""

import copy
import hashlib
import json
import tomllib
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
OLD_CLAIM = STATE / 'r2-fasttext-expiry-2902-20261020-claim.json'
OLD_CONFIG = WORK / 'configs/r2-fasttext-expiry-2902-20261020.json'
OLD_JOB = 'muse-nvfp4-tb-v1-exact-r2-fasttext-expiry-2902-20261020'
NEW_JOB = 'muse-nvfp4-tb-v1-exact-r2-fasttext-tmux-2902-20261020'
NEW_CONFIG = WORK / 'configs/r2-fasttext-tmux-2902-20261020.json'
NEW_CLAIM = STATE / 'r2-fasttext-tmux-2902-20261020-claim.json'
PREFLIGHT = STATE / 'r2-fasttext-tmux-preflight-2919.json'
TOOL_CLASS = WORK / 'preinstalled_tmux_isolated_docker.py'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert not NEW_CONFIG.exists() and not NEW_CLAIM.exists()
    assert not (ROOT / 'results/muse_nvfp4' / NEW_JOB).exists()
    old_claim = read(OLD_CLAIM)
    assert old_claim['job_name'] == OLD_JOB and old_claim['task'] == 'train-fasttext'
    assert old_claim['config_sha256'] == sha(OLD_CONFIG)
    assert old_claim['source_raw_response_count'] == 325
    old = read(OLD_CONFIG)
    assert old['job_name'] == OLD_JOB and len(old['tasks']) == 1
    assert old['environment']['import_path'] == 'isolated_docker:IsolatedDocker'
    assert old['n_attempts'] == 1 and old['retry']['max_retries'] == 0
    task = Path(old['tasks'][0]['path'])
    assert task.name == 'train-fasttext'
    image = tomllib.loads((task / 'task.toml').read_text())['environment']['docker_image']
    assert image == 'alexgshaw/train-fasttext:20251031'

    old_results = list((ROOT / 'results/muse_nvfp4' / OLD_JOB).glob('train-fasttext__*/result.json'))
    assert len(old_results) == 1
    old_result_path = old_results[0]
    old_result = read(old_result_path)
    assert old_result['finished_at'] and old_result['exception_info']['exception_type'] == 'RuntimeError'
    assert old_result['exception_info']['exception_message'] == 'Failed to start tmux session. Error: None'
    assert ((old_result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
    assert not list((old_result_path.parent / 'agent/raw_responses').glob('*.json'))
    assert not (old_result_path.parent / 'agent/trajectory.json').exists()
    assert old_result['config']['agent']['kwargs']['api_base'] == old['agents'][0]['kwargs']['api_base']

    preflight = read(PREFLIGHT)
    assert preflight['cpu_allocation'] == 2919 and preflight['task_image'] == image
    assert preflight['returncode'] == 0 and preflight['model_requests'] == 0
    assert preflight['task_attempts'] == 0 and 'tmux 3.2a' in preflight['stdout']
    assert preflight['image_identity_proof_sha256'] == sha(Path(preflight['image_identity_proof']))
    assert len(preflight['mounts']) == 3 and all(row['read_only'] for row in preflight['mounts'])
    assert TOOL_CLASS.is_file()

    config = copy.deepcopy(old)
    config['job_name'] = NEW_JOB
    config['environment']['import_path'] = 'preinstalled_tmux_isolated_docker:PreinstalledTmuxIsolatedDocker'
    with NEW_CONFIG.open('x') as stream:
        json.dump(config, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    with NEW_CLAIM.open('x') as stream:
        json.dump({
            'prepared_utc': datetime.now(timezone.utc).isoformat(),
            'scope': 'One draw after a pre-model tmux startup failure; same official task image and model sampling',
            'task': task.name, 'round': 2, 'new_allocation': 2902,
            'job_name': NEW_JOB, 'config': str(NEW_CONFIG), 'config_sha256': sha(NEW_CONFIG),
            'source_claim': str(OLD_CLAIM), 'source_claim_sha256': sha(OLD_CLAIM),
            'source_config': str(OLD_CONFIG), 'source_config_sha256': sha(OLD_CONFIG),
            'source_result': str(old_result_path), 'source_result_sha256': sha(old_result_path),
            'preflight': str(PREFLIGHT), 'preflight_sha256': sha(PREFLIGHT),
            'harness_tool_class': str(TOOL_CLASS), 'harness_tool_class_sha256': sha(TOOL_CLASS),
            'task_image': image, 'task_image_id': preflight['task_image_id'],
            'task_toml_sha256': sha(task / 'task.toml'),
            'same_task_model_sampling_and_verifier': True,
            'only_environment_change': 'Read-only host tmux binary and its two libraries mounted into the pinned task image; isolated network remains unchanged',
            'pre_model_failure_preserved': True, 'original_partial_trajectory_preserved': True,
            'no_model_retry': True, 'no_best_of_selection': True,
            'counting_policy': 'Score only a native grade from this single new draw. Original 325-response expiry failure and the no-response tmux setup failure remain ungraded.',
        }, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'claim': str(NEW_CLAIM), 'config': str(NEW_CONFIG),
                      'source_pre_model_failure': str(old_result_path)}))


if __name__ == '__main__':
    main()
