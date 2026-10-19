#!/usr/bin/env python3
"""Release only completed BF16 SWE-Review task images on its owned sandbox host."""

import hashlib
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/review_bench/queue')
RECEIPTS = ROOT / 'image-cleanups'
RECEIPTS.mkdir(exist_ok=True)
assert socket.gethostname() == 'ip-10-1-122-30'
DOCKER_ENV = dict(os.environ)
for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
    DOCKER_ENV.pop(key, None)


def docker(*args, capture=False):
    try:
        return subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
            env=DOCKER_ENV, capture_output=capture,
            stdout=None if capture else subprocess.DEVNULL,
            stderr=None if capture else subprocess.DEVNULL,
            text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return None


def save(path, data):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def task_image(split, task):
    receipt = ROOT / 'task-receipts' / f'{split}--{task}.json'
    row = json.loads(receipt.read_text())
    tag = row['image_tag']
    assert tag.startswith('zhiyuan-review-frozen:')
    return tag, row['image_id'], receipt


def owned_host_running():
    state = subprocess.check_output(['squeue', '-u', 'zhiyuan', '-h', '-j', '2886',
        '-o', '%T|%N'], text=True, timeout=15).strip()
    assert state == 'RUNNING|ip-10-1-13-41,ip-10-1-122-30', state


def free_bytes():
    stat = os.statvfs('/opt/dlami/nvme')
    return stat.f_bavail * stat.f_frsize


while True:
    owned_host_running()
    active_tags = set()
    for claim in sorted((ROOT / 'claims').glob('*.json')):
        if (ROOT / 'exits' / claim.name).exists():
            continue
        record = json.loads(claim.read_text())
        split = claim.stem.rsplit('-', 1)[0]
        for task in record['tasks']:
            active_tags.add(task_image(split, task)[0])

    released = 0
    pending = 0
    for exit_path in sorted((ROOT / 'exits').glob('*.json')):
        exit_record = json.loads(exit_path.read_text())
        if exit_record['returncode'] != 0:
            continue  # Keep every image for an interrupted or failed native batch.
        name = exit_path.stem
        claim_path = ROOT / 'claims' / f'{name}.json'
        claim = json.loads(claim_path.read_text())
        split = name.rsplit('-', 1)[0]
        cleanup_path = RECEIPTS / f'{name}.json'
        previous = json.loads(cleanup_path.read_text()) if cleanup_path.exists() else {}
        if previous.get('phase') == 'images_released':
            continue
        rows = []
        for task in claim['tasks']:
            tag, image_id, receipt = task_image(split, task)
            if tag in active_tags:
                rows.append(dict(task=task, tag=tag, image_id=image_id,
                                 task_receipt=str(receipt), status='active_elsewhere'))
                pending += 1
                continue
            inspect = docker('image', 'inspect', tag)
            if inspect is None:
                status = 'daemon_timeout'
            elif inspect.returncode:
                status = 'already_absent'
            else:
                outcome = docker('image', 'rm', tag, capture=True)
                status = 'removed' if outcome and outcome.returncode == 0 else 'in_use_or_daemon_error'
            rows.append(dict(task=task, tag=tag, image_id=image_id,
                             task_receipt=str(receipt), status=status))
            if status in ('removed', 'already_absent'):
                released += 1
            else:
                pending += 1
        phase = 'images_released' if all(row['status'] in ('removed', 'already_absent') for row in rows) else 'retry_pending'
        save(cleanup_path, dict(utc=datetime.now(timezone.utc).isoformat(), phase=phase,
            native_exit_sha256=hashlib.sha256(exit_path.read_bytes()).hexdigest(),
            batch=name, native_returncode=0,
            model_results_preserved=True, task_inputs_preserved=True,
            after_scoring_only=True, rows=rows, available_disk_bytes=free_bytes()))
    save(RECEIPTS / 'current.json', dict(utc=datetime.now(timezone.utc).isoformat(),
        released_in_cycle=released, pending_in_cycle=pending,
        completed_batch_receipts=sum(p.name != 'current.json' for p in RECEIPTS.glob('*.json')),
        available_disk_bytes=free_bytes()))
    time.sleep(30)
