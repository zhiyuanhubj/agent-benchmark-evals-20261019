#!/usr/bin/env python3
"""Declare first model draws for BF16 TB2.1 pre-model infrastructure failures."""

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/muse_bf16_20261018'
WORK = ROOT / 'legacy_bench'
REPO = BASE / 'agent-benchmark-evals-20261019'
STATE = ROOT / 'recovery_20261020'
SOURCE = WORK / 'configs/tb-r1.json'
DIRECT = WORK / 'configs/tb-r1-direct-2886-20261020.json'
AUDIT = REPO / 'evidence/muse_bf16_tb_ungraded_audit.json'
NAME = 'muse-bf16-tb-r1-pre-model-recovery-20261020'
DEST = WORK / 'configs' / (NAME + '.json')
CLAIM = STATE / (NAME + '-claim.json')
OLD_ENDPOINT = 'http://10.1.77.106:31324/v1'
ENDPOINT = 'http://10.1.13.41:31324/v1'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if CLAIM.exists() or DEST.exists():
        assert CLAIM.exists() and DEST.exists()
        claim = read(CLAIM)
        assert claim['config_sha256'] == sha(DEST)
        assert claim['audit_sha256'] == sha(AUDIT)
        assert claim['source_config_sha256'] == sha(SOURCE)
        assert claim['direct_config_sha256'] == sha(DIRECT)
        print(json.dumps({'existing_verified_claim': str(CLAIM), 'declared_tasks': len(claim['tasks'])}))
        return
    source = read(SOURCE)
    source_body = source.get('config', source)
    direct = read(DIRECT)
    direct_body = direct.get('config', direct)
    audit = read(AUDIT)
    assert source_body['job_name'] == 'muse-bf16-tb-r1'
    assert direct_body['job_name'] == 'muse-bf16-tb-r1-direct-2886-20261020'
    assert len(source_body['tasks']) == 89 and len(direct_body['tasks']) == 16
    assert source_body['n_attempts'] == direct_body['n_attempts'] == 1
    assert source_body['n_concurrent_trials'] == direct_body['n_concurrent_trials'] == 2
    assert source_body['agents'][0]['kwargs']['api_base'] == OLD_ENDPOINT
    assert direct_body['agents'][0]['kwargs']['api_base'] == ENDPOINT
    assert audit['source_ungraded'] == 32 and audit['pre_model_infrastructure_failures'] == 30
    assert audit['interrupted_after_model_output'] == 2
    direct_tasks = {Path(row['path']).name for row in direct_body['tasks']}
    originals = {}
    for task, row in audit['ungraded_tasks'].items():
        if row['classification'] != 'pre_model_infrastructure_failure':
            continue
        path = Path(row['source_result'])
        assert sha(path) == row['source_result_sha256']
        result = read(path)
        assert result.get('finished_at') and Path(result['config']['task']['path']).name == task
        assert result['config']['agent']['kwargs']['api_base'] == OLD_ENDPOINT
        assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        assert (result.get('exception_info') or {}).get('exception_type') == row['exception_type']
        assert row['raw_response_count'] == 0 and not list((path.parent / 'agent/raw_responses').glob('*.json'))
        trajectory = path.parent / 'agent/trajectory.json'
        if row['trajectory_sha256']:
            assert sha(trajectory) == row['trajectory_sha256']
            assert not any(step.get('source') == 'agent' for step in read(trajectory).get('steps', []))
        else:
            assert not trajectory.exists()
        assert row['agent_trajectory_steps'] == 0
        assert not any(p.stat().st_size for p in path.parent.rglob('model.patch'))
        assert task not in direct_tasks
        originals[task] = row
    assert len(originals) == 30
    source_tasks = {Path(row['path']).name: row for row in source_body['tasks']}
    assert set(originals) <= set(source_tasks)
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(ENDPOINT + '/models', timeout=10) as response:
        assert any(row['id'] == 'muse-spark-open-bf16' for row in json.load(response)['data'])
    assert not (Path(direct_body['jobs_dir']) / NAME).exists()
    config = json.loads(json.dumps(direct))
    body = config.get('config', config)
    body['job_name'] = NAME
    body['tasks'] = [row for row in source_body['tasks'] if Path(row['path']).name in originals]
    assert len(body['tasks']) == 30
    DEST.write_text(json.dumps(config, indent=2) + '\n')
    claim = {
        'utc': datetime.now(timezone.utc).isoformat(),
        'reason': 'First model draws for frozen original TB2.1 trials that failed before any model response.',
        'precision': 'BF16', 'kind': 'tb', 'round': 1,
        'model_allocation': 2886, 'cpu_allocation': 2968,
        'old_endpoint': OLD_ENDPOINT, 'verified_direct_endpoint': ENDPOINT,
        'source_config': str(SOURCE), 'source_config_sha256': sha(SOURCE),
        'direct_config': str(DIRECT), 'direct_config_sha256': sha(DIRECT),
        'audit': str(AUDIT), 'audit_sha256': sha(AUDIT),
        'job_name': NAME, 'config': str(DEST), 'config_sha256': sha(DEST),
        'tasks': originals,
        'excluded_partial_model_output_tasks': sorted(set(audit['ungraded_tasks']) - set(originals)),
        'policy': 'All 30 zero-response tasks are predeclared. Preserve originals and exclude them from scoring only when the matching new native terminal result exists. The two tasks with actual model output are excluded from this recovery. No correctness-based selection.',
    }
    CLAIM.write_text(json.dumps(claim, indent=2) + '\n')
    print(json.dumps({'claim': str(CLAIM), 'declared_tasks': len(originals), 'job_name': NAME}))


if __name__ == '__main__':
    main()
