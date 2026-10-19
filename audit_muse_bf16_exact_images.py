#!/usr/bin/env python3
"""Verify that the existing BF16 TB run used the supplied 89 image identities."""

import hashlib
import json
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BF = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018')
EXACT = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019')
PLAN = EXACT / 'image-identity-plan.json'
RECEIPT = BF / 'legacy_bench/state/muse-bf16-full89-images-ready.json'
LAUNCH = BF / 'legacy_bench/state/tb-r1-launch.json'
CONFIG = BF / 'legacy_bench/configs/tb-r1.json'
OUT = ROOT / 'evidence/muse_bf16_exact_image_identity.json'


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_check(plan):
    tags = [row['tag'] for row in plan['images']]
    images = json.loads(subprocess.check_output(['docker', 'image', 'inspect', *tags]))
    by_tag = {tag: row for row in images for tag in row.get('RepoTags', [])}
    bad = []
    for expected in plan['images']:
        row = by_tag.get(expected['tag'])
        good = row and row['Id'] in (
            expected['index_or_manifest_digest'], expected['manifest_digest'], expected['config_digest']
        ) and row['RootFS']['Layers'] == expected['rootfs_diff_ids'] and {
            key: row['Config'].get(key) for key in plan['runtime_config_keys']
        } == expected['runtime_config']
        if not good:
            bad.append(expected['tag'])
    return {'utc': datetime.now(timezone.utc).isoformat(), 'node': socket.gethostname().split('.')[0],
            'checked': len(tags), 'mismatched_tags': bad, 'plan_sha256': sha(PLAN)}


def normalize(config):
    value = json.loads(json.dumps(config))
    for key in ('job_name', 'jobs_dir', 'n_concurrent_trials', 'tasks'):
        value.pop(key)
    agent = value['agents'][0]
    agent.pop('model_name')
    agent['kwargs'].pop('api_base')
    return value


if __name__ == '__main__':
    if '--worker' in sys.argv:
        print(json.dumps(image_check(load(PLAN))))
        raise SystemExit(0)

    plan, receipt, launch, config = map(load, (PLAN, RECEIPT, LAUNCH, CONFIG))
    source_configs = [load(EXACT / f'muse_nvfp4/configs/r1-shard{i}.json') for i in (1, 2, 3)]
    by_tag = {row['tag']: row for row in receipt['images']}
    errors = []
    if len(plan['images']) != plan['image_count'] or plan['image_count'] != 89:
        errors.append('supplied image plan is not 89 unique images')
    if len(by_tag) != len(receipt['images']) or len(by_tag) != 89:
        errors.append('BF16 prelaunch receipt is not 89 unique images')
    if not receipt.get('all_archive_identities_verified') or receipt.get('model_requests') != 0:
        errors.append('BF16 image preparation did not precede model sampling')
    if receipt['utc'] >= launch['utc']:
        errors.append('BF16 image receipt is not earlier than TB launch')
    for expected in plan['images']:
        row = by_tag.get(expected['tag'])
        if not row or row['image_id'] not in (
            expected['index_or_manifest_digest'], expected['manifest_digest'], expected['config_digest']
        ) or row['rootfs_diff_ids'] != expected['rootfs_diff_ids'] or row['runtime_config_sha256'] != expected['runtime_config_sha256']:
            errors.append(f"BF16 image identity mismatch: {expected['tag']}")
    bf_tasks = [row['path'] for row in config['tasks']]
    exact_tasks = [row['path'] for source in source_configs for row in source['tasks']]
    if len(bf_tasks) != len(set(bf_tasks)) or set(bf_tasks) != set(exact_tasks) or len(bf_tasks) != 89:
        errors.append('BF16 and exact-image task lists differ')
    if any(normalize(config) != normalize(source) for source in source_configs):
        errors.append('BF16 and exact-image Harbor sampling settings differ beyond endpoint, model and concurrency')
    bf_agent = BF / 'legacy_bench/archived_terminus.py'
    exact_agent = EXACT / 'muse_nvfp4/archived_terminus.py'
    if sha(bf_agent) != sha(exact_agent):
        errors.append('BF16 and exact-image agent implementations differ')
    if not str(config['agents'][0]['kwargs']['api_base']).startswith('http://10.1.77.106:31324/v1'):
        errors.append('BF16 TB config does not use the pinned BF16 endpoint')
    if not launch['command'][-1] == str(CONFIG):
        errors.append('BF16 launch did not use audited config')

    previous = load(OUT) if OUT.exists() else {}
    live = previous.get('live_node_check')
    if '--live' in sys.argv:
        command = ['srun', '--jobid=2865', '--overlap', '--gres=none', '-N1', '-n1', '-c1', '--immediate=5',
                   '/usr/bin/python3', str(Path(__file__).resolve()), '--worker']
        result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=True)
        live = json.loads(result.stdout.strip().splitlines()[-1])
    if live and (live['node'] != receipt['host'] or live['checked'] != 89 or live['mismatched_tags']
                 or live['plan_sha256'] != sha(PLAN) or live['utc'] < datetime.fromtimestamp(launch['utc'], timezone.utc).isoformat()):
        errors.append('live BF16 node image inspection does not confirm the supplied 89 images')
    if not live:
        errors.append('live BF16 node image inspection is missing')

    audit = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'expected_images': 89,
             'prelaunch_receipt_images': len(receipt['images']), 'matching_image_identities': 89 - sum(
                 error.startswith('BF16 image identity mismatch:') for error in errors),
             'matching_task_paths': len(set(bf_tasks) & set(exact_tasks)),
             'receipt_utc': datetime.fromtimestamp(receipt['utc'], timezone.utc).isoformat(),
             'launch_utc': datetime.fromtimestamp(launch['utc'], timezone.utc).isoformat(),
             'bf16_node': receipt['host'], 'live_node_check': live,
             'agent_sha256': sha(bf_agent), 'source_sha256': {str(path): sha(path) for path in
                 (PLAN, RECEIPT, LAUNCH, CONFIG, bf_agent, exact_agent)}, 'errors': errors,
             'same_trials_as_legacy_named_bf16_tb': True,
             'qualification': 'Image and task identity audit; current partial rewards are not a full-round accuracy.'}
    OUT.write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({'matched': audit['matching_image_identities'], 'errors': errors}))
    raise SystemExit(1 if errors else 0)
