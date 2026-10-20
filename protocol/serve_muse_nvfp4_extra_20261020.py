#!/usr/bin/env python3
"""Serve the pinned Muse NVFP4 weights on verified single-node allocations."""

import fcntl
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


SOURCE = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019')
STATE = SOURCE / 'muse_nvfp4/state/replicas-extra-20261020'
DEPLOYMENT = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/deployment.json')
WEIGHTS = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/weights')
IMAGE = 'lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a'
HOSTS = {2869: 'ip-10-1-77-106', 2899: 'ip-10-1-114-210',
         2902: 'ip-10-1-105-182'}
PORT = 31321
MODEL = 'muse-spark-open-nvfp4'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert len(sys.argv) == 2 and sys.argv[1].isdigit()
    allocation = int(sys.argv[1])
    assert allocation in HOSTS
    assert os.environ.get('SLURM_JOB_ID') == str(allocation)
    assert socket.gethostname() == HOSTS[allocation]
    assert (WEIGHTS / 'config.json').is_file()
    assert (WEIGHTS / 'model.safetensors.index.json').is_file()
    assert subprocess.run(['docker', 'image', 'inspect', IMAGE], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0
    assert not subprocess.check_output(
        ['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
    state = STATE / str(allocation)
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'serve.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        source = json.loads(DEPLOYMENT.read_text())
        command = list(source['command'])
        assert command[command.index('-v') + 1] == str(WEIGHTS) + ':/model:ro'
        assert IMAGE in command
        assert command[command.index('--served-model-name') + 1] == MODEL
        assert command[command.index('--port') + 1] == '31320'
        command[command.index('--name') + 1] = f'zhiyuan-muse-nvfp4-exact-tb-{allocation}'
        command[command.index('--port') + 1] = str(PORT)
        launch = state / 'serve-launch.json'
        assert not launch.exists(), 'Prior launch requires reconciliation'
        launch.write_text(json.dumps({
            'utc': time.time(), 'allocation': allocation, 'hostname': socket.gethostname(),
            'source_deployment_sha256': sha(DEPLOYMENT),
            'weights_index_sha256': sha(WEIGHTS / 'model.safetensors.index.json'),
            'model': MODEL, 'precision': 'NVFP4', 'image_digest': IMAGE,
            'only_command_changes': ['--name', '--port'], 'command': command,
        }, indent=2) + '\n')
        process = subprocess.Popen(command)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        endpoint = 'http://' + HOSTS[allocation].removeprefix('ip-').replace('-', '.') + f':{PORT}/v1'
        for _ in range(720):
            assert process.poll() is None, 'Pinned Muse NVFP4 server exited before readiness'
            try:
                with opener.open(f'http://127.0.0.1:{PORT}/v1/models', timeout=5) as response:
                    models = json.load(response)['data']
                if any(model['id'] == MODEL for model in models):
                    break
            except OSError:
                pass
            time.sleep(10)
        else:
            raise RuntimeError('Muse NVFP4 replica loading exceeded two hours')
        (state / 'endpoint-ready.json').write_text(json.dumps({
            'utc': time.time(), 'allocation': allocation, 'api_base': endpoint,
            'model': MODEL, 'precision': 'NVFP4', 'image_digest': IMAGE,
            'source_deployment_sha256': sha(DEPLOYMENT),
            'weights_index_sha256': sha(WEIGHTS / 'model.safetensors.index.json'),
        }, indent=2) + '\n')
        raise SystemExit(process.wait())


if __name__ == '__main__':
    main()
