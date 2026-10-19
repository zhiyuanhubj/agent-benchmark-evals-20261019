#!/usr/bin/env python3
"""Copy pinned Muse BF16 weights from an already verified owned node to job 2886."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener
import fcntl
import hashlib
import json
import os
import socket
import sys


BASE = Path('/fsx/home/zhiyuan')
STATE = BASE / '.private/beam_20261018/expanded_capacity_20261018'
SOURCE = BASE / '.private/muse_bf16_20261018/stage_2869/muse_bf16-verification.json'
SOURCE_URL = 'http://10.1.77.106:31361/'
REVISION = '0fb02478b02565b2ce7fc57e6051c91172774ac9'
rank = int(sys.argv[1])
assert rank in (0, 1)
root = STATE / f'allocation-2886-rank-{rank}'
plan_bytes = (root / 'prefetch-plan.json').read_bytes()
plan = json.loads(plan_bytes)
assert plan['sandbox_allocation'] == 2886
assert socket.gethostname() == plan['hostname']
spec = plan['models']['muse_bf16']
assert spec['revision'] == REVISION and spec['repo'] == 'meta-models/Muse-Spark-Open-816B-A42B'
source_bytes = SOURCE.read_bytes()
source = json.loads(source_bytes)
assert source['complete'] and source['revision'] == REVISION
verified = {row['file']: row for row in source['verified_files']}
files = spec['files']
assert len(files) == 78 and set(files) == set(verified)
destination = Path(spec['local_path'])
assert destination.is_relative_to(Path(plan['node_local_root']))
destination.mkdir(parents=True, exist_ok=True)
lock = (Path(plan['node_local_root']) / 'prefetch.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
status = root / 'prefetch-current.json'
record = {
    'started_utc': datetime.now(timezone.utc).isoformat(),
    'plan_sha256': hashlib.sha256(plan_bytes).hexdigest(),
    'allocation': 2886,
    'transfer_source_allocation': 2869,
    'transfer_source_verification_sha256': hashlib.sha256(source_bytes).hexdigest(),
    'transfer_method': 'private-owned-node-http-with-pinned-hub-hashes',
    'models': {'muse_bf16': {
        'repo': spec['repo'], 'revision': REVISION,
        'local_path': str(destination), 'expected_files': len(files),
        'status': 'copying_verified_source', 'completed_files': 0,
        'completed_file_bytes': 0,
    }},
    'complete': False, 'active_split': 'muse_bf16',
}


def available_bytes():
    stats = os.statvfs(destination)
    return stats.f_bavail * stats.f_frsize


def save():
    record['utc'] = datetime.now(timezone.utc).isoformat()
    record['available_bytes'] = available_bytes()
    temporary = status.with_name(status.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(status)


def digest(path, row):
    value = hashlib.sha256() if row['algorithm'] == 'sha256' else hashlib.sha1()
    if row['algorithm'] == 'git-blob-sha1':
        value.update(('blob ' + str(row['bytes']) + '\0').encode())
    else:
        assert row['algorithm'] == 'sha256'
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 2**20), b''):
            value.update(block)
    return value.hexdigest()


def copy_one(name):
    row = verified[name]
    target = destination / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size == row['bytes']:
        if digest(target, row) == row['expected']:
            return {'file': name, 'bytes': row['bytes'], 'source': 'existing_hub_download'}
    temporary = target.with_name(target.name + '.verifiedcopy.tmp')
    temporary.unlink(missing_ok=True)
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(SOURCE_URL + quote(name), timeout=180) as response:
            assert response.status == 200
            assert int(response.headers['Content-Length']) == row['bytes'], name
            with temporary.open('wb') as output:
                for block in iter(lambda: response.read(8 * 2**20), b''):
                    output.write(block)
        assert temporary.stat().st_size == row['bytes'], name
        assert digest(temporary, row) == row['expected'], name
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'file': name, 'bytes': row['bytes'], 'source': 'verified_node_2869'}


assert available_bytes() > spec['estimated_weight_bytes'] + 512 * 2**30
save()
completed = []
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = {pool.submit(copy_one, name): name for name in files}
    for future in as_completed(futures):
        completed.append(future.result())
        item = record['models']['muse_bf16']
        item['completed_files'] = len(completed)
        item['completed_file_bytes'] = sum(row['bytes'] for row in completed)
        save()
        assert available_bytes() > 512 * 2**30, 'Insufficient disk headroom'

assert {row['file'] for row in completed} == set(files)
index = json.loads((destination / 'model.safetensors.index.json').read_text())
shards = set(index['weight_map'].values())
assert len(shards) == 65 and shards.issubset(set(files))
verification = root / 'muse_bf16-verification.json'
verification.write_text(json.dumps({
    'revision': REVISION, 'verified_files': source['verified_files'],
    'complete': True, 'verification_method': 'read-and-hash-each-existing-or-copied-file',
    'transfer_source_allocation': 2869,
}, indent=2) + '\n')
record['models']['muse_bf16'].update({
    'status': 'verified', 'index_shards': len(shards), 'verification_returncode': 0,
    'completed_files': len(files),
    'completed_file_bytes': sum(row['bytes'] for row in completed),
})
record['complete'] = True
record['active_split'] = None
save()
print(json.dumps({'complete': True, 'rank': rank, 'files': len(files),
                  'bytes': record['models']['muse_bf16']['completed_file_bytes']}), flush=True)
