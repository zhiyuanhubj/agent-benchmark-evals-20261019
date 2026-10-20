"""Continue Beam DeepSWE round 2 after its CPU allocation expired."""

import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


HERE = Path(__file__).resolve().parent
STATE = HERE / 'state'
CONFIG = HERE / 'configs/deep-r2.json'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
ENDPOINT = 'http://10.1.25.253:31328/v1'


with (STATE / 'r2-2922-resume.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert not (STATE / 'r2-2922-resume-claim.json').exists()
    assert json.loads((STATE / 'r2-exit.json').read_text())['returncode'] == 143
    source = json.loads(CONFIG.read_text())
    config = source['config']
    assert config['job_name'] == 'beam-deep-r2-full113'
    assert len(config['tasks']) == 113 and config['n_attempts'] == 1
    assert config['agents'][0]['kwargs']['config']['model']['model_kwargs']['api_base'] == ENDPOINT
    results = Path(config['jobs_dir']) / config['job_name']
    terminal = []
    partial = []
    for trial in results.iterdir():
        if not trial.is_dir():
            continue
        path = trial / 'result.json'
        if path.exists() and json.loads(path.read_text()).get('finished_at'):
            terminal.append(trial)
        else:
            partial.append(trial)
    assert len(terminal) == 25 and len(partial) == 1
    assert len({trial.name.split('__', 1)[0] for trial in terminal + partial}) == 26
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=20) as response:
        models = json.load(response)['data']
    assert any(model['id'] == 'Beam-1.0-501B-A23B' for model in models)
    backup = STATE / 'r2-2812-interrupted-original'
    assert not backup.exists()
    backup.mkdir()
    partial_original = partial[0]
    (backup / 'manifest.json').write_text(json.dumps({
        'utc': time.time(), 'reason': 'CPU allocation 2812 expired, controller exit 143',
        'original_trial': str(partial_original), 'terminal_trials_preserved': 25,
        'config_sha256': hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        'replacement_policy': 'Same job and exact config resume; existing 25 completed tasks reused, one interrupted partial preserved outside active results.',
    }, indent=2) + '\n')
    partial_original.rename(backup / partial_original.name)
    (STATE / 'r2-2922-resume-claim.json').write_text(json.dumps({
        'utc': time.time(), 'cpu_allocation': 2922, 'model_allocation': 2733,
        'model_endpoint': ENDPOINT, 'config': str(CONFIG),
        'config_sha256': hashlib.sha256(CONFIG.read_bytes()).hexdigest(),
        'original_terminal_count': 25, 'interrupted_trial_backup': str(backup / partial_original.name),
    }, indent=2) + '\n')
    env = os.environ.copy()
    env.update(MIX_SERVER_IP='10.1.25.253', OPENAI_API_KEY='EMPTY',
               HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
               UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
    command = ['/usr/local/bin/srun', '--jobid=2922', '--overlap', '--gres=none',
               '-N1', '-n1', '-c16', '--immediate=10', PYTHON,
               str(HERE / 'deep_entry.py'), str(CONFIG)]
    result = subprocess.run(command, cwd='/fsx/home/zhiyuan/AgentCompass', env=env)
    found = set()
    for path in results.glob('*/result.json'):
        value = json.loads(path.read_text())
        if value.get('finished_at'):
            name = Path(value['config']['task']['path']).name
            assert name not in found
            found.add(name)
    (STATE / 'r2-2922-resume-exit.json').write_text(json.dumps({
        'utc': time.time(), 'returncode': result.returncode,
        'terminal_tasks': len(found), 'expected_tasks': 113,
        'missing_tasks': sorted({Path(task['path']).name for task in config['tasks']} - found),
    }, indent=2) + '\n')
    assert result.returncode == 0 and len(found) == 113
