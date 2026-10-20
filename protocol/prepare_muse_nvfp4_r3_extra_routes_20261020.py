#!/usr/bin/env python3
"""Reserve six untouched round-3 infrastructure replacements for two replicas."""

import hashlib
import json
import time
from pathlib import Path


SOURCE = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019')
WORK = SOURCE / 'muse_nvfp4'
STATE = WORK / 'state/r3-infra-replacement-2900'
CONFIGS = WORK / 'configs'
RESULTS = SOURCE / 'results/muse_nvfp4'
ALLOCATIONS = {3: 2869, 4: 2899, 5: 2869, 6: 2899, 7: 2869, 8: 2899}
ENDPOINTS = {2869: 'http://10.1.77.106:31321/v1',
             2899: 'http://10.1.114.210:31321/v1'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan_path = STATE / 'plan.json'
    plan = json.loads(plan_path.read_text())
    assert plan['expected_tasks'] == 89 and len(plan['batches']) == 9
    assert plan['endpoint'] == 'http://10.1.101.159:31321/v1'
    route_dir = STATE / 'extra-routes-20261020'
    assert not route_dir.exists(), 'Existing routes require reconciliation'
    for batch in plan['batches'][3:]:
        number = batch['index']
        assert number in ALLOCATIONS
        assert not (STATE / f'b{number:02}-started.json').exists()
        assert not (RESULTS / batch['job_name']).exists()
        assert sha(Path(batch['effective_config'])) == batch['effective_config_sha256']
        assert len(batch['tasks']) == (9 if number == 8 else 10)
    route_dir.mkdir()
    for batch in plan['batches'][3:]:
        number = batch['index']
        allocation = ALLOCATIONS[number]
        job_root = RESULTS / batch['job_name']
        original = Path(batch['effective_config'])
        routed = CONFIGS / f'r3-infra-replacement-route-{allocation}-b{number:02}.json'
        receipt = route_dir / f'b{number:02}.json'
        assert not routed.exists() and not receipt.exists()
        config = json.loads(original.read_text())
        assert config['job_name'] == batch['job_name']
        assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
        assert config['agents'][0]['kwargs']['api_base'] == plan['endpoint']
        config['agents'][0]['kwargs']['api_base'] = ENDPOINTS[allocation]
        # Reserving this job directory prevents the original lane from
        # launching a duplicate draw after its current batch completes.
        job_root.mkdir()
        assert not (STATE / f'b{number:02}-started.json').exists(), \
            'Original lane crossed the reservation boundary; reconcile before launch'
        routed.write_text(json.dumps(config, indent=2) + '\n')
        receipt.write_text(json.dumps({
            'utc': time.time(), 'batch': number, 'allocation': allocation,
            'job_name': batch['job_name'], 'job_root': str(job_root),
            'original_plan': str(plan_path), 'original_plan_sha256': sha(plan_path),
            'original_effective_config': str(original),
            'original_effective_config_sha256': batch['effective_config_sha256'],
            'routed_config': str(routed), 'routed_config_sha256': sha(routed),
            'endpoint': ENDPOINTS[allocation], 'task_count': len(batch['tasks']),
            'policy': 'One original attempt and one replacement only; route changes only api_base. Original lane is fenced by reserved job_root.',
        }, indent=2) + '\n')
        print(f'b{number:02} -> {allocation}: {len(batch["tasks"])} tasks', flush=True)


if __name__ == '__main__':
    main()
