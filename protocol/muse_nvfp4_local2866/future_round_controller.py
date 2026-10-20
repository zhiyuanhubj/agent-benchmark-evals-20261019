"""Run disjoint planned round-2/3 TB batches on one newly granted NVFP4 GPU."""

import fcntl
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from route_2812 import validate_route as validate_round1_route
from route_future_rounds import LANES, ROOT, STATE, WORK, claim_next, save, sha, valid_endpoint, validate_route

PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
ROUTES = STATE / 'future-routes'


def endpoint_ready(allocation):
    proof = (WORK / 'state/reassigned-2867/endpoint-ready.json' if allocation == 2867
             else WORK / f'state/extra_gpu/{allocation}-ready.json')
    value = json.loads(proof.read_text())
    if allocation == 2867:
        assert value['allocation'] == allocation and value['model'] == 'muse-spark-open-nvfp4'
        endpoint = value['api_base']
    else:
        assert value['job'] == allocation and value['phase'] == 'ready'
        if allocation == 2812:
            assert value.get('claimed_round1_batches') == ['b05']
            route_path = STATE / 'extra_gpu/r1-b05-extra-route.json'
            route = json.loads(route_path.read_text())
            source = WORK / 'configs/r1-completion-2866-b05.json'
            validate_round1_route(route, source, 'b05')
            exit_state = json.loads((STATE / 'extra_gpu/r1-b05-early-exit.json').read_text())
            assert exit_state['returncode'] == 0 and exit_state['missing_terminal_tasks'] == []
            assert exit_state['terminal_tasks'] == route['tasks']
            assert exit_state['original_sha256'] == sha(source)
            assert exit_state['route_sha256'] == sha(route_path)
            expected, found = terminal_coverage(route)
            assert found == expected, 'Round-1 b05 handoff must finish before reusing 2812'
        else:
            assert value.get('claimed_round1_batches') == [], 'Round-1 handoff takes priority'
        endpoint = value['endpoint']
    assert valid_endpoint(allocation, endpoint)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=10) as response:
        models = json.load(response)['data']
    assert any(row.get('id') == 'muse-spark-open-nvfp4' for row in models)
    return endpoint


def terminal_coverage(receipt):
    expected = set(receipt['tasks'])
    found = set()
    directory = ROOT / 'results/muse_nvfp4' / receipt['job_name']
    for path in directory.glob('*/result.json'):
        value = json.loads(path.read_text())
        if not value.get('finished_at'):
            continue
        task = Path(value['config']['task']['path']).name
        assert task in expected and task not in found
        assert value['config']['agent']['kwargs']['api_base'] == receipt['endpoint']
        found.add(task)
    return expected, found


def main():
    allocation = int(sys.argv[1])
    slot = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    assert allocation in LANES and os.environ.get('SLURM_JOB_ID') == '2919'
    assert slot == 0 or (allocation == 2812 and slot in (1, 2, 3)) or (allocation == 2867 and slot == 1)
    images = json.loads((ROOT / 'allocation-2919/images-ready.json').read_text())
    assert images['count'] == 89 and images['all_archive_identities_verified']
    assert json.loads((ROOT / 'allocation-2919/official-policy-preflight-ready.json').read_text())['passed']
    lane = LANES[allocation]
    controller_name = str(allocation) if slot == 0 else f'{allocation}-slot{slot}'
    lock_name = (f'extra-lane{lane}-2866-controller.lock' if slot == 0 else
                 f'extra-lane{lane}-slot{slot}-2866-controller.lock')
    status_path = ROUTES / f'{controller_name}-controller-status.json'
    ROUTES.mkdir(parents=True, exist_ok=True)
    with (STATE / lock_name).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        endpoint = endpoint_ready(allocation)
        save(status_path,
             {'utc': time.time(), 'allocation': allocation, 'lane': lane, 'slot': slot,
              'endpoint': endpoint, 'phase': 'ready'})
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
        completed = []
        while receipt := claim_next(allocation, endpoint):
            source = Path(receipt['original_config'])
            effective = validate_route(source, receipt,
                                       json.loads((STATE / f'{source.stem}-extra-owner.json').read_text()))
            save(status_path,
                 {'utc': time.time(), 'allocation': allocation, 'lane': lane, 'slot': slot,
                  'endpoint': endpoint, 'phase': 'running',
                  'job_name': receipt['job_name'], 'completed_batches': completed})
            log = ROUTES / f'{receipt["job_name"]}-{controller_name}.log'
            with log.open('a') as stream:
                result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(effective)],
                                        env=env, stdout=stream, stderr=subprocess.STDOUT)
            expected, found = terminal_coverage(receipt)
            code = result.returncode if result.returncode else (0 if found == expected else 1)
            save(STATE / f'{source.stem}-extra-exit.json',
                 {'utc': time.time(), 'lane': lane, 'job_name': receipt['job_name'],
                  'returncode': code, 'config_sha256': sha(source),
                  'effective_config_sha256': sha(effective),
                  'missing_terminal_tasks': sorted(expected - found)})
            assert code == 0, 'Handoff batch failed; preserve results and audit before resuming'
            completed.append(receipt['job_name'])
        save(status_path,
             {'utc': time.time(), 'allocation': allocation, 'lane': lane, 'slot': slot,
              'endpoint': endpoint, 'phase': 'no_unclaimed_round23_batches',
              'completed_batches': completed})


if __name__ == '__main__':
    main()
