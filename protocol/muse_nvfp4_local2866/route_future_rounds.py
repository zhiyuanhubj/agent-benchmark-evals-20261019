"""Disjoint, crash-visible handoff of untouched Muse NVFP4 TB rounds 2/3."""

import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
ROUTES = STATE / 'future-routes'
RESULTS = ROOT / 'results/muse_nvfp4'
LANES = {2812: 4, 2923: 5, 2924: 6, 2927: 7, 2928: 8, 2867: 9, 2866: 10}
NAME = re.compile(r'r[23]-completion-2866-b\d{2}\.json\Z')


def valid_endpoint(allocation, endpoint):
    port = 31321 if allocation == 2867 else 31320
    return endpoint.startswith('http://10.') and endpoint.endswith(f':{port}/v1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temp, path)


def paths(source):
    stem = source.stem
    return (ROUTES / f'{stem}.lock', ROUTES / f'{stem}-local-started.json',
            ROUTES / f'{stem}-route.json', STATE / f'{stem}-extra-owner.json')


def plan_item(source):
    assert NAME.fullmatch(source.name), source
    plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
    rows = [row for row in plan['configurations'] if row['path'] == str(source)]
    assert len(rows) == 1 and rows[0]['round'] in (2, 3)
    row = rows[0]
    assert sha(source) == row['sha256']
    config = json.loads(source.read_text())
    assert config['job_name'] == row['job_name']
    assert [Path(task['path']).name for task in config['tasks']] == row['tasks']
    assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
    return row, config


def validate_route(source, receipt, owner):
    row, original = plan_item(source)
    effective = Path(receipt['effective_config'])
    assert receipt['job_name'] == row['job_name'] and receipt['tasks'] == row['tasks']
    assert receipt['original_config'] == str(source) and receipt['original_sha256'] == row['sha256']
    assert receipt['allocation'] in LANES and receipt['lane'] == LANES[receipt['allocation']]
    assert valid_endpoint(receipt['allocation'], receipt['endpoint'])
    assert receipt['sampling_profile_unchanged'] is True
    assert effective.is_file() and sha(effective) == receipt['effective_sha256']
    expected = json.loads(json.dumps(original))
    expected['agents'][0]['kwargs']['api_base'] = receipt['endpoint']
    assert json.loads(effective.read_text()) == expected, 'Handoff changed more than model endpoint'
    assert owner['lane'] == receipt['lane'] and owner['job_name'] == row['job_name']
    assert owner['config_sha256'] == row['sha256'] and owner['tasks'] == row['tasks']
    assert owner['destination_allocation'] == receipt['allocation']
    assert owner['effective_config_sha256'] == receipt['effective_sha256']
    return effective


def original_entry_claim(source):
    """Called by each original r2/r3 Harbor invocation before it can draw."""
    row, _ = plan_item(source)
    lock_path, local_path, receipt_path, owner_path = paths(source)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if owner_path.exists():
            assert receipt_path.exists() and not local_path.exists()
            validate_route(source, json.loads(receipt_path.read_text()), json.loads(owner_path.read_text()))
            return 'external'
        assert not receipt_path.exists(), 'Orphaned handoff receipt needs audit'
        assert not local_path.exists(), 'Original batch was already started; no repeat draw'
        save(local_path, {'utc': time.time(), 'job_name': row['job_name'],
                          'original_config': str(source), 'original_sha256': row['sha256']})
        return 'original'


def claim_next(allocation, endpoint):
    """Claim exactly one untouched planned batch for a ready new GPU replica."""
    assert allocation in LANES and valid_endpoint(allocation, endpoint)
    plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
    for row in plan['configurations']:
        if row['round'] not in (2, 3):
            continue
        source = Path(row['path'])
        lock_path, local_path, receipt_path, owner_path = paths(source)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if (local_path.exists() or owner_path.exists() or receipt_path.exists()
                    or (STATE / f'{row["job_name"]}-launch.json').exists()
                    or (RESULTS / row['job_name']).exists()):
                continue
            checked, original = plan_item(source)
            assert checked == row
            effective = WORK / 'configs' / f'{source.stem}-routed-{allocation}.json'
            assert not effective.exists(), 'Previous effective config needs audit'
            value = json.loads(json.dumps(original))
            value['agents'][0]['kwargs']['api_base'] = endpoint
            save(effective, value)
            receipt = {'utc': time.time(), 'round': row['round'], 'allocation': allocation,
                       'lane': LANES[allocation], 'cpu_allocation': 2919,
                       'job_name': row['job_name'], 'tasks': row['tasks'],
                       'original_config': str(source), 'original_sha256': row['sha256'],
                       'effective_config': str(effective), 'effective_sha256': sha(effective),
                       'endpoint': endpoint, 'sampling_profile_unchanged': True}
            owner = {'utc': receipt['utc'], 'lane': LANES[allocation],
                     'job_name': row['job_name'], 'config_sha256': row['sha256'],
                     'tasks': row['tasks'], 'effective_config_sha256': receipt['effective_sha256'],
                     'endpoint': endpoint, 'destination_allocation': allocation}
            validate_route(source, receipt, owner)
            save(receipt_path, receipt)
            save(owner_path, owner)
            return receipt
    return None
