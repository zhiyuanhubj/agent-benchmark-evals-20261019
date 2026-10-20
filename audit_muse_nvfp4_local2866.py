#!/usr/bin/env python3
"""Reconcile the original-node backfill routes with exact native task ownership."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = BASE / 'muse_nvfp4'
STATE = WORK / 'state'
PROTOCOL = ROOT / 'protocol/muse_nvfp4_local2866'
TARGET = ROOT / 'evidence/muse_nvfp4_local2866_route_audit.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


for name in ('route_future_rounds.py', 'future_round_controller.py', 'harbor_entry.py'):
    assert digest(WORK / name) == digest(PROTOCOL / name), f'Published controller differs: {name}'
ready = STATE / 'extra_gpu/2866-ready.json'
assert digest(ready) == digest(ROOT / 'evidence/muse_nvfp4_local2866_ready.json')
proof = json.loads(ready.read_text())
assert proof['job'] == 2866 and proof['phase'] == 'ready'
assert proof['endpoint'] == 'http://10.1.95.27:31320/v1'
assert any(item.get('id') == 'muse-spark-open-nvfp4' for item in proof['model_check']['data'])
plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
plan_rows = {item['job_name']: item for item in plan['configurations']}
claimed_tasks = set()
routes = []
for path in sorted((STATE / 'future-routes').glob('r[23]-completion-2866-b*-route.json')):
    route = json.loads(path.read_text())
    if route['allocation'] != 2866:
        continue
    row = plan_rows[route['job_name']]
    original = Path(route['original_config'])
    effective = Path(route['effective_config'])
    owner = STATE / f'{original.stem}-extra-owner.json'
    owner_data = json.loads(owner.read_text())
    assert row['round'] == route['round'] and row['tasks'] == route['tasks']
    assert row['sha256'] == digest(original) == route['original_sha256']
    assert digest(effective) == route['effective_sha256']
    assert route['endpoint'] == proof['endpoint'] and route['lane'] == owner_data['lane'] == 10
    assert owner_data['destination_allocation'] == 2866 and owner_data['tasks'] == row['tasks']
    assert not (STATE / 'future-routes' / f'{original.stem}-local-started.json').exists()
    expected = json.loads(original.read_text())
    expected['agents'][0]['kwargs']['api_base'] = proof['endpoint']
    assert json.loads(effective.read_text()) == expected
    assert not (set(row['tasks']) & claimed_tasks), 'Same task claimed by two local routes'
    claimed_tasks.update(row['tasks'])
    trial_dir = BASE / 'results/muse_nvfp4' / row['job_name']
    trial_names = [item.name.split('__', 1)[0] for item in trial_dir.glob('*__*') if item.is_dir()]
    assert len(trial_names) == len(set(trial_names))
    assert set(trial_names) <= set(row['tasks'])
    terminal = graded = success = 0
    for result_path in trial_dir.glob('*/result.json'):
        result = json.loads(result_path.read_text())
        task = Path(result['config']['task']['path']).name
        assert task in row['tasks'] and result['config']['agent']['kwargs']['api_base'] == proof['endpoint']
        if result.get('finished_at'):
            terminal += 1
            reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
            graded += reward in (0, 1)
            success += reward == 1
    routes.append(dict(job_name=row['job_name'], round=row['round'], task_count=len(row['tasks']),
                       route_sha256=digest(path), original_config_sha256=digest(original),
                       effective_config_sha256=digest(effective), owner_sha256=digest(owner),
                       trial_dirs=len(trial_names), terminal=terminal, graded=graded, success=success))
assert routes, 'Local 2866 lane has not claimed any untouched batch'
TARGET.write_text(json.dumps(dict(
    generated_utc=datetime.now(timezone.utc).isoformat(),
    scope='Original Muse NVFP4 GPU allocation 2866 exact-image TB2.1 round-2/3 local backfill.',
    ready_proof='evidence/muse_nvfp4_local2866_ready.json', ready_proof_sha256=digest(ready),
    controller_source='protocol/muse_nvfp4_local2866',
    route_count=len(routes), claimed_task_count=len(claimed_tasks), routes=routes,
    qualification='Each local route atomically owns a disjoint untouched frozen task batch; the effective config differs only by endpoint, which equals the original Muse NVFP4 endpoint. Native results count only when terminal and graded.'
), ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(routes=len(routes), claimed_tasks=len(claimed_tasks),
                      terminal=sum(row['terminal'] for row in routes))))
