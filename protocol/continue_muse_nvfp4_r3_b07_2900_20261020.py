#!/usr/bin/env python3
"""Run the untouched round-3 b07 replacement on the live 2900 replica."""

import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


SOURCE = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019')
WORK = SOURCE / 'muse_nvfp4'
STATE = WORK / 'state/r3-infra-replacement-2900'
ROUTE = STATE / 'extra-routes-20261020/b07.json'
ROOT = SOURCE / 'results/muse_nvfp4'
ENDPOINT = 'http://10.1.101.159:31321/v1'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    with (STATE / 'b07-2900-continuation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan_path = STATE / 'plan.json'
        plan = json.loads(plan_path.read_text())
        batch = plan['batches'][7]
        route = json.loads(ROUTE.read_text())
        assert batch['index'] == route['batch'] == 7
        assert len(batch['tasks']) == 10 and route['allocation'] == 2869
        assert not (STATE / 'b07-started.json').exists()
        assert not (STATE / 'extra-routes-20261020/b07-started.json').exists()
        job_root = ROOT / batch['job_name']
        assert job_root.is_dir() and not list(job_root.iterdir()), 'b07 already sampled'
        proof_path = WORK / 'state/replica-2900/endpoint-ready.json'
        proof = json.loads(proof_path.read_text())
        assert proof['allocation'] == 2900 and proof['api_base'] == ENDPOINT
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(ENDPOINT + '/models', timeout=20) as response:
            assert any(x['id'] == 'muse-spark-open-nvfp4' for x in json.load(response)['data'])
        original = Path(batch['effective_config'])
        old_route = Path(route['routed_config'])
        assert sha(original) == batch['effective_config_sha256']
        assert sha(old_route) == route['routed_config_sha256']
        old = json.loads(old_route.read_text())
        config = json.loads(original.read_text())
        assert config['job_name'] == batch['job_name']
        assert config['n_attempts'] == old['n_attempts'] == 1
        assert config['retry']['max_retries'] == old['retry']['max_retries'] == 0
        assert config['agents'][0]['kwargs']['api_base'] == ENDPOINT
        config['agents'][0]['kwargs']['api_base'] = route['endpoint']
        assert config == old, 'Old route changed sampling settings'
        config['agents'][0]['kwargs']['api_base'] = ENDPOINT
        config_path = WORK / 'configs/r3-infra-replacement-route-2900-b07.json'
        receipt_path = STATE / 'b07-2900-continuation.json'
        assert not config_path.exists() and not receipt_path.exists()
        write_once(config_path, config)
        write_once(receipt_path, {
            'utc': time.time(), 'batch': 7, 'source_plan': str(plan_path),
            'source_plan_sha256': sha(plan_path), 'preserved_old_route': str(ROUTE),
            'preserved_old_route_sha256': sha(ROUTE),
            'old_allocation': 2869, 'old_route_started': False,
            'allocation': 2900, 'endpoint': ENDPOINT, 'endpoint_ready_sha256': sha(proof_path),
            'effective_config': str(config_path), 'effective_config_sha256': sha(config_path),
            'job_name': batch['job_name'], 'tasks': [x['task'] for x in batch['tasks']],
            'policy': 'Same single predeclared infrastructure replacement draw, rerouted before any model response; only api_base changed.',
        })
        started = STATE / 'b07-2900-started.json'
        write_once(started, {'utc': time.time(), 'receipt_sha256': sha(receipt_path)})
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache', MIX_SERVER_IP='10.1.101.159')
        with (STATE / 'b07-2900.log').open('a') as stream:
            result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(config_path)],
                                    env=env, stdout=stream, stderr=subprocess.STDOUT)
        found = {}
        for path in job_root.glob('*/result.json'):
            value = json.loads(path.read_text())
            if value.get('finished_at'):
                task = Path(value['config']['task']['path']).name
                assert task not in found
                found[task] = str(path)
        expected = {x['task'] for x in batch['tasks']}
        write_once(STATE / 'b07-2900-exit.json', {
            'utc': time.time(), 'returncode': result.returncode,
            'terminal': len(found), 'missing': sorted(expected - set(found)),
            'result_paths': found,
        })
        assert result.returncode == 0 and set(found) == expected


if __name__ == '__main__':
    main()
