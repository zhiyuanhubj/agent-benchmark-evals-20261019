#!/usr/bin/env python3
"""Reclaim CPU 2922 space from unused historical DeepSWE image tags."""

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/fsx/home/zhiyuan/agent-benchmark-evals-20261019')
PLAN = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/recovery_20261020/cpu-2922-ecr-prune-plan-20261021.json')
LOG = PLAN.with_name('cpu-2922-ecr-prune-20261021.jsonl')
SUMMARY = ROOT / 'evidence/cpu2922_unused_ecr_prune_20261021.json'
REPOSITORY = 'public.ecr.aws/d3j8x8q7/swe-bench-202605'
DISK = '/opt/sagemaker/docker/data-root'
TARGET_BYTES = 100 * 2**30


def docker(*args):
    env = os.environ.copy()
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    result = subprocess.run(['docker', '--host=unix:///var/run/docker.sock', *args],
                            env=env, capture_output=True, text=True, timeout=120)
    return result


def write_event(**fields):
    event = {'utc': datetime.now(timezone.utc).isoformat(), **fields}
    with LOG.open('a') as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event


def container_image_ids():
    ids = docker('ps', '-aq', '--no-trunc')
    ids.check_returncode()
    names = ids.stdout.split()
    if not names:
        return set()
    inspected = docker('inspect', *names, '--format', '{{.Image}}')
    inspected.check_returncode()
    return set(inspected.stdout.split())


def inventory():
    listed = docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    listed.check_returncode()
    used = container_image_ids()
    candidates = []
    for line in listed.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != REPOSITORY:
            continue
        if image['ID'] in used:
            continue
        candidates.append({'reference': image['Repository'] + ':' + image['Tag'],
                           'image_id': image['ID']})
    return sorted(candidates, key=lambda item: item['reference']), len(used)


def run():
    assert os.environ.get('SLURM_JOB_ID') == '2922'
    assert os.uname().nodename == 'ip-10-1-69-250'
    candidates, used_count = inventory()
    before = shutil.disk_usage(DISK).free
    plan = {'created_utc': datetime.now(timezone.utc).isoformat(),
            'node': os.uname().nodename, 'allocation': 2922,
            'repository': REPOSITORY, 'target_free_gib': TARGET_BYTES / 2**30,
            'free_gib_before': round(before / 2**30, 2),
            'container_image_id_count': used_count,
            'candidate_count': len(candidates), 'candidates': candidates,
            'rule': 'Only tags from the historical public ECR repository whose image IDs are not referenced by any current or stopped container; Docker image rm without force rechecks references.'}
    PLAN.write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps({k: plan[k] for k in ('free_gib_before', 'candidate_count', 'container_image_id_count')}), flush=True)
    return plan


def execute(plan):
    before = shutil.disk_usage(DISK).free
    removed = []
    refused = []
    write_event(event='begin', free_gib=round(before / 2**30, 2), candidate_count=len(plan['candidates']))
    for candidate in plan['candidates']:
        if shutil.disk_usage(DISK).free >= TARGET_BYTES:
            break
        reference = candidate['reference']
        image_id = candidate['image_id']
        current = docker('image', 'inspect', reference, '--format', '{{.Id}}')
        if current.returncode or current.stdout.strip() != image_id:
            refused.append({'reference': reference, 'reason': 'image changed or absent'})
            continue
        if image_id in container_image_ids():
            refused.append({'reference': reference, 'reason': 'container reference appeared'})
            continue
        try:
            outcome = docker('image', 'rm', reference)  # Never force, remove containers, or prune volumes.
        except subprocess.TimeoutExpired:
            refused.append({'reference': reference, 'reason': 'Docker removal timed out'})
            break
        row = {'reference': reference, 'image_id': image_id,
               'returncode': outcome.returncode,
               'free_gib_after': round(shutil.disk_usage(DISK).free / 2**30, 2),
               'output_tail': (outcome.stdout + outcome.stderr)[-300:]}
        write_event(event='remove_tag', **row)
        (removed if outcome.returncode == 0 else refused).append(row)
    after = shutil.disk_usage(DISK).free
    summary = {'generated_utc': datetime.now(timezone.utc).isoformat(),
               'node': plan['node'], 'allocation': plan['allocation'],
               'repository': REPOSITORY, 'target_free_gib': TARGET_BYTES / 2**30,
               'free_gib_before': round(before / 2**30, 2),
               'free_gib_after': round(after / 2**30, 2),
               'recovered_gib': round((after - before) / 2**30, 2),
               'candidate_count': len(plan['candidates']),
               'removed_count': len(removed), 'refused_count': len(refused),
               'removed_image_tags': [row['reference'] for row in removed],
               'qualification': plan['rule']}
    temp = SUMMARY.with_suffix('.json.tmp')
    temp.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    temp.replace(SUMMARY)
    write_event(event='finish', recovered_gib=summary['recovered_gib'],
                free_gib_after=summary['free_gib_after'], removed_count=len(removed),
                refused_count=len(refused))
    print(json.dumps({key: summary[key] for key in ('free_gib_before', 'free_gib_after',
                                                  'recovered_gib', 'removed_count', 'refused_count')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    plan = run()
    if args.execute:
        execute(plan)
