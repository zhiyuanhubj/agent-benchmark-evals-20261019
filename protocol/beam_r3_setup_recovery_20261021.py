#!/usr/bin/env python3
"""One declared draw for Beam TB2.1 round-three setup failures with no model reply.

Original ungraded results stay untouched. Each selected task gets exactly one
new native attempt under the same exact-image and generation protocol.
"""

import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'beam'
STATE = WORK / 'state'
RESULTS = ROOT / 'results/beam_bf16'
ORIGINAL = RESULTS / 'beam-tb-v1-exact-r3'
SOURCE = WORK / 'configs/r3-2901.json'
FROZEN = WORK / 'configs/r3.json'
JOB = 'beam-tb-v1-exact-r3-setup-replacement-20261021'
CONFIG = WORK / 'configs/r3-setup-replacement-20261021.json'
CLAIM = STATE / 'r3-setup-replacement-20261021-claim.json'
STARTED = STATE / 'r3-setup-replacement-20261021-started.json'
EXIT = STATE / 'r3-setup-replacement-20261021-exit.json'
LOG = STATE / 'r3-setup-replacement-20261021.log'
ENDPOINT = 'http://10.1.95.27:31328/v1'
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
SELECTED = {
    'qemu-alpine-ssh', 'polyglot-rust-c', 'pytorch-model-recovery',
    'pytorch-model-cli', 'portfolio-optimization', 'polyglot-c-py',
    'path-tracing-reverse', 'protein-assembly', 'openssl-selfsigned-cert',
    'pypi-server', 'prove-plus-comm',
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def running(job):
    return subprocess.check_output(['squeue', '-h', '-j', str(job), '-o', '%T'],
                                   text=True).strip() == 'RUNNING'


def original_proof():
    assert read(STATE / 'r3-exit.json')['returncode'] == 0
    done = read(STATE / 'beam-tb-v1-exact-r3-done.json')
    assert done['n_total_trials'] == done['stats']['n_completed_trials'] == 89
    source = read(SOURCE)
    frozen = read(FROZEN)
    assert source['job_name'] == frozen['job_name'] == 'beam-tb-v1-exact-r3'
    assert source['agents'][0]['kwargs']['api_base'] == ENDPOINT
    normalized = copy.deepcopy(source)
    normalized['agents'][0]['kwargs']['api_base'] = frozen['agents'][0]['kwargs']['api_base']
    assert normalized == frozen, 'Round-three effective config changed beyond equivalent endpoint'
    assert source['n_attempts'] == 1 and source['retry']['max_retries'] == 0
    image_plan = read(ROOT / 'allocation-2919/images-ready.json')
    assert image_plan['count'] == 89 and image_plan['all_archive_identities_verified']
    tasks = {Path(task['path']).name: task for task in source['tasks']}
    assert len(tasks) == 89 and SELECTED <= tasks.keys()
    results = {}
    for path in ORIGINAL.glob('*/result.json'):
        row = read(path)
        assert row.get('finished_at')
        name = Path(row['config']['task']['path']).name
        assert name in tasks and name not in results
        results[name] = path
    assert len(results) == 89
    originals = {}
    for name in sorted(SELECTED):
        path = results[name]
        row = read(path)
        assert row.get('verifier_result') is None, name
        exception = row.get('exception_info') or {}
        assert exception.get('exception_type') == 'RuntimeError', name
        message = exception.get('exception_message', '')
        assert (message.startswith('Failed to start tmux session.') or
                message.startswith('Docker compose command failed for environment ')), (name, message)
        raw = list((path.parent / 'agent/raw_responses').glob('*.json'))
        assert not raw, f'{name} has an original archived model response'
        trajectory = path.parent / 'agent/trajectory.json'
        originals[name] = {
            'result_path': str(path), 'result_sha256': sha(path),
            'original_raw_response_count': 0,
            'original_trajectory_sha256': sha(trajectory) if trajectory.exists() else None,
            'exception_type': exception['exception_type'],
            'exception_message': message,
            'task_toml_sha256': sha(Path(tasks[name]['path']) / 'task.toml'),
        }
    return source, originals


def prepare():
    assert not any(path.exists() for path in (CLAIM, CONFIG, STARTED, EXIT, RESULTS / JOB))
    source, originals = original_proof()
    replacement = copy.deepcopy(source)
    replacement['job_name'] = JOB
    replacement['tasks'] = [task for task in source['tasks']
                            if Path(task['path']).name in SELECTED]
    replacement['n_concurrent_trials'] = 1  # Keep the shared Docker disk below capacity.
    assert len(replacement['tasks']) == len(originals) == 11
    assert replacement['n_attempts'] == 1 and replacement['retry']['max_retries'] == 0
    write_new(CONFIG, replacement)
    write_new(CLAIM, {
        'prepared_utc': time.time(), 'round': 3, 'model': 'Beam-1.0-501B-A23B',
        'precision': 'BF16', 'profile': 'TB2.1 exact supplied images',
        'reason': 'Eleven original trials failed during tmux or Docker setup with no archived model response.',
        'original_job': ORIGINAL.name, 'originals': originals,
        'original_config': str(SOURCE), 'original_config_sha256': sha(SOURCE),
        'frozen_config_sha256': sha(FROZEN),
        'image_ready_sha256': sha(ROOT / 'allocation-2919/images-ready.json'),
        'replacement_job': JOB, 'replacement_config': str(CONFIG),
        'replacement_config_sha256': sha(CONFIG),
        'endpoint': ENDPOINT, 'model_allocation': 2901, 'cpu_allocation': 2919,
        'only_changes': ['declared subset of setup failures', 'unique job name',
                         'one concurrent sandbox to avoid shared Docker disk pressure'],
        'score_policy': 'Keep all original results ungraded. Report first replacement grades separately; never select best-of outcomes.',
        'maximum_replacements_per_task': 1,
        'runner_sha256': sha(Path(__file__)),
    })
    print(json.dumps({'claim': str(CLAIM), 'tasks': sorted(originals),
                      'replacement_config_sha256': sha(CONFIG)}), flush=True)


def run():
    assert CLAIM.exists() and CONFIG.exists() and not STARTED.exists()
    claim = read(CLAIM)
    assert claim['runner_sha256'] == sha(Path(__file__))
    assert claim['replacement_config_sha256'] == sha(CONFIG)
    assert claim['original_config_sha256'] == sha(SOURCE)
    assert claim['image_ready_sha256'] == sha(ROOT / 'allocation-2919/images-ready.json')
    _, originals = original_proof()
    assert claim['originals'] == originals, 'Original trial changed after the replacement claim'
    assert not (RESULTS / JOB).exists(), 'Replacement has already sampled'
    assert running(2919) and running(2901)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=10) as response:
        assert any(row['id'] == 'Beam-1.0-501B-A23B'
                   for row in json.load(response)['data'])
    env = dict(os.environ)
    env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.95.27',
               HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
               PYTHONPATH=str(BASE / 'bench/strict_four_models_20261008/sources/swe-pro/v2/tooling')
               + ':' + str(BASE / 'AgentCompass-official-baseline'))
    command = ['/usr/local/bin/srun', '--jobid=2919', '--overlap', '--gres=none',
               '-N1', '-n1', '-c8', '--immediate=10', PYTHON,
               str(WORK / 'harbor_entry.py'), str(CONFIG)]
    write_new(STARTED, {'started_utc': time.time(), 'claim_sha256': sha(CLAIM),
                        'replacement_config_sha256': sha(CONFIG), 'command': command})
    with LOG.open('x') as stream:
        result = subprocess.run(command, cwd=BASE / 'AgentCompass', env=env,
                                stdout=stream, stderr=subprocess.STDOUT)
    write_new(EXIT, {'finished_utc': time.time(), 'returncode': result.returncode,
                     'replacement_result_dir': str(RESULTS / JOB)})
    assert result.returncode == 0, 'Replacement stopped; preserve all native results'


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'run')
    (prepare if sys.argv[1] == 'prepare' else run)()
