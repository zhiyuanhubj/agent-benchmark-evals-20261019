#!/usr/bin/env python3
"""Count native Muse BF16 SWE-Review outcomes without treating them as DA/RRR."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
QUEUE = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/review_bench/queue')
EVIDENCE = ROOT / 'evidence/muse_bf16_swe_review_progress.json'
PLAN = QUEUE / 'queue-plan.json'


def main():
    plan = json.loads(PLAN.read_text())
    assert plan['model_id'] == 'muse-spark-open-bf16'
    report = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Original Muse BF16 SWE-Review native task outcomes; progress only, not official DA or RRR.',
        'queue_plan_sha256': hashlib.sha256(PLAN.read_bytes()).hexdigest(),
        'model_id': plan['model_id'],
        'splits': {},
        'errors': [],
    }
    for split, spec in plan['splits'].items():
        expected = set(spec['tasks'])
        assert len(expected) == len(spec['tasks']), f'duplicate planned task: {split}'
        records = {}
        for path in sorted((QUEUE / 'results' / split).glob('*/*/result.json')):
            row = json.loads(path.read_text())
            task = row.get('task_name')
            if task not in expected:
                report['errors'].append(f'{split}: unexpected native task {task}')
                continue
            if task in records:
                report['errors'].append(f'{split}: duplicate native result {task}')
                continue
            if row.get('task_id', {}).get('path') != str(QUEUE / 'tasks' / split / task):
                report['errors'].append(f'{split}: task input path mismatch {task}')
            agent = row.get('config', {}).get('agent', {})
            if agent.get('model_name') != 'openai/muse-spark-open-bf16':
                report['errors'].append(f'{split}: model configuration mismatch {task}')
            if not row.get('finished_at'):
                report['errors'].append(f'{split}: result file lacks native finish time {task}')
            reward = (row.get('verifier_result') or {}).get('rewards', {}).get('reward')
            records[task] = {
                'result': str(path.relative_to(QUEUE.parent.parent.parent.parent)),
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'native_graded': type(reward) in (int, float) and 0 <= reward <= 1,
                'exception_type': (row.get('exception_info') or {}).get('exception_type'),
            }
        report['splits'][split] = {
            'expected': len(expected),
            'native_terminal': len(records),
            'native_graded': sum(row['native_graded'] for row in records.values()),
            'records': records,
        }
    report['total_expected'] = sum(row['expected'] for row in report['splits'].values())
    report['total_native_terminal'] = sum(row['native_terminal'] for row in report['splits'].values())
    report['total_native_graded'] = sum(row['native_graded'] for row in report['splits'].values())
    EVIDENCE.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: (row['native_terminal'], row['expected'])
                      for name, row in report['splits'].items()}))
    if report['errors']:
        raise SystemExit(report['errors'])


if __name__ == '__main__':
    main()
