"""Run the untouched third Beam DeepSWE round on the verified 2888 replica."""

import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
BEAM = HERE.parents[1]
READY = BEAM / 'expanded_capacity_20261018/allocation-2888-rank-0/serving-conformance-ready.json'
TEMPLATE = HERE / 'configs/deep-r3.template.json'
CONFIG = HERE / 'configs/deep-r3.json'
STATE = HERE / 'state'
ENDPOINT = 'http://10.1.108.251:31328/v1'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


with (STATE / 'r3-2888-controller.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not (STATE / 'r3-launch.json').exists()
    assert not CONFIG.exists()
    assert not (STATE / 'r3-2888-launch.json').exists()
    source = json.loads(TEMPLATE.read_text())
    assert source['config']['job_name'] == 'beam-deep-r3-full113'
    assert len(source['config']['tasks']) == 113
    assert len({Path(task['path']).name for task in source['config']['tasks']}) == 113
    assert source['config']['n_attempts'] == 1
    assert not (Path(source['config']['jobs_dir']) / source['config']['job_name']).exists()
    assert json.loads((STATE / 'r2-exit.json').read_text())['returncode'] == 143
    assert not (STATE / 'complete.json').exists()
    while not READY.exists():
        (STATE / 'r3-2888-waiting.json').write_text(json.dumps({
            'utc': time.time(), 'phase': 'waiting_for_pinned_beam_endpoint',
            'allocation': 2888, 'cpu_allocation': 2922,
        }, indent=2) + '\n')
        time.sleep(15)
    ready = json.loads(READY.read_text())
    assert ready['api_base'] == ENDPOINT
    assert ready['model'] == 'reflection/Beam-1.0-501B-A23B'
    assert ready['revision'] == '78f8f654d40a40919b8e9954b40dd879ecb9a692'
    assert ready['precision'] == 'BF16'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=20) as response:
        models = json.load(response)['data']
    assert any(model['id'] == 'Beam-1.0-501B-A23B' for model in models)
    source_text = TEMPLATE.read_text()
    assert source_text.count('http://10.1.25.253:31328/v1') >= 1
    effective = json.loads(source_text.replace('http://10.1.25.253:31328/v1', ENDPOINT))
    effective['slurm_job'] = 2922
    effective['config']['n_concurrent_trials'] = 4
    changed_back = json.loads(json.dumps(effective))
    changed_back['slurm_job'] = source['slurm_job']
    changed_back['config']['n_concurrent_trials'] = source['config']['n_concurrent_trials']
    changed_back_text = json.dumps(changed_back).replace(ENDPOINT, 'http://10.1.25.253:31328/v1')
    assert json.loads(changed_back_text) == source, 'Task or sampling settings changed'
    CONFIG.write_text(json.dumps(effective, indent=2) + '\n')
    claim = STATE / 'r3-2888-launch.json'
    claim.write_text(json.dumps({
        'utc': time.time(), 'round': 3, 'expected_tasks': 113,
        'original_template': str(TEMPLATE), 'original_template_sha256': sha(TEMPLATE),
        'effective_config': str(CONFIG), 'effective_config_sha256': sha(CONFIG),
        'model_allocation': 2888, 'cpu_allocation': 2922, 'endpoint': ENDPOINT,
        'orchestration_change': 'n_concurrent_trials 1 -> 4; task/image/generation settings unchanged',
        'purpose': 'Original controller stopped after CPU allocation 2812 expired during round 2. Round 3 was never launched.',
    }, indent=2) + '\n')
    env = os.environ.copy()
    env.update(MIX_SERVER_IP='10.1.108.251', OPENAI_API_KEY='EMPTY',
               HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
               UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
    command = ['/usr/local/bin/srun', '--jobid=2922', '--overlap', '--gres=none',
               '-N1', '-n1', '-c32', '--immediate=10', PYTHON,
               str(HERE / 'deep_entry.py'), str(CONFIG)]
    result = subprocess.run(command, cwd='/fsx/home/zhiyuan/AgentCompass', env=env)
    completed = set()
    for path in (Path(effective['config']['jobs_dir']) / effective['config']['job_name']).glob('*/result.json'):
        value = json.loads(path.read_text())
        if value.get('finished_at'):
            name = Path(value['config']['task']['path']).name
            assert name not in completed
            completed.add(name)
    (STATE / 'r3-2888-exit.json').write_text(json.dumps({
        'utc': time.time(), 'returncode': result.returncode,
        'terminal_tasks': len(completed), 'expected_tasks': 113,
        'missing_tasks': sorted({Path(task['path']).name for task in effective['config']['tasks']} - completed),
    }, indent=2) + '\n')
    assert result.returncode == 0 and len(completed) == 113
