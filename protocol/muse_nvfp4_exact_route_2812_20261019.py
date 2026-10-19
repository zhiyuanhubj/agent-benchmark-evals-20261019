"""Route untouched first-round batches to a released NVFP4 GPU without replay."""

import fcntl
import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
ROUTE_STATE = STATE / 'extra_gpu'
RESULTS = ROOT / 'results/muse_nvfp4'
LANES = {'b03': 2, 'b05': 3}
JOB_PREFIX = 'muse-nvfp4-tb-v1-exact-r1-completion-2866-'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def paths(batch):
    return (ROUTE_STATE / f'r1-{batch}-2812-route.lock',
            ROUTE_STATE / f'r1-{batch}-2812-route.json',
            ROUTE_STATE / f'r1-{batch}-local-started.json',
            WORK / 'configs' / f'r1-route-2812-{batch}.json')


def validate_route(receipt, config_path, batch):
    original = json.loads(config_path.read_text())
    effective = Path(receipt['effective_config'])
    assert receipt['batch'] == batch and receipt['lane'] == LANES[batch]
    assert receipt['allocation'] == 2812 and receipt['job_name'] == original['job_name']
    assert receipt['original_config'] == str(config_path)
    assert receipt['original_sha256'] == digest(config_path)
    assert receipt['tasks'] == [Path(t['path']).name for t in original['tasks']]
    assert effective.is_file() and receipt['effective_sha256'] == digest(effective)
    expected = json.loads(json.dumps(original))
    expected['agents'][0]['kwargs']['api_base'] = receipt['endpoint']
    assert json.loads(effective.read_text()) == expected, 'Route changed benchmark settings beyond endpoint'
    assert receipt['sampling_profile_unchanged'] is True
    return effective


def route_for_extra_lane(config_path, lane):
    """Choose once under a lock before the local Harbor job starts."""
    batch = config_path.stem[-3:]
    if batch not in LANES or config_path.name != f'r1-completion-2866-{batch}.json':
        return config_path
    assert str(lane) == str(LANES[batch])
    lock_path, receipt_path, local_path, _ = paths(batch)
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if receipt_path.exists():
            assert not local_path.exists(), 'Both local and remote owners claimed batch'
            receipt = json.loads(receipt_path.read_text())
            return validate_route(receipt, config_path, batch)
        assert not local_path.exists(), 'Local batch already started; never redraw'
        save(local_path, {'utc': time.time(), 'batch': batch, 'lane': LANES[batch],
                          'original_config': str(config_path), 'original_sha256': digest(config_path)})
        return config_path


def prepare_routes(endpoint):
    """Claim only batches that have not begun when the new model is ready."""
    assert endpoint.startswith('http://10.') and endpoint.endswith(':31320/v1')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=10) as response:
        models = json.load(response).get('data', [])
    assert any(row.get('id') == 'muse-spark-open-nvfp4' for row in models)
    plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
    claimed = []
    for batch, lane in LANES.items():
        item = next(row for row in plan['configurations']
                    if row['round'] == 1 and row['job_name'] == JOB_PREFIX + batch)
        source = Path(item['path'])
        assert source.name == f'r1-completion-2866-{batch}.json' and digest(source) == item['sha256']
        owner = json.loads((STATE / (source.stem + '-extra-owner.json')).read_text())
        assert owner['lane'] == lane and owner['config_sha256'] == item['sha256']
        lock_path, receipt_path, local_path, effective = paths(batch)
        with lock_path.open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if local_path.exists() or (RESULTS / item['job_name']).exists():
                continue
            if receipt_path.exists():
                validate_route(json.loads(receipt_path.read_text()), source, batch)
                claimed.append(batch)
                continue
            value = json.loads(source.read_text())
            value['agents'][0]['kwargs']['api_base'] = endpoint
            save(effective, value)
            receipt = {'utc': time.time(), 'batch': batch, 'lane': lane,
                       'allocation': 2812, 'job_name': item['job_name'],
                       'tasks': item['tasks'], 'original_config': str(source),
                       'original_sha256': item['sha256'], 'effective_config': str(effective),
                       'effective_sha256': digest(effective), 'endpoint': endpoint,
                       'sampling_profile_unchanged': True}
            validate_route(receipt, source, batch)
            save(receipt_path, receipt)
            claimed.append(batch)
    return claimed
