#!/usr/bin/env python3
"""Keep CPU 2922's Docker disk usable by evicting completed Muse Pro task images."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / ('.private/muse_bf16_20261018/legacy_bench/pro-results/muse_bf16_full/'
                 'muse-spark-open-bf16_swebench_pro_verified_mini_swe_agent/'
                 'muse-bf16-pro-full-r1-resume-20261020/details')
LOG = BASE / '.private/muse_bf16_20261018/recovery_20261020/cpu-2922-image-guard.jsonl'
DISK = '/opt/sagemaker'
JOB_ID = '2922'
NODE_NAME = 'ip-10-1-69-250'
TRIGGER = 50 * 2**30
TARGET = 80 * 2**30


def digest(path):
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
        stream.flush()
    return event


def candidates():
    graded = {}
    for path in SOURCE.glob('*/attempt-1/result.json'):
        result = json.loads(path.read_text())
        evaluation = (((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {})
        if evaluation.get('completed') is not True:
            continue
        if not isinstance((result.get('metrics') or {}).get('correct'), bool):
            continue
        task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
        assert task not in graded
        graded[task] = (path, digest(path))
    images = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    images.check_returncode()
    eligible = []
    for line in images.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matches = [task for task in graded if task.removeprefix('instance_') in image['Tag']]
        if len(matches) != 1:
            continue
        task = matches[0]
        path, result_sha = graded[task]
        eligible.append((image['Repository'] + ':' + image['Tag'], image['ID'], task, path, result_sha))
    return eligible


def cycle():
    assert os.environ.get('SLURM_JOB_ID') == JOB_ID
    assert os.uname().nodename == NODE_NAME
    before = shutil.disk_usage(DISK).free
    if before >= TRIGGER:
        return record(event='healthy', free_gib=round(before / 2**30, 2))
    eligible = candidates()
    record(event='cleanup_start', free_gib=round(before / 2**30, 2), candidate_count=len(eligible))
    removed = 0
    refused = 0
    for reference, image_id, task, result_path, result_sha in eligible:
        if shutil.disk_usage(DISK).free >= TARGET:
            break
        inspect = docker('image', 'inspect', reference, '--format', '{{.Id}}')
        if inspect.returncode or inspect.stdout.strip() != image_id:
            record(event='skip_changed_image', reference=reference, expected_image_id=image_id)
            continue
        if not result_path.exists() or digest(result_path) != result_sha:
            record(event='skip_changed_result', reference=reference, task=task)
            continue
        outcome = docker('image', 'rm', reference)  # No --force; container references are protected.
        if outcome.returncode:
            refused += 1
        else:
            removed += 1
        record(event='remove_image_tag', reference=reference, image_id=image_id,
               task=task, result_sha256=result_sha, returncode=outcome.returncode,
               output_tail=(outcome.stdout + outcome.stderr)[-350:])
    after = shutil.disk_usage(DISK).free
    return record(event='cleanup_finish', free_gib_before=round(before / 2**30, 2),
                  free_gib_after=round(after / 2**30, 2),
                  recovered_gib=round((after - before) / 2**30, 2),
                  candidate_count=len(eligible), removed=removed, refused=refused,
                  target_reached=after >= TARGET)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    while True:
        print(json.dumps(cycle()), flush=True)
        if args.once:
            return
        time.sleep(180)


if __name__ == '__main__':
    main()
