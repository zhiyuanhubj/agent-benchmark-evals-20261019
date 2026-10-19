"""Coordinate an early b05 launch with the pre-existing sequential lane 3."""

import atexit
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

from route_2812 import validate_route

WORK = Path(__file__).resolve().parent
ROOT = WORK.parent
STATE = WORK / 'state/extra_gpu'
LOCK = STATE / 'r1-b05-early.lock'
OWNER = STATE / 'r1-b05-early-owner.json'
NORMAL = STATE / 'r1-b05-normal-started.json'
EXIT = STATE / 'r1-b05-early-exit.json'
ROUTE = STATE / 'r1-b05-extra-route.json'


def save(path, value):
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def coverage(config):
    expected = {Path(row['path']).name for row in config['tasks']}
    found = set()
    directory = Path(config['jobs_dir']) / config['job_name']
    for result_path in directory.glob('*/result.json'):
        result = json.loads(result_path.read_text())
        if result.get('finished_at'):
            task = Path(result['config']['task']['path']).name
            assert task in expected and task not in found
            found.add(task)
    return expected, found


def owner_alive(pid):
    try:
        command = (Path('/proc') / str(pid) / 'cmdline').read_bytes()
    except OSError:
        return False
    return b'harbor_entry.py' in command


def coordinate(config_path):
    assert config_path.name == 'r1-completion-2866-b05.json'
    assert os.environ.get('SLURM_JOB_ID') == '2922'
    assert os.environ.get('MUSE_TB_EXTRA_LANE') == '3'
    config = json.loads(config_path.read_text())
    assert len(config['tasks']) == 10
    digest = hashlib.sha256(config_path.read_bytes()).hexdigest()
    receipt = json.loads(ROUTE.read_text())
    assert receipt['batch'] == 'b05' and receipt['original_sha256'] == digest
    validate_route(receipt, config_path, 'b05')
    early = os.environ.get('MUSE_TB_B05_EARLY_OWNER') == '1'
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if early:
            assert not OWNER.exists() and not NORMAL.exists() and not EXIT.exists()
            assert not (Path(config['jobs_dir']) / config['job_name']).exists()
            save(OWNER, {'utc': time.time(), 'pid': os.getpid(), 'cpu_allocation': 2922,
                         'model_allocation': receipt['allocation'], 'job_name': config['job_name'],
                         'tasks': [Path(row['path']).name for row in config['tasks']],
                         'original_config': str(config_path), 'original_sha256': digest,
                         'route_receipt': str(ROUTE), 'route_sha256': hashlib.sha256(ROUTE.read_bytes()).hexdigest(),
                         'endpoint': receipt['endpoint']})
        elif not OWNER.exists():
            assert not NORMAL.exists(), 'b05 already claimed by the sequential lane'
            save(NORMAL, {'utc': time.time(), 'pid': os.getpid(), 'original_sha256': digest,
                          'job_name': config['job_name']})
            return True
    if early:
        def record_exit():
            try:
                expected, found = coverage(config)
                missing = sorted(expected - found)
                save(EXIT, {'utc': time.time(), 'original_sha256': digest,
                            'route_sha256': hashlib.sha256(ROUTE.read_bytes()).hexdigest(),
                            'terminal_tasks': sorted(found), 'missing_terminal_tasks': missing,
                            'returncode': 0 if not missing else 1})
            except Exception as exc:
                save(EXIT, {'utc': time.time(), 'original_sha256': digest,
                            'returncode': 1, 'error': repr(exc)})
        atexit.register(record_exit)
        return True
    owner = json.loads(OWNER.read_text())
    assert owner['original_sha256'] == digest and owner['job_name'] == config['job_name']
    while not EXIT.exists():
        assert owner_alive(owner['pid']), 'Early b05 owner stopped before exit receipt; preserve its outputs'
        time.sleep(15)
    outcome = json.loads(EXIT.read_text())
    expected, found = coverage(config)
    assert outcome['returncode'] == 0 and outcome['original_sha256'] == digest
    assert found == expected and outcome['terminal_tasks'] == sorted(expected)
    return False
