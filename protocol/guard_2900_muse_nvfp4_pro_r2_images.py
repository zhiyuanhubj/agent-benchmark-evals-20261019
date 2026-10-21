#!/usr/bin/env python3
"""Evict only completed, graded Pro task images from Muse NVFP4 node 2900."""

import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/pro_round2_20261021')
STATE = ROOT / 'shard0-2900'
DETAILS = (ROOT / 'results/muse-pro-r2/'
           'muse-spark-open-nvfp4_swebench_pro_verified_mini_swe_agent/'
           'muse-nvfp4-pro-r2-shard0-2900/details')
LOG = STATE / 'image-guard.jsonl'
TRIGGER = 150 * 2**30
TARGET = 350 * 2**30


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
                          env=env, capture_output=True, text=True, timeout=90)


def record(**fields):
    event = {'utc': datetime.now(timezone.utc).isoformat(), **fields}
    with LOG.open('a') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
    print(json.dumps(event, ensure_ascii=False), flush=True)


def candidates():
    graded = {}
    for path in DETAILS.glob('*/attempt-1/result.json'):
        result = json.loads(path.read_text())
        evaluation = (((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {})
        if evaluation.get('completed') is not True:
            continue
        if not isinstance((result.get('metrics') or {}).get('correct'), bool):
            continue
        task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
        assert task not in graded
        graded[task] = (path, sha(path))
    image_list = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    image_list.check_returncode()
    eligible = []
    for line in image_list.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matches = [task for task in graded if task.removeprefix('instance_') in image['Tag']]
        if len(matches) == 1:
            task = matches[0]
            path, result_sha = graded[task]
            eligible.append((image['Repository'] + ':' + image['Tag'], image['ID'],
                             task, path, result_sha))
    return eligible


def cycle():
    assert os.environ.get('SLURM_JOB_ID') == '2900'
    assert os.uname().nodename == 'ip-10-1-101-159'
    before = shutil.disk_usage('/opt/dlami/nvme').free
    if before >= TRIGGER:
        record(event='healthy', free_gib=round(before / 2**30, 1))
        return
    eligible = candidates()
    record(event='cleanup_start', free_gib=round(before / 2**30, 1), candidates=len(eligible))
    removed = 0
    for reference, image_id, task, result_path, result_sha in eligible:
        if shutil.disk_usage('/opt/dlami/nvme').free >= TARGET:
            break
        inspect = docker('image', 'inspect', reference, '--format', '{{.Id}}')
        if inspect.returncode or inspect.stdout.strip() != image_id:
            continue
        if not result_path.exists() or sha(result_path) != result_sha:
            continue
        outcome = docker('image', 'rm', reference)  # No --force; active containers stay protected.
        record(event='remove_image_tag', reference=reference, task=task,
               result_sha256=result_sha, returncode=outcome.returncode,
               output_tail=(outcome.stdout + outcome.stderr)[-250:])
        removed += outcome.returncode == 0
    after = shutil.disk_usage('/opt/dlami/nvme').free
    record(event='cleanup_finish', before_gib=round(before / 2**30, 1),
           after_gib=round(after / 2**30, 1), removed=removed)


if __name__ == '__main__':
    assert STATE.joinpath('claim.json').is_file()
    while True:
        cycle()
        if STATE.joinpath('exit.json').exists():
            break
        time.sleep(180)
