#!/usr/bin/env python3
"""Run untouched Beam exact-image TB rounds 2/3 on the verified 2887 replica.

Round 1 remains owned by the original controller. Creating r2-launch.json makes
that controller stop after round 1 rather than draw round 2 a second time.
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
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'beam'
STATE = WORK / 'state'
ENDPOINT = 'http://10.1.69.108:31328/v1'
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
HARNESS = WORK / 'harbor_entry.py'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def preflight():
    assert subprocess.check_output(['squeue', '-h', '-j', '2887', '-o', '%T'], text=True).strip() == 'RUNNING'
    assert subprocess.check_output(['squeue', '-h', '-j', '2919', '-o', '%T'], text=True).strip() == 'RUNNING'
    assert read(ROOT / 'allocation-2919/images-ready.json')['all_archive_identities_verified']
    assert read(ROOT / 'allocation-2919/images-ready.json')['count'] == 89
    initial = read(BASE / '.private/beam_20261018/serve-launch.json')
    replica = read(BASE / '.private/beam_20261018/expanded_capacity_20261018/allocation-2887-rank-0/serving-conformance-ready.json')
    for key in ('model', 'revision', 'precision', 'image_digest'):
        assert initial[key] == replica[key], (key, initial[key], replica[key])
    assert replica['api_base'] == ENDPOINT
    with urllib.request.urlopen(ENDPOINT + '/models', timeout=10) as response:
        models = json.load(response)['data']
    assert any(model['id'] == 'Beam-1.0-501B-A23B' for model in models)
    first = read(WORK / 'configs/r1.json')
    for number in (2, 3):
        original = read(WORK / 'configs' / f'r{number}.json')
        assert len(original['tasks']) == len(first['tasks']) == 89
        assert original['retry']['max_retries'] == first['retry']['max_retries'] == 0
        assert original['n_concurrent_trials'] == first['n_concurrent_trials'] == 4
        assert original['agents'][0]['kwargs']['api_base'] == first['agents'][0]['kwargs']['api_base']
        assert original['agents'][0]['kwargs']['api_base'] == 'http://10.1.25.253:31328/v1'
        comparison = copy.deepcopy(original)
        comparison['job_name'] = first['job_name']
        assert comparison == first, f'Round {number} differs from the frozen round-1 protocol'
        assert not (STATE / f'r{number}-launch.json').exists(), f'Round {number} already claimed'
        assert not (ROOT / 'results/beam_bf16' / original['job_name']).exists(), f'Round {number} has native trials'
    return {'source_model': {key: initial[key] for key in ('model', 'revision', 'precision', 'image_digest')},
            'replica': ENDPOINT,
            'original_config_sha256': {str(number): digest(WORK / 'configs' / f'r{number}.json') for number in (2, 3)},
            'round_1_claim_sha256': digest(STATE / 'r1-launch.json'),
            'images_ready_sha256': digest(ROOT / 'allocation-2919/images-ready.json')}


def run_round(number, proof):
    original_path = WORK / 'configs' / f'r{number}.json'
    original = read(original_path)
    modified = copy.deepcopy(original)
    modified['agents'][0]['kwargs']['api_base'] = ENDPOINT
    assert {k: modified[k] for k in modified if k != 'agents'} == {k: original[k] for k in original if k != 'agents'}
    assert len(modified['agents']) == 1
    config_path = WORK / 'configs' / f'r{number}-2887.json'
    write_new(config_path, modified)
    claim = STATE / f'r{number}-launch.json'
    write_new(claim, {'utc': time.time(), 'round': number, 'owner': 'beam_exact_parallel_r23_2887.py',
                      'model_allocation': 2887, 'cpu_allocation': 2919, 'endpoint': ENDPOINT,
                      'source_config': str(original_path), 'source_config_sha256': proof['original_config_sha256'][str(number)],
                      'effective_config': str(config_path), 'effective_config_sha256': digest(config_path),
                      'only_protocol_change': 'Equivalent BF16 model replica endpoint; task and agent settings unchanged',
                      'no_retry': True})
    print(f'round {number} claimed, native Harbor start', flush=True)
    env = dict(os.environ)
    env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.69.108',
               HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
               PYTHONPATH=str(BASE / 'bench/strict_four_models_20261008/sources/swe-pro/v2/tooling') + ':' +
               str(BASE / 'AgentCompass-official-baseline'))
    result = subprocess.run([PYTHON, str(HARNESS), str(config_path)], env=env,
                            cwd=str(BASE / 'AgentCompass'))
    write_new(STATE / f'r{number}-exit.json', {'utc': time.time(), 'returncode': result.returncode,
                                               'owner': 'beam_exact_parallel_r23_2887.py'})
    assert result.returncode == 0, f'Round {number} stopped; preserve attempts for audit'
    print(f'round {number} native Harbor process exited successfully', flush=True)


def main():
    proof = preflight()
    print(json.dumps({'preflight': proof}, ensure_ascii=False), flush=True)
    if '--preflight' in sys.argv:
        return
    assert os.environ.get('SLURM_JOB_ID') == '2919', 'Run on the prepared CPU allocation'
    write_new(STATE / 'r23-2887-handoff.json', {'utc': time.time(), 'proof': proof,
              'owner': 'beam_exact_parallel_r23_2887.py', 'rounds': [2, 3],
              'round_1_remains_owned_by_original_controller': True,
              'round_2_claim_blocks_original_duplicate_after_round_1': True})
    run_round(2, proof)
    while not (STATE / 'r1-exit.json').exists():
        time.sleep(30)
    assert read(STATE / 'r1-exit.json')['returncode'] == 0, 'Round 1 needs reconciliation before round 3'
    run_round(3, proof)
    write_new(STATE / 'complete.json', {'utc': time.time(), 'rounds': 3,
                                       'fourth_round_scheduled': False,
                                       'rounds_2_3_owner': 'beam_exact_parallel_r23_2887.py'})


if __name__ == '__main__':
    main()
