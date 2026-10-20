#!/usr/bin/env python3
"""Declare first actual draws for BF16 DeepSWE trials stopped before model access."""

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/muse_bf16_20261018'
WORK = ROOT / 'legacy_bench'
STATE = ROOT / 'recovery_20261020'
OLD_CLAIM = STATE / 'deep-r1-direct-2886-20261020-claim.json'
SOURCE = WORK / 'configs/deep-r1.json'
DIRECT = WORK / 'configs/deep-r1-direct-2886-20261020.json'
NAME = 'muse-bf16-deep-r1-pre-model-endpoint-recovery-20261020'
DEST = WORK / 'configs' / f'{NAME}.json'
CLAIM = STATE / f'{NAME}-claim.json'
OLD_ENDPOINT = 'http://10.1.77.106:31324/v1'
NEW_ENDPOINT = 'http://10.1.13.41:31324/v1'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if CLAIM.exists() or DEST.exists():
        assert CLAIM.exists() and DEST.exists()
        claim = read(CLAIM)
        assert claim['config_sha256'] == sha(DEST)
        assert claim['source_config_sha256'] == sha(SOURCE)
        print(json.dumps({'existing_verified_claim': str(CLAIM), 'declared': len(claim['tasks'])}))
        return
    old_claim = read(OLD_CLAIM)
    assert old_claim['source_config_sha256'] == sha(SOURCE)
    assert old_claim['config_sha256'] == sha(DIRECT)
    assert old_claim['old_endpoint'] == OLD_ENDPOINT
    assert old_claim['verified_direct_endpoint'] == NEW_ENDPOINT
    source = read(SOURCE)
    source_body = source.get('config', source)
    direct = read(DIRECT)
    direct_body = direct.get('config', direct)
    assert source_body['job_name'] == 'muse-bf16-deep-r1'
    assert len(source_body['tasks']) == 113
    assert direct_body['job_name'] == 'muse-bf16-deep-r1-direct-2886-20261020'
    assert OLD_ENDPOINT in json.dumps(source_body['agents'])
    assert NEW_ENDPOINT in json.dumps(direct_body['agents'])
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(NEW_ENDPOINT + '/models', timeout=10) as response:
        assert any(row['id'] == 'muse-spark-open-bf16' for row in json.load(response)['data'])

    eligible = {}
    for task, row in old_claim['terminal_original_trials'].items():
        path = Path(row['path'])
        assert sha(path) == row['sha256'], f'Original DeepSWE result changed: {task}'
        result = read(path)
        error = result.get('exception_info') or {}
        if error.get('exception_type') != 'AssertionError' or 'Model endpoint unavailable from sandbox' not in error.get('exception_message', ''):
            continue
        assert OLD_ENDPOINT + '/models' in error['exception_message']
        assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        assert not list((path.parent / 'agent/raw_responses').glob('*.json'))
        assert not (path.parent / 'agent/trajectory.json').exists()
        patches = list((path.parent / 'artifacts').glob('**/model.patch'))
        assert len(patches) == 1 and patches[0].stat().st_size == 0
        assert task not in old_claim['tasks'], f'Previously resumed task cannot be selected again: {task}'
        eligible[task] = {'result': str(path), 'result_sha256': sha(path),
                          'empty_patch': str(patches[0]), 'empty_patch_sha256': sha(patches[0]),
                          'raw_model_responses': 0, 'trajectory_present': False,
                          'exception_type': error['exception_type'],
                          'exception_message': error['exception_message']}
    assert len(eligible) == 17, f'Expected 17 pre-model endpoint failures, got {len(eligible)}'
    original_tasks = {Path(row['path']).name: row for row in source_body['tasks']}
    assert set(eligible) <= set(original_tasks)
    new_job = Path(direct_body['jobs_dir']) / NAME
    assert not new_job.exists(), 'Recovery job already exists without a frozen claim'
    new_config = json.loads(json.dumps(direct))
    body = new_config.get('config', new_config)
    body['job_name'] = NAME
    body['tasks'] = [row for row in source_body['tasks'] if Path(row['path']).name in eligible]
    assert len(body['tasks']) == 17
    DEST.write_text(json.dumps(new_config, indent=2) + '\n')
    claim = {'utc': datetime.now(timezone.utc).isoformat(), 'kind': 'deep', 'round': 1,
             'precision': 'BF16', 'model_allocation': 2886, 'cpu_allocation': 2922,
             'reason': 'Original native result stopped during sandbox endpoint healthcheck before any model response; first actual model draw on verified direct endpoint.',
             'source_config': str(SOURCE), 'source_config_sha256': sha(SOURCE),
             'direct_config': str(DIRECT), 'direct_config_sha256': sha(DIRECT),
             'config': str(DEST), 'config_sha256': sha(DEST), 'job_name': NAME,
             'old_endpoint': OLD_ENDPOINT, 'verified_direct_endpoint': NEW_ENDPOINT,
             'tasks': eligible,
             'policy': 'Only the 17 frozen pre-model endpoint failures may be replaced. Preserve old results and empty patches; count each task once only after native grading.'}
    CLAIM.write_text(json.dumps(claim, indent=2) + '\n')
    print(json.dumps({'claim': str(CLAIM), 'declared': len(eligible), 'job_name': NAME}))


if __name__ == '__main__':
    main()
