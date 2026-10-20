#!/usr/bin/env python3
"""Free CPU 2922 Docker space using only completed Muse Pro image tags."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
STATE = BASE / '.private/muse_bf16_20261018/recovery_20261020'
SOURCE = BASE / ('.private/muse_bf16_20261018/legacy_bench/pro-results/muse_bf16_full/'
                 'muse-spark-open-bf16_swebench_pro_verified_mini_swe_agent/'
                 'muse-bf16-pro-full-r1-resume-20261020/details')
PLAN = STATE / 'cpu-2922-image-prune-plan.json'
LOG = STATE / 'cpu-2922-image-prune.jsonl'
DISK = '/opt/sagemaker'
TARGET = 80 * 2**30


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
                          env=env, capture_output=True, text=True, timeout=90)


def event(**fields):
    with LOG.open('a') as stream:
        stream.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), **fields}) + '\n')
        stream.flush()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2922'
    assert not PLAN.exists() and not LOG.exists()
    before = shutil.disk_usage(DISK)
    assert before.free < 60 * 2**30
    graded = {}
    for path in SOURCE.glob('*/attempt-1/result.json'):
        result = json.loads(path.read_text())
        evaluation = (((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {})
        if evaluation.get('completed') is not True:
            continue
        if not isinstance((result.get('metrics') or {}).get('correct'), bool):
            continue
        task_file = path.parent.parent / 'task.json'
        task = json.loads(task_file.read_text())['task_id']
        assert task not in graded
        graded[task] = {'result': str(path), 'result_sha256': digest(path)}
    listing = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    listing.check_returncode()
    candidates = []
    for line in listing.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matches = [task for task in graded if task.removeprefix('instance_') in image['Tag']]
        if len(matches) == 1:
            task = matches[0]
            candidates.append({'repository': image['Repository'], 'tag': image['Tag'],
                               'image_id': image['ID'], 'native_graded_task': task,
                               **graded[task]})
    assert len(candidates) >= 10
    PLAN.write_text(json.dumps({
        'utc': datetime.now(timezone.utc).isoformat(), 'cpu_allocation': 2922,
        'free_bytes_before': before.free, 'target_free_bytes': TARGET,
        'candidate_count': len(candidates), 'candidates': candidates,
        'policy': 'Remove only image tags for already-native-graded Muse BF16 Pro tasks, without --force. Docker refuses active container references. Preserve all containers and result files.',
    }, indent=2) + '\n')
    event(event='start', candidates=len(candidates), free_bytes=before.free)
    for item in candidates:
        if shutil.disk_usage(DISK).free >= TARGET:
            break
        reference = item['repository'] + ':' + item['tag']
        outcome = docker('image', 'rm', reference)
        event(event='remove_image_tag', reference=reference, image_id=item['image_id'],
              task=item['native_graded_task'], returncode=outcome.returncode,
              output_tail=(outcome.stdout + outcome.stderr)[-350:],
              free_bytes=shutil.disk_usage(DISK).free)
    after = shutil.disk_usage(DISK)
    event(event='finish', free_bytes=after.free,
          recovered_bytes=after.free - before.free, target_reached=after.free >= TARGET)
    print(json.dumps({'candidate_count': len(candidates),
                      'recovered_gib': round((after.free - before.free) / 2**30, 2),
                      'free_gib': round(after.free / 2**30, 2),
                      'target_reached': after.free >= TARGET}))


if __name__ == '__main__':
    main()
