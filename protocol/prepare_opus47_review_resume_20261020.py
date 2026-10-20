#!/usr/bin/env python3
"""Freeze and preserve Opus 4.7 SWE-Review state before native Harbor resume."""

import hashlib
import json
import subprocess
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from harbor.models.job.config import JobConfig


BASE = Path('/fsx/home/zhiyuan/.private/opus47_review_20261020')
STATE = BASE / 'resume_20261020'
SPLITS = {
    'glm5_500': ('opus47-swe-review-glm-r1-2900-20261020.service', 500),
    'qwen3_coder_30b_500': ('opus47-swe-review-coder-r1-2900-20261020.service', 462),
    'qwen3_30b_instruct2507_500': ('opus47-swe-review-instruct-r1-2900-20261020.service', 422),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    with path.open('x') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write('\n')


def main():
    assert not (STATE / 'claim.json').exists(), 'Continuation already frozen'
    STATE.mkdir(parents=True, exist_ok=True)
    for url in ('http://10.1.69.108:31352/health',
                'http://10.1.115.182:31352/health'):
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=5) as response:
            assert json.load(response)['ready'] is True
    assert subprocess.check_output(['squeue', '-h', '-j', '2887', '-o', '%T|%N'], text=True).strip() == 'RUNNING|ip-10-1-69-108'

    claim = {
        'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Opus 4.7 SWE-Review first attempts; resume only missing native results after GPU-node Docker disk exhaustion.',
        'gateway': 'http://10.1.69.108:31352/v1',
        'original_endpoint_forwarded': 'http://10.1.115.182:31352/v1',
        'client_allocation': 2887,
        'preserve_existing_native_results': True,
        'no_correctness_based_selection': True,
        'splits': {},
    }
    for split, (unit, expected_count) in SPLITS.items():
        assert subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit]).returncode != 0, unit
        source = BASE / 'configs' / f'{split}.json'
        spec = json.loads(source.read_text())
        config = JobConfig.model_validate(spec['config'])
        assert config.n_attempts == 1 and config.n_concurrent_trials == 2
        assert config.agents[0].model_name == 'openai/claude-opus-4-7'
        assert config.agents[0].env['LLM_BASE_URL'] == 'http://10.1.115.182:31352/v1'
        assert config.agents[0].env['LLM_API_KEY'] == 'EMPTY'
        task_root = Path(config.datasets[0].path)
        tasks = {path.name for path in task_root.iterdir() if path.is_dir()}
        assert len(tasks) == expected_count
        job = Path(config.jobs_dir) / config.job_name
        existing_config_path = job / 'config.json'
        assert existing_config_path.exists()

        # Harbor masks this environment value in its persisted job config.
        # Match that value while LLM_API_KEY=EMPTY supplies the same runtime key.
        spec['config']['agents'][0]['env']['LLM_API_KEY'] = '${LLM_API_KEY}'
        assert JobConfig.model_validate(spec['config']) == JobConfig.model_validate_json(existing_config_path.read_text())
        continuation = STATE / f'{split}-config.json'
        save_new(continuation, spec)

        terminals = {}
        interrupted = {}
        for trial in job.iterdir():
            if not trial.is_dir():
                continue
            native = trial / 'result.json'
            if native.exists():
                row = json.loads(native.read_text())
                task = Path(row['task_id']['path']).name
                assert row['config']['agent']['model_name'] == 'openai/claude-opus-4-7'
                assert task in tasks and task not in terminals and task not in interrupted
                terminals[task] = {'result': str(native), 'sha256': digest(native)}
            else:
                task = trial.name.rsplit('__', 1)[0]
                assert task in tasks and task not in terminals and task not in interrupted
                assert not list((trial / 'agent/raw_responses').glob('*.json'))
                archive = STATE / f'{split}-{trial.name}-interrupted.tar'
                with tarfile.open(archive, 'x') as tar:
                    tar.add(trial, arcname=trial.name)
                interrupted[task] = {'directory': str(trial), 'archive': str(archive),
                                     'archive_sha256': digest(archive)}
        assert len(terminals) + len(interrupted) <= len(tasks)
        claim['splits'][split] = {
            'source_config': str(source), 'source_config_sha256': digest(source),
            'existing_job_config_sha256': digest(existing_config_path),
            'resume_config': str(continuation), 'resume_config_sha256': digest(continuation),
            'task_count': len(tasks), 'terminal_count': len(terminals),
            'never_started_count': len(tasks - set(terminals) - set(interrupted)),
            'interrupted_unresulted_count': len(interrupted),
            'terminal_results': terminals, 'interrupted_trials': interrupted,
            'policy': 'Harbor resumes the same one-attempt job. Every existing native result remains fixed; zero-result trial directories are archived before Harbor replaces them.',
        }
    save_new(STATE / 'claim.json', claim)
    print(json.dumps({key: {name: row[name] for name in
                            ('task_count', 'terminal_count', 'never_started_count', 'interrupted_unresulted_count')}
                      for key, row in claim['splits'].items()}))


if __name__ == '__main__':
    main()
