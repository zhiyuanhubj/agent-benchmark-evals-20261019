#!/usr/bin/env python3
"""Resume only Beam DeepSWE R2 trials stopped before their first model call."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import ProxyHandler, build_opener


BASE = Path('/fsx/home/zhiyuan')
REPO = BASE / 'agent-benchmark-evals-20261019'
BEAM = BASE / '.private/beam_20261018'
WORK = BEAM / 'legacy_bench_20261018/remaining_deep'
SOURCE = WORK / 'configs/deep-r2.json'
SOURCE_JOB = WORK / 'deep-results/beam-deep-r2-full113'
STATE = WORK / 'state/beam-deep-r2-client-recovery-20261021'
CLAIM = REPO / 'evidence/beam_deep_r2_client_recovery_claim.json'
OLD_CLIENT = WORK / 'client_dependency.py'
FIXED_CLIENT = REPO / 'protocol/beam_deep_r2_client_dependency_20261021.py'
ENDPOINT = 'http://10.1.95.27:31328/v1'
READY = BEAM / 'expanded_capacity_20261018/allocation-2901-rank-0/serving-conformance-ready.json'
ORIGINAL_READY = BEAM / 'serve-launch.json'
CPU_JOB = 2968
GPU_JOB = 2901
GPU_HOST = 'ip-10-1-95-27'
NAMES = {'pilot': 'beam-client-r2-pilot-20261021',
         'remaining': 'beam-client-r2-remaining-20261021'}
CONFIGS = {part: WORK / 'configs' / f'{name}.json' for part, name in NAMES.items()}
OLD_GUARD = "before.get('litellm') == '1.106.0'"
FIXED_GUARD = "before.get('litellm') in {'1.106.0', '1.106.1'}"


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write('\n')


def slurm_running(job, host=None):
    state = subprocess.check_output(
        ['squeue', '-h', '-j', str(job), '-o', '%T|%N'], text=True).strip()
    assert state == 'RUNNING|' + (host or 'ip-10-1-100-204'), (job, state)


def model_ready():
    replica = read(READY)
    original = read(ORIGINAL_READY)
    for field in ('model', 'revision', 'precision', 'image_digest'):
        assert replica[field] == original[field], field
    assert replica['api_base'] == ENDPOINT
    assert replica['precision'] == 'BF16'
    with build_opener(ProxyHandler({})).open(ENDPOINT + '/models', timeout=12) as response:
        assert any(row['id'] == 'Beam-1.0-501B-A23B'
                   for row in json.load(response)['data'])


def failed_before_model():
    source = read(SOURCE)
    body = source['config']
    assert body['job_name'] == 'beam-deep-r2-full113'
    assert body['n_attempts'] == 1 and body['n_concurrent_trials'] == 1
    assert body['agents'][0]['model_name'] == 'openai/Beam-1.0-501B-A23B'
    assert body['agents'][0]['kwargs']['config']['model']['model_kwargs']['api_base'] == 'http://10.1.25.253:31328/v1'
    inventory = {Path(row['path']).name: row for row in body['tasks']}
    assert len(inventory) == len(body['tasks']) == 113
    terminal = set()
    failures = {}
    for path in SOURCE_JOB.glob('*/result.json'):
        result = read(path)
        if not result.get('task_name') or not result.get('finished_at'):
            continue
        task = Path(result['config']['task']['path']).name
        assert task in inventory and task not in terminal
        terminal.add(task)
        exception = result.get('exception_info') or {}
        if exception.get('exception_type') != 'AssertionError':
            continue
        assert OLD_GUARD in exception.get('exception_traceback', '')
        assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        trial = path.parent
        assert not list((trial / 'agent/raw_responses').glob('*.json'))
        assert not (trial / 'agent/trajectory.json').exists()
        patches = list((trial / 'artifacts').glob('**/model.patch'))
        assert len(patches) == 1 and patches[0].stat().st_size == 0
        task_toml = Path(inventory[task]['path']) / 'task.toml'
        failures[task] = {
            'original_result': str(path), 'original_result_sha256': digest(path),
            'empty_patch': str(patches[0]), 'empty_patch_sha256': digest(patches[0]),
            'task_toml': str(task_toml), 'task_toml_sha256': digest(task_toml),
            'exception_type': 'AssertionError', 'raw_model_responses': 0,
            'trajectory_present': False,
        }
    assert terminal == set(inventory) and len(failures) == 35
    return source, inventory, failures


def prepare():
    assert not CLAIM.exists()
    assert not any(path.exists() for path in CONFIGS.values())
    assert not any((WORK / 'deep-results' / name).exists() for name in NAMES.values())
    slurm_running(CPU_JOB)
    slurm_running(GPU_JOB, GPU_HOST)
    model_ready()
    old = OLD_CLIENT.read_text()
    fixed = FIXED_CLIENT.read_text()
    assert old.count(OLD_GUARD) == fixed.count(FIXED_GUARD) == 1
    assert old.replace(OLD_GUARD, FIXED_GUARD) == fixed
    source, inventory, failures = failed_before_model()
    selected = sorted(failures)
    splits = {'pilot': selected[:1], 'remaining': selected[1:]}
    assert len(splits['pilot']) == 1 and len(splits['remaining']) == 34
    configs = {}
    for part, tasks in splits.items():
        spec = json.loads(json.dumps(source))
        body = spec['config']
        body['job_name'] = NAMES[part]
        body['tasks'] = [row for row in source['config']['tasks']
                         if Path(row['path']).name in tasks]
        body['n_concurrent_trials'] = 1 if part == 'pilot' else 2
        agent = body['agents'][0]
        agent['kwargs']['config']['model']['model_kwargs']['api_base'] = ENDPOINT
        for key in ('OPENAI_BASE_URL', 'OPENAI_API_BASE'):
            assert agent['env'][key] == 'http://10.1.25.253:31328/v1'
            agent['env'][key] = ENDPOINT
        spec['slurm_job'] = CPU_JOB
        assert len(body['tasks']) == len(tasks)
        configs[part] = spec
    for part, spec in configs.items():
        write_new(CONFIGS[part], spec)
    claim = {
        'utc': datetime.now(timezone.utc).isoformat(),
        'purpose': 'First real model draw for frozen Beam DeepSWE R2 pre-model client failures.',
        'source_config': str(SOURCE), 'source_config_sha256': digest(SOURCE),
        'source_job': str(SOURCE_JOB), 'expected_original_tasks': 113,
        'original_failed_before_model': failures,
        'declared_tasks': selected, 'pilot_task': splits['pilot'][0],
        'splits': {part: {'job_name': NAMES[part], 'tasks': tasks,
                          'config': str(CONFIGS[part]),
                          'config_sha256': digest(CONFIGS[part])}
                   for part, tasks in splits.items()},
        'original_client_sha256': digest(OLD_CLIENT),
        'fixed_client_source': str(FIXED_CLIENT),
        'fixed_client_sha256': digest(FIXED_CLIENT),
        'model': 'reflection/Beam-1.0-501B-A23B',
        'revision': read(READY)['revision'], 'precision': 'BF16',
        'model_image_digest': read(READY)['image_digest'],
        'model_ready_receipt': str(READY), 'model_ready_sha256': digest(READY),
        'model_allocation': GPU_JOB, 'cpu_allocation': CPU_JOB,
        'endpoint': ENDPOINT,
        'only_changes': ['frozen pre-model task subset', 'new run name',
                         'equivalent pinned BF16 endpoint',
                         'client guard accepts installed LiteLLM 1.106.0 or 1.106.1',
                         'remaining-task concurrency 1 to 2'],
        'scoring_policy': 'Keep original zero-response failures. Replace an original only after its first retry has a native binary reward; never choose by correctness.',
    }
    write_new(CLAIM, claim)
    print(json.dumps({'claim': str(CLAIM), 'tasks': len(selected),
                      'pilot': splits['pilot'][0], 'remaining': len(splits['remaining'])}))


def deploy():
    claim = read(CLAIM)
    backup = STATE / 'original_client_dependency.py'
    STATE.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        assert digest(OLD_CLIENT) == claim['original_client_sha256']
        shutil.copy2(OLD_CLIENT, backup)
    assert digest(backup) == claim['original_client_sha256']
    assert digest(FIXED_CLIENT) == claim['fixed_client_sha256']
    if digest(OLD_CLIENT) != claim['fixed_client_sha256']:
        assert digest(OLD_CLIENT) == claim['original_client_sha256']
        temp = OLD_CLIENT.with_suffix('.py.tmp')
        temp.write_bytes(FIXED_CLIENT.read_bytes())
        temp.replace(OLD_CLIENT)
    assert digest(OLD_CLIENT) == claim['fixed_client_sha256']
    print(json.dumps({'runtime': str(OLD_CLIENT), 'fixed_sha256': digest(OLD_CLIENT),
                      'original_backup': str(backup)}))


def run(part):
    claim = read(CLAIM)
    assert part in NAMES and digest(OLD_CLIENT) == claim['fixed_client_sha256']
    assert digest(SOURCE) == claim['source_config_sha256']
    assert digest(CONFIGS[part]) == claim['splits'][part]['config_sha256']
    assert not (STATE / f'exit_{part}.json').exists()
    assert not (WORK / 'deep-results' / NAMES[part]).exists()
    slurm_running(CPU_JOB)
    slurm_running(GPU_JOB, GPU_HOST)
    model_ready()
    available = subprocess.check_output([
        'srun', f'--jobid={CPU_JOB}', '--overlap', '--gres=none', '-N1', '-n1',
        '--immediate=10', 'python3', '-c',
        'import os; s=os.statvfs("/opt/sagemaker/tmp"); print(s.f_bavail*s.f_frsize)'],
        text=True).strip().splitlines()[-1]
    assert int(available) >= 60 * 1024**3, f'CPU Docker disk too full: {available}'
    temp_dir = f'/opt/sagemaker/tmp/zhiyuan-beam-deep-r2-client-{part}'
    subprocess.run(['srun', f'--jobid={CPU_JOB}', '--overlap', '--gres=none',
                    '-N1', '-n1', '--immediate=10', 'mkdir', '-p', temp_dir], check=True)
    env = os.environ.copy()
    env.update(MIX_SERVER_IP='10.1.95.27', OPENAI_API_KEY='EMPTY',
               HF_HOME=str(BASE / 'bench/hf_home'),
               UV_CACHE_DIR=str(BASE / 'bench/uv_cache'), TMPDIR=temp_dir)
    STATE.mkdir(parents=True, exist_ok=True)
    log = STATE / f'{part}.log'
    with log.open('a') as output:
        outcome = subprocess.run([
            'srun', f'--jobid={CPU_JOB}', '--overlap', '--gres=none', '-N1', '-n1',
            '-c16', '--immediate=10', str(BASE / 'AgentCompass/.venv/bin/python'),
            str(WORK / 'deep_entry.py'), str(CONFIGS[part])],
            cwd=BASE / 'AgentCompass', env=env, stdout=output,
            stderr=subprocess.STDOUT)
    write_new(STATE / f'exit_{part}.json', {
        'utc': datetime.now(timezone.utc).isoformat(), 'part': part,
        'returncode': outcome.returncode})
    raise SystemExit(outcome.returncode)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['deploy']:
        deploy()
    elif len(sys.argv) == 3 and sys.argv[1] == 'run' and sys.argv[2] in NAMES:
        run(sys.argv[2])
    else:
        raise SystemExit('usage: script.py prepare | deploy | run {pilot|remaining}')
