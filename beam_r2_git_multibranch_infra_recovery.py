#!/usr/bin/env python3
"""One declared replacement for Beam TB2.1 r2's ungraded tmux failure.

The original six-response trial is retained. This controller waits until all
three original rounds have exited so the replacement cannot steal CPU capacity
from their first draws. It never selects an outcome based on its reward.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = SOURCE / 'beam'
STATE = WORK / 'state'
TRIAL = SOURCE / 'results/beam_bf16/beam-tb-v1-exact-r2/git-multibranch__46Fqx2D'
ENDPOINT = 'http://10.1.69.108:31328/v1'
JOB_NAME = 'beam-tb-v1-exact-r2-infra-replacement-git-multibranch'
CLAIM = STATE / 'r2-git-multibranch-infra-replacement-claim.json'
CONFIG = WORK / 'configs/r2-git-multibranch-infra-replacement.json'
EXIT = STATE / 'r2-git-multibranch-infra-replacement-exit.json'
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def source_proof():
    source = WORK / 'configs/r2-2887.json'
    frozen = WORK / 'configs/r2.json'
    original = read(source)
    frozen_config = read(frozen)
    assert len(original['tasks']) == len(frozen_config['tasks']) == 89
    assert original['retry']['max_retries'] == frozen_config['retry']['max_retries'] == 0
    assert original['n_attempts'] == frozen_config['n_attempts'] == 1
    assert original['agents'][0]['kwargs']['api_base'] == ENDPOINT
    normalized = copy.deepcopy(original)
    normalized['agents'][0]['kwargs']['api_base'] = frozen_config['agents'][0]['kwargs']['api_base']
    assert normalized == frozen_config, 'Effective round differs beyond the equivalent model endpoint'
    image_plan = read(SOURCE / 'allocation-2919/images-ready.json')
    assert image_plan['count'] == 89 and image_plan['all_archive_identities_verified']
    result_path = TRIAL / 'result.json'
    result = read(result_path)
    assert result.get('finished_at') and result['config']['task']['path'].endswith('/git-multibranch')
    assert result.get('verifier_result') is None
    exception = result.get('exception_info') or {}
    assert exception.get('exception_type') == 'RuntimeError'
    assert 'no server running on /tmp/tmux-0/default' in exception.get('exception_message', '')
    raw = sorted((TRIAL / 'agent/raw_responses').glob('*.json'))
    assert len(raw) == 6, 'The declared original six-response trial changed'
    assert all(read(path).get('model') == 'Beam-1.0-501B-A23B' for path in raw)
    assert (TRIAL / 'agent/trajectory.json').is_file()
    task = next(row for row in original['tasks'] if row['path'].endswith('/git-multibranch'))
    return {
        'source_result_sha256': sha(result_path),
        'source_trajectory_sha256': sha(TRIAL / 'agent/trajectory.json'),
        'source_raw_response_sha256': {path.name: sha(path) for path in raw},
        'source_config_sha256': sha(source),
        'frozen_config_sha256': sha(frozen),
        'image_ready_sha256': sha(SOURCE / 'allocation-2919/images-ready.json'),
        'task': task,
    }


def ready_to_launch():
    # Round 3 was reassigned to the verified 2901 replica, so the old
    # sequential controller never writes complete.json. Native exit receipts
    # and terminal results are the actual completion gate for all three draws.
    for round_number in (1, 2, 3):
        receipt = STATE / f'r{round_number}-exit.json'
        if not receipt.exists():
            return False
        assert read(receipt)['returncode'] == 0, f'Round {round_number} exited with an error'
        config = read(WORK / f'configs/r{round_number}.json')
        expected = {Path(row['path']).name for row in config['tasks']}
        assert len(expected) == 89
        results = SOURCE / 'results/beam_bf16' / config['job_name']
        found = {}
        for path in results.glob('*/result.json'):
            result = read(path)
            if not result.get('finished_at'):
                return False
            task = Path(result['config']['task']['path']).name
            assert task not in found, f'Duplicate round-{round_number} task: {task}'
            found[task] = path
        if len(found) < 89:
            return False
        assert set(found) == expected, f'Round {round_number} task inventory changed'
    return True


def launch(proof):
    assert not CLAIM.exists() and not CONFIG.exists() and not EXIT.exists()
    assert subprocess.check_output(['squeue', '-h', '-j', '2919', '-o', '%T'], text=True).strip() == 'RUNNING'
    assert subprocess.check_output(['squeue', '-h', '-j', '2887', '-o', '%T'], text=True).strip() == 'RUNNING'
    initial = read(BASE / '.private/beam_20261018/serve-launch.json')
    replica = read(BASE / '.private/beam_20261018/expanded_capacity_20261018/allocation-2887-rank-0/serving-conformance-ready.json')
    assert all(initial[key] == replica[key] for key in ('model', 'revision', 'precision', 'image_digest'))
    with urllib.request.urlopen(ENDPOINT + '/models', timeout=10) as response:
        assert any(row['id'] == 'Beam-1.0-501B-A23B' for row in json.load(response)['data'])

    effective = copy.deepcopy(read(WORK / 'configs/r2-2887.json'))
    effective['job_name'] = JOB_NAME
    effective['n_concurrent_trials'] = 1
    effective['tasks'] = [proof['task']]
    assert effective['n_attempts'] == 1 and effective['retry']['max_retries'] == 0
    create(CONFIG, effective)
    create(CLAIM, {
        'utc': time.time(), 'model': 'Beam-1.0-501B-A23B', 'precision': 'BF16',
        'profile': 'TB2.1 user-supplied exact images', 'round': 2,
        'reason': 'Original native trial had no verifier or reward after tmux server disappeared',
        'source_trial': str(TRIAL), 'source_proof': proof,
        'original_round_exit_sha256': {
            str(number): sha(STATE / f'r{number}-exit.json') for number in (1, 2, 3)
        },
        'original_round_terminal_tasks': {'1': 89, '2': 89, '3': 89},
        'replacement_job_name': JOB_NAME, 'replacement_config': str(CONFIG),
        'replacement_config_sha256': sha(CONFIG), 'endpoint': ENDPOINT,
        'model_allocation': 2887, 'cpu_allocation': 2919,
        'score_policy': 'Keep original trial ungraded; count at most this one declared infrastructure replacement, separately from raw first draw.',
        'resamples_after_replacement': 0,
    })
    env = dict(os.environ)
    env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.69.108',
               HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
               PYTHONPATH=str(BASE / 'bench/strict_four_models_20261008/sources/swe-pro/v2/tooling') + ':' +
               str(BASE / 'AgentCompass-official-baseline'))
    command = ['/usr/local/bin/srun', '--jobid=2919', '--overlap', '--gres=none',
               '-N1', '-n1', '-c8', '--immediate=10', PYTHON, str(WORK / 'harbor_entry.py'), str(CONFIG)]
    print(json.dumps({'phase': 'launch', 'command': command, 'claim': str(CLAIM)}), flush=True)
    result = subprocess.run(command, cwd=str(BASE / 'AgentCompass'), env=env)
    create(EXIT, {'utc': time.time(), 'returncode': result.returncode,
                  'replacement_result_dir': str(SOURCE / 'results/beam_bf16' / JOB_NAME)})
    assert result.returncode == 0, 'Replacement stopped; preserve artifacts and do not resample'


def main():
    proof = source_proof()
    if '--preflight' in sys.argv:
        print(json.dumps({'phase': 'preflight_passed', 'source_proof': proof}, ensure_ascii=False))
        return
    assert not CLAIM.exists(), 'Recovery is already claimed; no duplicate model draw'
    while not ready_to_launch():
        time.sleep(45)
    assert source_proof() == proof, 'Original trial changed while waiting'
    launch(proof)


if __name__ == '__main__':
    main()
