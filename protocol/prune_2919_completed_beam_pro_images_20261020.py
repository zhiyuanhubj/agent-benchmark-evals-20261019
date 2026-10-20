#!/usr/bin/env python3
"""Recover CPU sandbox space from completed, graded Beam Pro task images.

Only image tags for completed round-one task IDs are considered. Docker refuses
to remove images still referenced by containers. No containers or results are
deleted; source image IDs and native grades are recorded before removal.
"""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/legacy_bench_20261018'
STATE = BASE / '.private/muse_bf16_20261018/recovery_20261020'
PLAN = STATE / 'cpu-2919-image-prune-plan.json'
LOG = STATE / 'cpu-2919-image-prune.jsonl'
DISK = '/opt/sagemaker'
MIN_FREE = 80 * 2**30


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS',
                'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
                          env=env, capture_output=True, text=True, timeout=90)


def write_event(**fields):
    with LOG.open('a') as stream:
        stream.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(),
                                 **fields}) + '\n')
        stream.flush()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    assert not PLAN.exists() and not LOG.exists()
    before = shutil.disk_usage(DISK)
    assert before.free < 5 * 2**30, 'Disk pressure already resolved; no prune needed'
    graded = {}
    for root in (ROOT / 'pro-results', ROOT / 'remaining_pro/pro-results'):
        for path in root.glob('**/attempt-1/result.json'):
            if 'beam_pro_full731_round2_2888_20261020' in path.parts:
                continue
            result = json.loads(path.read_text())
            evaluation = (((result.get('meta') or {}).get('benchmark') or {})
                          .get('eval_raw_data') or {})
            if evaluation.get('completed') is not True:
                continue
            if not isinstance((result.get('metrics') or {}).get('correct'), bool):
                continue
            task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
            assert task not in graded, f'Duplicate native grade: {task}'
            graded[task] = {'result': str(path), 'result_sha256': sha(path)}
    images_result = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    images_result.check_returncode()
    images = [json.loads(line) for line in images_result.stdout.splitlines()]
    candidates = []
    for image in images:
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matching = [task for task in graded if task.removeprefix('instance_') in image['Tag']]
        if len(matching) == 1:
            candidates.append({'repository': image['Repository'], 'tag': image['Tag'],
                               'image_id': image['ID'], 'reported_size': image['Size'],
                               'native_graded_task': matching[0],
                               **graded[matching[0]]})
    assert len(candidates) >= 20
    PLAN.write_text(json.dumps({
        'utc': datetime.now(timezone.utc).isoformat(), 'cpu_allocation': 2919,
        'disk': DISK, 'free_bytes_before': before.free, 'target_free_bytes': MIN_FREE,
        'candidate_count': len(candidates), 'candidates': candidates,
        'policy': 'Remove only jefzda image tags belonging to already-native-graded Beam Pro round-one tasks; no --force, no containers or result files removed.',
    }, indent=2) + '\n')
    write_event(event='start', candidate_count=len(candidates), free_bytes=before.free)
    for candidate in candidates:
        if shutil.disk_usage(DISK).free >= MIN_FREE:
            break
        reference = candidate['repository'] + ':' + candidate['tag']
        outcome = docker('image', 'rm', reference)
        write_event(event='remove_image_tag', image_id=candidate['image_id'],
                    reference=reference, task=candidate['native_graded_task'],
                    returncode=outcome.returncode,
                    output_tail=(outcome.stdout + outcome.stderr)[-350:],
                    free_bytes=shutil.disk_usage(DISK).free)
    after = shutil.disk_usage(DISK)
    write_event(event='finish', free_bytes=after.free,
                recovered_bytes=after.free - before.free,
                target_reached=after.free >= MIN_FREE)
    print(json.dumps({'candidate_count': len(candidates),
                      'recovered_gib': round((after.free - before.free)/2**30, 2),
                      'free_gib': round(after.free/2**30, 2),
                      'target_reached': after.free >= MIN_FREE}))


if __name__ == '__main__':
    main()
