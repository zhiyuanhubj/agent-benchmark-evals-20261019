#!/usr/bin/env python3
"""Prove the pinned task image can start tmux with read-only harness mounts."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/fsx/home/zhiyuan/bench/tb21_v1_four_models_20261012')
from preinstalled_tmux_isolated_docker import TOOL_MOUNTS


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
PROOF = ROOT / 'muse_nvfp4/state/r2-fasttext-tmux-preflight-2919.json'
IMAGES = ROOT / 'allocation-2919/images-ready.json'
IMAGE = 'alexgshaw/train-fasttext:20251031'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    assert not PROOF.exists()
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS',
                'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    docker = ['docker', '--host=unix:///var/run/docker.sock']
    inspect = subprocess.run(docker + ['image', 'inspect', IMAGE, '--format', '{{.Id}}'],
                             env=env, capture_output=True, text=True, timeout=20, check=True)
    image_id = inspect.stdout.strip()
    verified = [row for row in json.loads(IMAGES.read_text())['images'] if row['tag'] == IMAGE]
    assert len(verified) == 1 and verified[0]['image_id'] == image_id
    mounts = []
    for source, target in TOOL_MOUNTS:
        assert Path(source).is_file()
        mounts.extend(['--mount', f'type=bind,src={source},dst={target},readonly'])
    command = docker + ['run', '--rm', '--network', 'none', *mounts,
                        '--entrypoint', 'sh', IMAGE, '-lc',
                        'tmux -V && tmux -L zhiyuan-fasttext-preflight '
                        'new-session -d -s probe "sleep 1" && '
                        'tmux -L zhiyuan-fasttext-preflight kill-server']
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and 'tmux 3.2a' in result.stdout
    PROOF.write_text(json.dumps({
        'utc': datetime.now(timezone.utc).isoformat(), 'cpu_allocation': 2919,
        'task_image': IMAGE, 'task_image_id': image_id,
        'image_identity_proof': str(IMAGES), 'image_identity_proof_sha256': sha(IMAGES),
        'network': 'none', 'model_requests': 0, 'task_attempts': 0,
        'mounts': [{'source': source, 'target': target, 'read_only': True,
                    'sha256': sha(Path(source))} for source, target in TOOL_MOUNTS],
        'stdout': result.stdout, 'returncode': result.returncode,
        'qualification': 'Harness tmux startup only; no model call or benchmark scoring.',
    }, indent=2) + '\n')
    print(json.dumps({'proof': str(PROOF), 'image_id': image_id,
                      'tmux': result.stdout.strip()}))


if __name__ == '__main__':
    main()
