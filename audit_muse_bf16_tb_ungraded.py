#!/usr/bin/env python3
"""Freeze BF16 TB2.1 first-round failures before any infrastructure retry."""

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parent
SOURCE = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/legacy_bench')
RUN = SOURCE / 'tb-results/muse-bf16-tb-r1'
CONFIG = SOURCE / 'configs/tb-r1.template.json'
DIRECT = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/recovery_20261020/tb-r1-direct-2886-20261020-claim.json')
ENDPOINT = 'http://10.1.77.106:31324/v1'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


config = json.loads(CONFIG.read_text())
tasks = {Path(task['path']).name for task in config.get('config', config)['tasks']}
assert len(tasks) == 89
direct = json.loads(DIRECT.read_text())
assert len(direct['tasks']) == 16 and set(direct['tasks']) <= tasks

rows = {}
graded = 0
seen = set()
for result_path in RUN.glob('*/result.json'):
    result = json.loads(result_path.read_text())
    assert result.get('finished_at'), result_path
    task = Path(result['config']['task']['path']).name
    assert task in tasks and task not in seen
    seen.add(task)
    assert result['config']['agent']['kwargs']['api_base'] == ENDPOINT
    reward = (result.get('verifier_result') or {}).get('rewards', {}).get('reward')
    if reward in (0, 1):
        graded += 1
        continue
    exception = result.get('exception_info') or {}
    assert exception.get('exception_type') in {'RuntimeError', 'InternalServerError'}
    raw_files = list((result_path.parent / 'agent/raw_responses').glob('*.json'))
    trajectory = result_path.parent / 'agent/trajectory.json'
    steps = json.loads(trajectory.read_text()).get('steps', []) if trajectory.exists() else []
    agent_steps = sum(step.get('source') == 'agent' for step in steps)
    pre_model = not raw_files and agent_steps == 0
    patch_files = list(result_path.parent.rglob('model.patch'))
    if pre_model:
        assert not any(path.stat().st_size for path in patch_files)
    rows[task] = {
        'source_result': str(result_path),
        'source_result_sha256': digest(result_path),
        'exception_type': exception['exception_type'],
        'exception_message': (exception.get('exception_message') or '')[:250],
        'raw_response_count': len(raw_files),
        'agent_trajectory_steps': agent_steps,
        'trajectory_sha256': digest(trajectory) if trajectory.exists() else None,
        'patch_files': [{'path': str(path), 'size': path.stat().st_size} for path in patch_files],
        'classification': 'pre_model_infrastructure_failure' if pre_model else 'interrupted_after_model_output',
    }

assert graded == 41 and len(rows) == 32
assert Counter(row['classification'] for row in rows.values()) == {
    'pre_model_infrastructure_failure': 30,
    'interrupted_after_model_output': 2,
}
assert not set(rows).intersection(direct['tasks'])
report = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'source_run': str(RUN),
    'source_config': str(CONFIG),
    'source_config_sha256': digest(CONFIG),
    'source_endpoint': ENDPOINT,
    'expected_tasks': 89,
    'source_terminal': graded + len(rows),
    'source_graded': graded,
    'source_ungraded': len(rows),
    'pre_model_infrastructure_failures': 30,
    'interrupted_after_model_output': 2,
    'qualification': 'Read-only frozen audit. Zero raw model replies and zero agent trajectory steps define pre-model failures; this audit itself does not resample, replace, or score any task.',
    'ungraded_tasks': rows,
}
target = ROOT / 'evidence/muse_bf16_tb_ungraded_audit.json'
if target.exists():
    previous = json.loads(target.read_text())
    report['generated_utc'] = previous['generated_utc']
    assert report == previous, 'Frozen BF16 TB2.1 failure audit changed'
else:
    target.write_text(json.dumps(report, indent=2) + '\n')
print(target)
