#!/usr/bin/env python3
"""Free 2919 Docker space only for Pro images graded by both active model runs."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
BEAM = BASE / '.private/beam_20261018/legacy_bench_20261018'
MUSE = BASE / '.private/muse_bf16_20261018/legacy_bench/pro-results'
STATE = BASE / '.private/muse_bf16_20261018/recovery_20261020'
PLAN = STATE / 'cpu-2919-double-completed-image-prune-v2-plan.json'
LOG = STATE / 'cpu-2919-double-completed-image-prune-v2.jsonl'
SUMMARY = BASE / 'agent-benchmark-evals-20261019/evidence/cpu_2919_double_completed_image_prune_v2.json'
DISK = '/opt/sagemaker'
TARGET_FREE = 80 * 2**30


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS',
                'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
                          env=env, capture_output=True, text=True, timeout=90)


def graded(roots, excluded=()):
    records = {}
    for root in roots:
        for path in root.glob('**/attempt-1/result.json'):
            if any(name in path.parts for name in excluded):
                continue
            result = json.loads(path.read_text())
            evaluation = (((result.get('meta') or {}).get('benchmark') or {})
                          .get('eval_raw_data') or {})
            if evaluation.get('completed') is not True:
                continue
            if not isinstance((result.get('metrics') or {}).get('correct'), bool):
                continue
            task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
            records.setdefault(task, []).append({'result': str(path), 'result_sha256': sha(path)})
    return records


def event(**fields):
    with LOG.open('a') as stream:
        stream.write(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), **fields}) + '\n')
        stream.flush()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    assert not PLAN.exists() and not LOG.exists() and not SUMMARY.exists()
    before = shutil.disk_usage(DISK)
    assert before.free < 60 * 2**30, 'No current disk pressure'
    beam = graded((BEAM / 'pro-results', BEAM / 'remaining_pro/pro-results'),
                  ('beam_pro_full731_round2_2888_20261020',))
    muse = graded((MUSE,))
    both = set(beam) & set(muse)
    assert len(both) >= 100
    images_result = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    images_result.check_returncode()
    candidates = []
    for line in images_result.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matching = [task for task in both if task.removeprefix('instance_') in image['Tag']]
        if len(matching) != 1:
            continue
        task = matching[0]
        candidates.append({
            'repository': image['Repository'], 'tag': image['Tag'],
            'image_id': image['ID'], 'reported_size': image['Size'],
            'task': task, 'beam_native_results': beam[task],
            'muse_native_results': muse[task],
        })
    assert len(candidates) >= 20
    PLAN.write_text(json.dumps({
        'utc': datetime.now(timezone.utc).isoformat(), 'cpu_allocation': 2919,
        'free_bytes_before': before.free, 'target_free_bytes': TARGET_FREE,
        'candidate_count': len(candidates), 'candidates': candidates,
        'policy': 'Only image tags whose task has native grades from both Beam and Muse BF16 Pro. No --force, no container or result deletion. Docker refuses referenced layers.',
    }, indent=2) + '\n')
    event(event='start', candidate_count=len(candidates), free_bytes=before.free)
    attempted = succeeded = 0
    for item in candidates:
        if shutil.disk_usage(DISK).free >= TARGET_FREE:
            break
        for row in (*item['beam_native_results'], *item['muse_native_results']):
            assert sha(Path(row['result'])) == row['result_sha256']
        reference = item['repository'] + ':' + item['tag']
        outcome = docker('image', 'rm', reference)
        attempted += 1
        succeeded += outcome.returncode == 0
        event(event='remove_image_tag', image_id=item['image_id'], reference=reference,
              task=item['task'], returncode=outcome.returncode,
              output_tail=(outcome.stdout + outcome.stderr)[-350:],
              free_bytes=shutil.disk_usage(DISK).free)
    after = shutil.disk_usage(DISK)
    event(event='finish', free_bytes=after.free,
          recovered_bytes=after.free - before.free, target_reached=after.free >= TARGET_FREE)
    summary = {
        'utc': datetime.now(timezone.utc).isoformat(),
        'cpu_allocation': 2919, 'plan': str(PLAN), 'plan_sha256': sha(PLAN),
        'log': str(LOG), 'log_sha256': sha(LOG),
        'candidate_count': len(candidates), 'attempted': attempted,
        'succeeded': succeeded, 'free_bytes_before': before.free,
        'free_bytes_after': after.free, 'recovered_bytes': after.free - before.free,
        'target_reached': after.free >= TARGET_FREE,
        'containers_or_results_deleted': False,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: summary[k] for k in ('candidate_count', 'attempted',
                                               'succeeded', 'recovered_bytes',
                                               'free_bytes_after', 'target_reached')}))


if __name__ == '__main__':
    main()
