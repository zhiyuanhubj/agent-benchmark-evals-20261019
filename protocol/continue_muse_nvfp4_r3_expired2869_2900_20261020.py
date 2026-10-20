#!/usr/bin/env python3
"""Document and continue only round-3 trials interrupted by allocation 2869 expiry."""

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
STATE = WORK / 'state/r3-infra-replacement-2900'
RESULTS = SOURCE / 'results/muse_nvfp4'
CLAIM = STATE / 'expired2869-continuation-2900-claim.json'
START = STATE / 'expired2869-continuation-2900-start.json'
EXIT = STATE / 'expired2869-continuation-2900-exit.json'
LOCK = STATE / 'expired2869-continuation-2900.lock'
LOG = STATE / 'expired2869-continuation-2900.log'
CONFIG = WORK / 'configs/r3-expired2869-continuation-2900-20261020.json'
JOB = 'muse-nvfp4-tb-v1-exact-r3-expired2869-continuation-2900-20261020'
ENDPOINT = 'http://10.1.101.159:31321/v1'
PYTHON = BASE / 'AgentCompass/.venv/bin/python'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def assert_old_allocation_expired():
    output = subprocess.check_output(
        ['sacct', '-n', '-P', '-j', '2869', '--format=JobIDRaw,State,End'], text=True)
    rows = [line.split('|') for line in output.splitlines() if line.startswith('2869|')]
    assert len(rows) == 1 and rows[0][1] == 'TIMEOUT'
    assert rows[0][2].startswith('2026-10-20T16:00:')
    for lane in (0, 1):
        unit = f'muse-nvfp4-r3-extra-2869-lane{lane}-20261020.service'
        active = subprocess.run(['systemctl', '--user', 'is-active', unit],
                                capture_output=True, text=True)
        assert active.stdout.strip() != 'active', unit
    return rows[0]


def source_rows(plan):
    selected = []
    configs = []
    for number in (3, 5):
        batch = plan['batches'][number]
        route_path = STATE / f'extra-routes-20261020/b{number:02}.json'
        route = read(route_path)
        assert route['batch'] == number and route['allocation'] == 2869
        assert route['job_name'] == batch['job_name']
        assert sha(Path(batch['effective_config'])) == batch['effective_config_sha256']
        assert sha(Path(route['routed_config'])) == route['routed_config_sha256']
        assert (STATE / f'extra-routes-20261020/b{number:02}-started.json').exists()
        assert not (STATE / f'extra-routes-20261020/b{number:02}-exit.json').exists()
        config = read(Path(batch['effective_config']))
        assert config['job_name'] == batch['job_name']
        assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
        configs.append(config)
        result_root = RESULTS / batch['job_name']
        for item, task_config in zip(batch['tasks'], config['tasks'], strict=True):
            task = item['task']
            assert Path(task_config['path']).name == task
            assert sha(Path(item['original_result'])) == item['original_result_sha256']
            matches = list(result_root.glob(task + '__*'))
            assert len(matches) <= 1, f'duplicate source task {task}'
            trial = matches[0] if matches else None
            if trial:
                assert trial.is_dir()
                result_path = trial / 'result.json'
                if result_path.exists() and read(result_path).get('finished_at'):
                    continue
                raw = sorted((trial / 'agent/raw_responses').glob('*.json'))
                trajectory = trial / 'agent/trajectory.json'
            else:
                raw = []
                trajectory = None
            selected.append({
                'task': task, 'batch': number, 'source_job': batch['job_name'],
                'task_config': task_config,
                'task_toml': str(Path(task_config['path']) / 'task.toml'),
                'task_toml_sha256': sha(Path(task_config['path']) / 'task.toml'),
                'original_failure_result': item['original_result'],
                'original_failure_result_sha256': item['original_result_sha256'],
                'source_partial_trial': str(trial) if trial else None,
                'source_partial_raw': [{'path': str(path), 'sha256': sha(path)} for path in raw],
                'source_partial_trajectory': str(trajectory) if trajectory and trajectory.exists() else None,
                'source_partial_trajectory_sha256': sha(trajectory) if trajectory and trajectory.exists() else None,
                'source_has_terminal_result': False,
            })
    assert len(selected) == 11
    assert len({row['task'] for row in selected}) == 11
    assert sum(bool(row['source_partial_raw']) for row in selected) == 4
    left, right = (json.loads(json.dumps(x)) for x in configs)
    for config in (left, right):
        config.pop('job_name')
        config.pop('tasks')
    assert left == right, 'Batch sampling settings differ'
    return selected, configs[0]


def prepare():
    assert not CLAIM.exists() and not START.exists() and not CONFIG.exists()
    assert not (RESULTS / JOB).exists()
    old_sacct = assert_old_allocation_expired()
    plan_path = STATE / 'plan.json'
    plan = read(plan_path)
    assert plan['expected_tasks'] == 89 and plan['endpoint'] == ENDPOINT
    selected, config = source_rows(plan)
    config['job_name'] = JOB
    config['tasks'] = [row['task_config'] for row in selected]
    assert config['agents'][0]['kwargs']['api_base'] == ENDPOINT
    assert config['n_concurrent_trials'] == 2
    write_once(CONFIG, config)
    proof_path = WORK / 'state/replica-2900/endpoint-ready.json'
    proof = read(proof_path)
    assert proof['allocation'] == 2900 and proof['api_base'] == ENDPOINT
    write_once(CLAIM, {
        'prepared_utc': time.time(), 'scope': 'All and only 11 round-3 replacement trials without a native result after allocation 2869 timed out',
        'original_allocation': 2869, 'original_allocation_sacct': old_sacct,
        'model_allocation': 2900, 'cpu_allocation': 2919,
        'source_plan': str(plan_path), 'source_plan_sha256': sha(plan_path),
        'model_ready': str(proof_path), 'model_ready_sha256': sha(proof_path),
        'config': str(CONFIG), 'config_sha256': sha(CONFIG),
        'job_name': JOB, 'endpoint': ENDPOINT, 'tasks': selected,
        'source_partial_model_response_tasks': 4,
        'source_never_started_tasks': 7,
        'policy': 'One separately identified infrastructure continuation for each ungraded interrupted task. Preserve the timed-out partial trajectory; select no result by correctness. Native outcomes already terminal in b03/b05 are never repeated.',
    })
    print(json.dumps({'job': JOB, 'tasks': len(selected),
                      'partial_raw': sum(len(row['source_partial_raw']) for row in selected)}))


def run():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim = read(CLAIM)
        assert claim['job_name'] == JOB and claim['endpoint'] == ENDPOINT
        assert claim['original_allocation_sacct'] == assert_old_allocation_expired()
        assert sha(Path(claim['source_plan'])) == claim['source_plan_sha256']
        assert sha(Path(claim['model_ready'])) == claim['model_ready_sha256']
        assert sha(CONFIG) == claim['config_sha256']
        assert not START.exists() and not EXIT.exists() and not (RESULTS / JOB).exists()
        plan = read(Path(claim['source_plan']))
        selected, _ = source_rows(plan)
        assert selected == claim['tasks'], 'Interrupted source evidence changed'
        assert [x['task'] for x in selected] == [Path(x['path']).name for x in read(CONFIG)['tasks']]
        assert subprocess.check_output(['squeue', '-h', '-j', '2900', '-o', '%T'], text=True).strip() == 'RUNNING'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(ENDPOINT + '/models', timeout=20) as response:
            assert any(row['id'] == 'muse-spark-open-nvfp4' for row in json.load(response)['data'])
        write_once(START, {'utc': time.time(), 'claim_sha256': sha(CLAIM),
                           'config_sha256': sha(CONFIG), 'endpoint': ENDPOINT})
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', HF_HOME=str(BASE / 'bench/hf_home'),
                   UV_CACHE_DIR=str(BASE / 'bench/uv_cache'), MIX_SERVER_IP='10.1.101.159')
        with LOG.open('a') as stream:
            result = subprocess.run([str(PYTHON), str(WORK / 'harbor_entry.py'), str(CONFIG)],
                                    cwd=str(BASE / 'AgentCompass'), env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        found = {}
        for path in (RESULTS / JOB).glob('*/result.json'):
            value = read(path)
            if value.get('finished_at'):
                task = Path(value['config']['task']['path']).name
                assert task not in found
                found[task] = str(path)
        expected = {row['task'] for row in selected}
        write_once(EXIT, {'utc': time.time(), 'returncode': result.returncode,
                          'terminal': len(found), 'missing': sorted(expected - set(found)),
                          'results': found})
        assert result.returncode == 0 and set(found) == expected


if __name__ == '__main__':
    assert sys.argv[1:] in (['prepare'], ['run'])
    (prepare if sys.argv[1] == 'prepare' else run)()
