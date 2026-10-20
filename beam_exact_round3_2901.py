#!/usr/bin/env python3
"""Start untouched Beam exact-image TB round 3 on the verified 2901 replica.

The active 2887 controller owns round 2. The exclusive r3-launch receipt stops
it from drawing round 3 a second time when round 2 eventually ends.
"""

import copy
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'beam'
STATE = WORK / 'state'
REPLICA = BASE / '.private/beam_20261018/expanded_capacity_20261018/allocation-2901-rank-0'
ENDPOINT = 'http://10.1.95.27:31328/v1'
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
SOURCE = WORK / 'configs/r3.json'
EFFECTIVE = WORK / 'configs/r3-2901.json'
CLAIM = STATE / 'r3-launch.json'
EXIT = STATE / 'r3-exit.json'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open('x') as out:
        json.dump(value, out, indent=2)
        out.write('\n')


def running(job):
    return subprocess.check_output(['squeue', '-h', '-j', str(job), '-o', '%T'],
                                   text=True).strip() == 'RUNNING'


def preflight():
    assert running(2901) and running(2919), 'Model or prepared CPU allocation ended'
    assert read(ROOT / 'allocation-2919/images-ready.json')['count'] == 89
    assert read(ROOT / 'allocation-2919/images-ready.json')['all_archive_identities_verified']
    assert read(STATE / 'r1-exit.json')['returncode'] == 0
    initial = read(BASE / '.private/beam_20261018/serve-launch.json')
    replica = read(REPLICA / 'serving-conformance-ready.json')
    for key in ('model', 'revision', 'precision', 'image_digest'):
        assert initial[key] == replica[key], (key, initial[key], replica[key])
    assert replica['api_base'] == ENDPOINT
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=10) as response:
        assert any(model['id'] == 'Beam-1.0-501B-A23B'
                   for model in json.load(response)['data'])
    first = read(WORK / 'configs/r1.json')
    original = read(SOURCE)
    assert len(first['tasks']) == len(original['tasks']) == 89
    assert original['retry']['max_retries'] == first['retry']['max_retries'] == 0
    assert original['n_concurrent_trials'] == first['n_concurrent_trials'] == 4
    comparison = copy.deepcopy(original)
    comparison['job_name'] = first['job_name']
    assert comparison == first, 'Round 3 differs from the frozen round-1 protocol'
    assert original['agents'][0]['kwargs']['api_base'] == 'http://10.1.25.253:31328/v1'
    assert not (ROOT / 'results/beam_bf16' / original['job_name']).exists(), 'Native round 3 already started'
    assert not CLAIM.exists(), 'Round 3 already has an owner'
    return original, replica


def main():
    while not (REPLICA / 'serving-conformance-ready.json').exists():
        if CLAIM.exists():
            raise RuntimeError('Another controller claimed round 3 during conformance')
        assert subprocess.run(['systemctl', '--user', 'is-failed',
                               'beam-reserve-serving-2901-20261018.service'],
                              stdout=subprocess.DEVNULL).returncode != 0, 'Replica failed conformance or startup'
        assert running(2901), 'Model allocation ended before conformance'
        time.sleep(30)
    original, replica = preflight()
    modified = copy.deepcopy(original)
    modified['agents'][0]['kwargs']['api_base'] = ENDPOINT
    assert {key: modified[key] for key in modified if key != 'agents'} == {
        key: original[key] for key in original if key != 'agents'}
    write_new(EFFECTIVE, modified)
    write_new(CLAIM, {
        'utc': time.time(), 'round': 3, 'owner': 'beam_exact_round3_2901.py',
        'model_allocation': 2901, 'cpu_allocation': 2919, 'endpoint': ENDPOINT,
        'source_config': str(SOURCE), 'source_config_sha256': sha(SOURCE),
        'effective_config': str(EFFECTIVE), 'effective_config_sha256': sha(EFFECTIVE),
        'replica_ready_sha256': sha(REPLICA / 'serving-conformance-ready.json'),
        'replica_revision': replica['revision'],
        'only_protocol_change': 'Equivalent pinned Beam BF16 endpoint; tasks, images, generation and concurrency unchanged',
        'no_retry': True,
        'existing_round_2_owner': 'beam_exact_parallel_r23_2887.py',
        'duplicate_prevention': 'Exclusive r3-launch.json blocks the 2887 owner from starting round 3',
    })
    env = dict(os.environ)
    env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.95.27',
               HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
               PYTHONPATH=str(BASE / 'bench/strict_four_models_20261008/sources/swe-pro/v2/tooling')
               + ':' + str(BASE / 'AgentCompass-official-baseline'))
    command = ['/usr/local/bin/srun', '--jobid=2919', '--overlap', '--gres=none',
               '-N1', '-n1', '-c8', '--immediate=10', PYTHON,
               str(WORK / 'harbor_entry.py'), str(EFFECTIVE)]
    result = subprocess.run(command, env=env, cwd=BASE / 'AgentCompass')
    write_new(EXIT, {'utc': time.time(), 'returncode': result.returncode,
                     'owner': 'beam_exact_round3_2901.py'})
    assert result.returncode == 0, 'Round 3 stopped; preserve native attempts for audit'


if __name__ == '__main__':
    main()
