#!/usr/bin/env python3
"""Run one disjoint round-3 replacement draw on a verified extra replica."""

import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


SOURCE = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019')
WORK = SOURCE / 'muse_nvfp4'
STATE = WORK / 'state/r3-infra-replacement-2900'
REPLICAS = WORK / 'state/replicas-extra-20261020'
RESULTS = SOURCE / 'results/muse_nvfp4'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
LANES = {(2869, 0): [3, 7], (2869, 1): [5],
         (2899, 0): [4, 8], (2899, 1): [6]}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    assert len(sys.argv) == 3 and all(part.isdigit() for part in sys.argv[1:])
    allocation, lane = map(int, sys.argv[1:])
    assert (allocation, lane) in LANES
    assert os.environ.get('SLURM_JOB_ID') == str(allocation)
    with (STATE / f'extra-{allocation}-lane{lane}.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proof_path = REPLICAS / str(allocation) / 'endpoint-ready.json'
        preflight_path = REPLICAS / str(allocation) / 'reasoning-preflight.json'
        for _ in range(720):
            if proof_path.exists() and preflight_path.exists():
                break
            time.sleep(10)
        else:
            raise RuntimeError('Extra Muse replica or reasoning preflight did not become ready within two hours')
        proof = json.loads(proof_path.read_text())
        assert proof['allocation'] == allocation and proof['model'] == 'muse-spark-open-nvfp4'
        assert proof['precision'] == 'NVFP4'
        preflight = json.loads(preflight_path.read_text())
        assert preflight['allocation'] == allocation and preflight['nonempty_reasoning_content']
        assert preflight['response']['model'] == proof['model']
        assert preflight['response']['choices'][0]['message']['reasoning_content'].strip()
        existing = json.loads((WORK / 'state/replica-2900/endpoint-ready.json').read_text())
        assert proof['source_deployment_sha256'] == existing['source_deployment_sha256']
        endpoint = proof['api_base']
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(endpoint + '/models', timeout=20) as response:
            models = json.load(response)['data']
        assert any(model['id'] == proof['model'] for model in models)
        plan = json.loads((STATE / 'plan.json').read_text())
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache',
                   MIX_SERVER_IP=endpoint.split('/')[2].split(':')[0])
        for number in LANES[(allocation, lane)]:
            batch = plan['batches'][number]
            route_path = STATE / 'extra-routes-20261020' / f'b{number:02}.json'
            route = json.loads(route_path.read_text())
            assert route['batch'] == number and route['allocation'] == allocation
            assert route['endpoint'] == endpoint and route['job_name'] == batch['job_name']
            assert route['original_effective_config_sha256'] == batch['effective_config_sha256']
            assert not (STATE / f'b{number:02}-started.json').exists(), 'Original lane also claimed batch'
            config_path = Path(route['routed_config'])
            assert sha(config_path) == route['routed_config_sha256']
            config = json.loads(config_path.read_text())
            assert config['job_name'] == batch['job_name']
            assert config['agents'][0]['kwargs']['api_base'] == endpoint
            assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
            job_root = RESULTS / batch['job_name']
            assert job_root.is_dir() and not list(job_root.iterdir()), 'Draw already started'
            started = STATE / 'extra-routes-20261020' / f'b{number:02}-started.json'
            write_once(started, {'utc': time.time(), 'allocation': allocation, 'lane': lane,
                                 'job_name': batch['job_name'], 'route_sha256': sha(route_path),
                                 'endpoint_ready_sha256': sha(proof_path)})
            with (STATE / 'extra-routes-20261020' / f'b{number:02}.log').open('a') as stream:
                result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(config_path)],
                                        env=env, stdout=stream, stderr=subprocess.STDOUT)
            found = {}
            for result_path in job_root.glob('*/result.json'):
                value = json.loads(result_path.read_text())
                if value.get('finished_at'):
                    task = Path(value['config']['task']['path']).name
                    assert task not in found
                    found[task] = str(result_path)
            expected = {item['task'] for item in batch['tasks']}
            write_once(STATE / 'extra-routes-20261020' / f'b{number:02}-exit.json',
                       {'utc': time.time(), 'allocation': allocation, 'lane': lane,
                        'job_name': batch['job_name'], 'returncode': result.returncode,
                        'terminal': len(found), 'missing': sorted(expected - set(found)),
                        'result_paths': found})
            assert result.returncode == 0 and set(found) == expected


if __name__ == '__main__':
    main()
