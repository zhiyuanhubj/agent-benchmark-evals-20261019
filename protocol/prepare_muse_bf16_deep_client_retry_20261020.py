#!/usr/bin/env python3
"""Retry BF16 DeepSWE pre-model client setup failures without a second model draw."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
REPO = BASE / 'agent-benchmark-evals-20261019'
WORK = BASE / '.private/muse_bf16_20261018/legacy_bench'
STATE = BASE / '.private/muse_bf16_20261018/recovery_20261020'
FIRST_NAME = 'muse-bf16-deep-r1-pre-model-endpoint-recovery-20261020'
FIRST_CLAIM = STATE / f'{FIRST_NAME}-claim.json'
FIRST_CONFIG = WORK / 'configs' / f'{FIRST_NAME}.json'
NAME = 'muse-bf16-deep-r1-pre-model-client-recovery-20261020'
CONFIG = WORK / 'configs' / f'{NAME}.json'
CLAIM = STATE / f'{NAME}-claim.json'
CLIENT_SOURCE = REPO / 'protocol/muse_bf16_client_dependency.py'
CLIENT_RUNTIME = WORK / 'client_dependency.py'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if CLAIM.exists() or CONFIG.exists():
        assert CLAIM.exists() and CONFIG.exists()
        claim = read(CLAIM)
        assert claim['config_sha256'] == sha(CONFIG)
        assert claim['client_dependency_sha256'] == sha(CLIENT_RUNTIME) == sha(CLIENT_SOURCE)
        print(json.dumps({'existing_verified_claim': str(CLAIM), 'declared': len(claim['tasks'])}))
        return
    initial = read(FIRST_CLAIM)
    assert initial['config_sha256'] == sha(FIRST_CONFIG)
    assert len(initial['tasks']) == 17
    assert sha(CLIENT_SOURCE) == sha(CLIENT_RUNTIME)
    assert "{'1.106.0', '1.106.1'}" in CLIENT_RUNTIME.read_text()
    first_job = WORK / 'deep-results' / FIRST_NAME
    assert first_job.is_dir()
    failed, interrupted = {}, {}
    for trial in first_job.iterdir():
        if not trial.is_dir() or '__' not in trial.name:
            continue
        config = read(trial / 'config.json')
        task = Path(config['task']['path']).name
        assert task in initial['tasks'] and task not in failed and task not in interrupted
        raw = list((trial / 'agent/raw_responses').glob('*.json'))
        assert not raw, f'Prior client retry reached the model: {task}'
        result_path = trial / 'result.json'
        if not result_path.exists():
            interrupted[task] = {'trial_dir': str(trial), 'raw_model_responses': 0}
            continue
        result = read(result_path)
        error = result.get('exception_info') or {}
        assert error.get('exception_type') == 'AssertionError'
        assert "before.get('litellm') == '1.106.0'" in error.get('exception_traceback', '')
        assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        assert not (trial / 'agent/trajectory.json').exists()
        patches = list((trial / 'artifacts').glob('**/model.patch'))
        assert len(patches) == 1 and patches[0].stat().st_size == 0
        failed[task] = {'result': str(result_path), 'result_sha256': sha(result_path),
                        'empty_patch': str(patches[0]), 'empty_patch_sha256': sha(patches[0]),
                        'raw_model_responses': 0, 'trajectory_present': False,
                        'exception_type': error['exception_type']}
    assert len(failed) == 2 and len(interrupted) <= 2
    old = read(FIRST_CONFIG)
    body = old.get('config', old)
    assert body['job_name'] == FIRST_NAME and len(body['tasks']) == 17
    assert not (WORK / 'deep-results' / NAME).exists()
    new = json.loads(json.dumps(old))
    new_body = new.get('config', new)
    new_body['job_name'] = NAME
    assert {Path(row['path']).name for row in new_body['tasks']} == set(initial['tasks'])
    CONFIG.write_text(json.dumps(new, indent=2) + '\n')
    claim = dict(initial)
    claim.update({'utc': datetime.now(timezone.utc).isoformat(),
                  'reason': 'The first endpoint-correction job stopped before model access because the client version guard accepted LiteLLM 1.106.0 but the pinned task image has 1.106.1. Runtime guard now accepts either version and preserves whichever is present.',
                  'job_name': NAME, 'config': str(CONFIG), 'config_sha256': sha(CONFIG),
                  'initial_claim': str(FIRST_CLAIM), 'initial_claim_sha256': sha(FIRST_CLAIM),
                  'first_job_name': FIRST_NAME, 'first_pre_model_results': failed,
                  'first_interrupted_without_model_response': interrupted,
                  'client_dependency_source': str(CLIENT_SOURCE),
                  'client_dependency_runtime': str(CLIENT_RUNTIME),
                  'client_dependency_sha256': sha(CLIENT_RUNTIME),
                  'policy': 'The first correction had no model responses. Count only the first native result from this new job for each frozen task; preserve all prior records.'})
    CLAIM.write_text(json.dumps(claim, indent=2) + '\n')
    print(json.dumps({'claim': str(CLAIM), 'declared': len(claim['tasks']),
                      'prior_failed_before_model': len(failed), 'prior_interrupted_before_model': len(interrupted)}))


if __name__ == '__main__':
    main()
