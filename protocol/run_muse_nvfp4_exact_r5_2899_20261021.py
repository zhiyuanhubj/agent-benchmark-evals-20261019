#!/usr/bin/env python3
"""Prepare and run one independent Muse NVFP4 exact-image TB2.1 round."""

import copy
import fcntl
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
WORK = SOURCE / 'muse_nvfp4'
STATE = WORK / 'state/r5-2899-20261021'
CONFIG = WORK / 'configs/r5-2899-20261021.json'
READY = WORK / 'state/replicas-extra-20261020/2899/endpoint-ready.json'
PREFLIGHT = WORK / 'state/replicas-extra-20261020/2899/reasoning-preflight.json'
JOB = 'muse-nvfp4-tb-v1-exact-r5-2899-20261021'
RESULTS = SOURCE / 'results/muse_nvfp4' / JOB
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def prepare():
    assert not CONFIG.exists() and not (STATE / 'claim.json').exists()
    assert not RESULTS.exists(), 'Round 5 already has native attempts'
    proof = json.loads(READY.read_text())
    preflight = json.loads(PREFLIGHT.read_text())
    assert proof['allocation'] == 2899 and proof['precision'] == 'NVFP4'
    assert proof['model'] == 'muse-spark-open-nvfp4'
    assert proof['api_base'] == 'http://10.1.114.210:31321/v1'
    assert preflight['allocation'] == 2899 and preflight['nonempty_reasoning_content']
    assert preflight['response']['choices'][0]['message']['reasoning_content'].strip()
    reference = json.loads((WORK / 'state/replica-2900/endpoint-ready.json').read_text())
    assert proof['source_deployment_sha256'] == reference['source_deployment_sha256']

    sources = [WORK / f'configs/r1-shard{i}.json' for i in (1, 2, 3)]
    configs = [json.loads(path.read_text()) for path in sources]
    common = []
    for config in configs:
        item = copy.deepcopy(config)
        item.pop('job_name')
        item.pop('tasks')
        item.pop('n_concurrent_trials')
        item['agents'][0]['kwargs'].pop('api_base')
        common.append(item)
    assert common[0] == common[1] == common[2], 'Source shards differ in benchmark settings'
    tasks = [task for config in configs for task in config['tasks']]
    names = [Path(task['path']).name for task in tasks]
    assert len(tasks) == len(set(names)) == 89
    task_hashes = {}
    for task in tasks:
        task_path = Path(task['path']) / 'task.toml'
        assert task_path.is_file()
        task_hashes[Path(task['path']).name] = sha(task_path)

    config = copy.deepcopy(configs[0])
    config['job_name'] = JOB
    config['n_concurrent_trials'] = 2
    config['agents'][0]['kwargs']['api_base'] = proof['api_base']
    config['tasks'] = tasks
    assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
    STATE.mkdir(parents=True, exist_ok=False)
    write_once(CONFIG, config)
    write_once(STATE / 'claim.json', {
        'prepared_utc': time.time(), 'round': 5, 'expected': 89,
        'policy': 'Independent fifth draw on the same 89 supplied TB2.1 image identities; '
                  'one native attempt per task, no correctness-based retry.',
        'allocation': 2899, 'model': proof['model'], 'precision': proof['precision'],
        'api_base': proof['api_base'], 'job_name': JOB,
        'config': str(CONFIG), 'config_sha256': sha(CONFIG),
        'source_configs': [{'path': str(path), 'sha256': sha(path)} for path in sources],
        'task_toml_sha256': task_hashes,
        'endpoint_ready': str(READY), 'endpoint_ready_sha256': sha(READY),
        'reasoning_preflight': str(PREFLIGHT), 'reasoning_preflight_sha256': sha(PREFLIGHT),
        'runner': str(Path(__file__)), 'runner_sha256': sha(Path(__file__)),
        'generation_qualification': 'Same pinned exact-image task paths, agent and generation settings '
                                    'as round 1, except the independently declared endpoint and concurrency.',
    })
    print(json.dumps({'job_name': JOB, 'expected': 89, 'config_sha256': sha(CONFIG)}))


def run():
    assert os.environ.get('SLURM_JOB_ID') == '2899'
    claim_path = STATE / 'claim.json'
    claim = json.loads(claim_path.read_text())
    assert claim['job_name'] == JOB and claim['config_sha256'] == sha(CONFIG)
    assert claim['endpoint_ready_sha256'] == sha(READY)
    assert claim['reasoning_preflight_sha256'] == sha(PREFLIGHT)
    assert claim['runner_sha256'] == sha(Path(__file__))
    assert not RESULTS.exists(), 'Do not restart a partially sampled native round'
    endpoint = json.loads(READY.read_text())['api_base']
    assert endpoint == claim['api_base']
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=20) as response:
        models = json.load(response)['data']
    assert any(row['id'] == claim['model'] for row in models)
    with (STATE / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not (STATE / 'started.json').exists()
        write_once(STATE / 'started.json', {
            'started_utc': time.time(), 'allocation': 2899,
            'claim_sha256': sha(claim_path), 'config_sha256': sha(CONFIG),
        })
        local_tmp = Path('/opt/dlami/nvme/zhiyuan-muse-nvfp4-r5')
        local_tmp.mkdir(exist_ok=True)
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY',
                   HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache',
                   MIX_SERVER_IP='10.1.114.210', TMPDIR=str(local_tmp))
        with (STATE / 'harbor.log').open('a') as stream:
            result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(CONFIG)],
                                    env=env, stdout=stream, stderr=subprocess.STDOUT)
        records = {}
        if RESULTS.exists():
            for path in RESULTS.glob('*/result.json'):
                value = json.loads(path.read_text())
                if value.get('finished_at'):
                    task = Path(value['config']['task']['path']).name
                    assert task not in records
                    records[task] = str(path)
        write_once(STATE / 'exit.json', {
            'finished_utc': time.time(), 'returncode': result.returncode,
            'terminal': len(records), 'missing': sorted(set(claim['task_toml_sha256']) - set(records)),
            'result_paths': records,
        })
        assert result.returncode == 0 and len(records) == 89


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'run')
    (prepare if sys.argv[1] == 'prepare' else run)()
