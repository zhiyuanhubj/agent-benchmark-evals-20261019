#!/usr/bin/env python3
"""Audit the predeclared Muse NVFP4 Pro Verified round-two shard."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / 'agent-benchmark-evals-20261019'
STATE = BASE / '.private/muse_spark_open_20261016/pro_round2_20261021/shard0-2900'
RUN = (STATE.parent / 'results/muse-pro-r2/'
       'muse-spark-open-nvfp4_swebench_pro_verified_mini_swe_agent/'
       'muse-nvfp4-pro-r2-shard0-2900')
EVIDENCE = ROOT / 'evidence/muse_nvfp4_pro_r2_shard0_progress.json'
CLAIM_COPY = ROOT / 'evidence/muse_nvfp4_pro_r2_shard0_claim.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


claim_path = STATE / 'claim.json'
claim = json.loads(claim_path.read_text())
command_path = Path(claim['command'])
assert claim['command_sha256'] == sha(command_path)
assert claim['endpoint_ready_sha256'] == sha(Path(claim['endpoint_ready']))
assert claim['precision'] == 'NVFP4' and claim['model_allocation'] == 2900
assert claim['endpoint'] == 'http://10.1.101.159:31321/v1'
assert len(claim['task_ids']) == len(set(claim['task_ids'])) == claim['expected_shard_tasks'] == 183
source = json.loads(Path(claim['source_shards'][0]['path']).read_text())
assert claim['source_shards'][0]['sha256'] == sha(Path(claim['source_shards'][0]['path']))
assert json.loads(source[source.index('--benchmark-params') + 1])['sample_ids'] == claim['task_ids']
command = json.loads(command_path.read_text())
assert command[command.index('--run-id') + 1] == claim['run_id']
assert command[command.index('--model-base-url') + 1] == claim['endpoint']
assert command[command.index('--task-concurrency') + 1] == '2'

records = {}
for path in sorted(RUN.glob('details/*/attempt-1/result.json')):
    task_path = path.parent.parent / 'task.json'
    task = json.loads(task_path.read_text())['task_id']
    assert task in claim['task_ids'] and task not in records
    result = json.loads(path.read_text())
    evaluation = (((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {})
    correct = (result.get('metrics') or {}).get('correct')
    graded = evaluation.get('completed') is True and isinstance(correct, bool)
    records[task] = {
        'task_json': str(task_path), 'task_sha256': sha(task_path),
        'result': str(path), 'result_sha256': sha(path),
        'native_graded': graded, 'success': bool(correct) if graded else None,
    }

graded = sum(row['native_graded'] for row in records.values())
success = sum(row['success'] is True for row in records.values())
evidence = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'model': 'Muse-Spark-Open-816B-A42B-NVFP4',
    'benchmark': 'SWE-bench Pro Verified', 'round': 2,
    'shard': 0, 'expected_round': claim['full_inventory_tasks'],
    'expected_shard': claim['expected_shard_tasks'],
    'terminal': len(records), 'graded': graded, 'success': success,
    'status': 'partial_no_full_score', 'accuracy': None,
    'claim': str(CLAIM_COPY.relative_to(ROOT)), 'claim_sha256': sha(claim_path),
    'run_id': claim['run_id'], 'records': records,
    'qualification': 'Only predeclared shard zero of the independent second 731-task draw. '
                     'No complete round accuracy or best-of merging with round one.',
}
EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
CLAIM_COPY.write_bytes(claim_path.read_bytes())
print(json.dumps({k: evidence[k] for k in ('expected_shard', 'terminal', 'graded', 'success')}))
