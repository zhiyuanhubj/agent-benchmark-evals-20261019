#!/usr/bin/env python3
"""Resume this job's missing rank-1 shards without deleting existing caches."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

def digest(path, row):
    h = hashlib.sha256() if row['algorithm'] == 'sha256' else hashlib.sha1()
    if row['algorithm'] == 'git-blob-sha1':
        h.update(('blob ' + str(row['bytes']) + '\0').encode())
    with path.open('rb') as f:
        for b in iter(lambda: f.read(16 * 2**20), b''):
            h.update(b)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    a = p.parse_args()
    assert os.environ['SLURM_JOB_ID'] == '3121'
    assert socket.gethostname() == 'ip-10-1-114-210'
    local = Path('/opt/dlami/nvme/zhiyuan-muse-perf-3121-1/weights')
    # Cache cleanup has made enough local NVMe available. Keep both staging and
    # Xet cache local; do not reserve terabyte-sized files on the shared quota.
    os.environ['HF_XET_CACHE'] = str(local.parent / 'xet-cache')
    from huggingface_hub import hf_hub_download
    model = json.loads((a.state / 'PLAN.json').read_text())['models']['bf16']
    rows = model['files']
    pending = [r for r in rows if not (local / r['file']).is_file() or (local / r['file']).stat().st_size != r['bytes']]
    needed = sum(r['bytes'] for r in pending)
    reserve = 100 * 10**9
    assert shutil.disk_usage(local).free - reserve > needed, 'Local NVMe cannot fit missing shards with a 100 GB reserve'
    lock, reserved = threading.Lock(), {}
    def get(row):
        target = local / row['file']
        with lock:
            inflight = sum(reserved.values())
            assert shutil.disk_usage(local).free - inflight - reserve > row['bytes'], 'Local NVMe space reserve reached'
            reserved[row['file']] = row['bytes']
        try:
            downloaded = Path(hf_hub_download(model['repo'], row['file'], revision=model['revision'], local_dir=local))
            assert downloaded.stat().st_size == row['bytes'] and digest(downloaded, row) == row['expected']
            assert downloaded == target
            print(json.dumps({'downloaded_and_verified': row['file'], 'bytes': row['bytes'], 'local_free_GB': shutil.disk_usage(local).free / 1e9}), flush=True)
        finally:
            with lock:
                reserved.pop(row['file'], None)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for f in as_completed([pool.submit(get, r) for r in pending]):
            f.result()
    checked = []
    for row in rows:
        target = local / row['file']
        assert target.is_file() and target.stat().st_size == row['bytes']
        assert digest(target, row) == row['expected'], row['file']
        checked.append(row['file'])
    proof = {'path': str(local), 'repo': model['repo'], 'revision': model['revision'],
             'verified_files': checked, 'complete': True, 'storage': 'node-local NVMe',
             'repair': 'Inactive old Hub-model cache removed with user authorization; missing shards resumed on NVMe',
             'verified_unix': time.time()}
    path = a.state / 'bf16/rank1/weights.json'
    tmp = path.with_suffix('.tmp');tmp.write_text(json.dumps(proof, indent=2) + '\n');tmp.replace(path)
    print('BF16 RANK 1 PINNED WEIGHTS VERIFIED', flush=True)


if __name__ == '__main__':
    main()
