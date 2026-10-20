#!/usr/bin/env python3
"""Declare disjoint BF16 native tasks after the 2869 endpoint bridge expired."""

import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/muse_bf16_20261018'
WORK = ROOT / 'legacy_bench'
STATE = ROOT / 'recovery_20261020'
REPO = BASE / 'agent-benchmark-evals-20261019'
OLD = 'http://10.1.77.106:31324/v1'
NEW = 'http://10.1.13.41:31324/v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(kind):
    name = f'muse-bf16-{kind}-r1-direct-2886-20261020'
    source = WORK / 'configs' / f'{kind}-r1.json'
    destination = WORK / 'configs' / f'{kind}-r1-direct-2886-20261020.json'
    claim_path = STATE / f'{kind}-r1-direct-2886-20261020-claim.json'
    if destination.exists() or claim_path.exists():
        assert destination.exists() and claim_path.exists()
        prior = json.loads(claim_path.read_text())
        assert prior['config_sha256'] == digest(destination)
        assert prior['source_config_sha256'] == digest(source)
        print(json.dumps({'kind': kind, 'existing_verified_claim': str(claim_path),
                          'missing': len(prior['tasks'])}))
        return
    original = json.loads(source.read_text())
    config = original.get('config', original)
    assert config['job_name'] == f'muse-bf16-{kind}-r1'
    tasks = {Path(item['path']).name: item for item in config['tasks']}
    expected = 89 if kind == 'tb' else 113
    assert len(tasks) == expected
    job = Path(config['jobs_dir']) / config['job_name']
    assert job.is_dir()
    terminal, pending = {}, {}
    for trial in job.iterdir():
        if not trial.is_dir() or '__' not in trial.name:
            continue
        provenance = trial / 'result.json'
        if not provenance.is_file():
            provenance = trial / 'config.json'
        value = json.loads(provenance.read_text())
        task = Path(value['config']['task']['path'] if 'config' in value else
                    value['task']['path']).name
        assert task in tasks and task not in terminal and task not in pending
        result = trial / 'result.json'
        if result.is_file():
            assert Path(value['config']['task']['path']).name == task
            terminal[task] = {'path': str(result), 'sha256': digest(result),
                              'reward': ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward'),
                              'exception': (value.get('exception_info') or {}).get('exception_type')}
        else:
            raws = list((trial / 'agent/raw_responses').glob('*.json'))
            assert not raws, f'Preserve model-sampled interrupted trial for audit: {trial}'
            pending[task] = {'path': str(trial), 'raw_responses': 0}
    missing = sorted(set(tasks) - set(terminal))
    assert set(pending) <= set(missing)
    assert len(missing) >= 1
    assert all(OLD in json.dumps(item) for item in config['agents'])
    assert NEW not in json.dumps(original)
    new_config = json.loads(json.dumps(original).replace(OLD, NEW))
    body = new_config.get('config', new_config)
    body['job_name'] = name
    body['tasks'] = [item for item in config['tasks'] if Path(item['path']).name in missing]
    assert len(body['tasks']) == len(missing)
    assert not (Path(config['jobs_dir']) / name).exists()
    destination.write_text(json.dumps(new_config, indent=2) + '\n')
    claim = {
        'utc': datetime.now(timezone.utc).isoformat(),
        'reason': '2869 bridge expired while original one-draw first-round trials ran; resume only tasks without a native result',
        'kind': kind, 'round': 1, 'precision': 'BF16', 'model_allocation': 2886,
        'old_endpoint': OLD, 'verified_direct_endpoint': NEW,
        'job_name': name, 'source_job_name': config['job_name'],
        'source_config': str(source), 'source_config_sha256': digest(source),
        'config': str(destination), 'config_sha256': digest(destination),
        'tasks': missing, 'pending_original_trials_without_model_response': pending,
        'terminal_original_trials': terminal,
        'policy': 'Do not duplicate or replace an existing native result. Keep prior failed and partial artifacts separately; score each task at most once after task-level audit.',
    }
    claim_path.write_text(json.dumps(claim, indent=2) + '\n')
    print(json.dumps({'kind': kind, 'new_job': name, 'missing': len(missing),
                      'original_terminal': len(terminal), 'original_pending_no_model': len(pending),
                      'claim': str(claim_path)}))


def main():
    stop = json.loads((STATE / 'bridge-2869-expiry-stop-plan.json').read_text())
    assert stop['old_endpoint'] == OLD and stop['verified_live_model_endpoint'] == NEW
    assert '2869|TIMEOUT|' in subprocess.run(
        ['sacct', '-n', '-P', '-j', '2869', '--format=JobIDRaw,State,End'],
        check=True, capture_output=True, text=True).stdout
    assert '2886' in subprocess.run(['squeue', '-h', '-j', '2886', '-o', '%i'],
                                    check=True, capture_output=True, text=True).stdout.split()
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(NEW + '/models', timeout=10) as response:
        assert any(model['id'] == 'muse-spark-open-bf16' for model in json.load(response)['data'])
    for kind in ('tb', 'deep'):
        prepare(kind)


if __name__ == '__main__':
    main()
