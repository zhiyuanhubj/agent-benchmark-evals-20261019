#!/usr/bin/env python3
"""Run the declared train-fasttext correction with the pinned image and tmux mounts."""

import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
CLAIM = STATE / 'r2-fasttext-tmux-2902-20261020-claim.json'
START = STATE / 'r2-fasttext-tmux-2902-20261020-start.json'
EXIT = STATE / 'r2-fasttext-tmux-2902-20261020-exit.json'
LOCK = STATE / 'r2-fasttext-tmux-2902-20261020.lock'
LOG = STATE / 'r2-fasttext-tmux-2902-20261020.log'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim = read(CLAIM)
        assert claim['new_allocation'] == 2902 and claim['task'] == 'train-fasttext'
        assert claim['same_task_model_sampling_and_verifier']
        assert claim['no_model_retry'] and claim['no_best_of_selection']
        assert claim['pre_model_failure_preserved']
        assert not START.exists() and not EXIT.exists()
        job_dir = ROOT / 'results/muse_nvfp4' / claim['job_name']
        assert not job_dir.exists()
        assert subprocess.check_output(['squeue', '-h', '-j', '2902', '-o', '%T'],
                                       text=True).strip() == 'RUNNING'
        for key in ('config', 'source_claim', 'source_config', 'source_result',
                    'preflight', 'harness_tool_class'):
            assert sha(Path(claim[key])) == claim[key + '_sha256']
        source_claim = read(Path(claim['source_claim']))
        for key in ('source_result', 'new_endpoint_ready', 'new_reasoning_preflight',
                    'image_proof'):
            assert sha(Path(source_claim[key])) == source_claim[key + '_sha256']
        source_result = read(Path(claim['source_result']))
        assert source_result['exception_info']['exception_type'] == 'RuntimeError'
        assert ((source_result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        assert not list((Path(claim['source_result']).parent / 'agent/raw_responses').glob('*.json'))
        preflight = read(Path(claim['preflight']))
        assert preflight['task_image_id'] == claim['task_image_id']
        assert preflight['returncode'] == 0 and preflight['model_requests'] == 0
        config = read(Path(claim['config']))
        source = read(Path(claim['source_config']))
        assert config['job_name'] == claim['job_name']
        assert config['environment']['import_path'] == 'preinstalled_tmux_isolated_docker:PreinstalledTmuxIsolatedDocker'
        config_copy = json.loads(json.dumps(config))
        config_copy['job_name'] = source['job_name']
        config_copy['environment']['import_path'] = source['environment']['import_path']
        assert config_copy == source, 'Model, task, sampling, or verifier settings changed'
        assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
        task = Path(config['tasks'][0]['path'])
        assert sha(task / 'task.toml') == claim['task_toml_sha256']
        ready = read(Path(source_claim['new_endpoint_ready']))
        endpoint = ready['api_base']
        assert ready['allocation'] == 2902
        assert config['agents'][0]['kwargs']['api_base'] == endpoint
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(endpoint + '/models', timeout=20) as response:
            assert any(row['id'] == 'muse-spark-open-nvfp4'
                       for row in json.load(response)['data'])
        with START.open('x') as stream:
            json.dump({'utc': time.time(), 'job_name': claim['job_name'],
                       'model_allocation': 2902, 'cpu_allocation': 2919,
                       'claim_sha256': sha(CLAIM), 'config_sha256': sha(Path(claim['config'])),
                       'endpoint': endpoint}, stream, indent=2)
            stream.write('\n')
        env = dict(os.environ)
        env.update(OPENAI_API_KEY='EMPTY', HF_HOME=str(BASE / 'bench/hf_home'),
                   UV_CACHE_DIR=str(BASE / 'bench/uv_cache'), MIX_SERVER_IP='10.1.105.182')
        with LOG.open('a') as stream:
            result = subprocess.run([str(BASE / 'AgentCompass/.venv/bin/python'),
                                     str(WORK / 'harbor_entry.py'), str(claim['config'])],
                                    cwd=str(BASE / 'AgentCompass'), env=env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        found = list(job_dir.glob('train-fasttext__*/result.json'))
        assert len(found) <= 1
        value = read(found[0]) if found else None
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward') if value else None
        with EXIT.open('x') as stream:
            json.dump({'utc': time.time(), 'returncode': result.returncode,
                       'terminal': bool(value and value.get('finished_at')),
                       'reward': reward, 'result': str(found[0]) if found else None,
                       'result_sha256': sha(found[0]) if found else None}, stream, indent=2)
            stream.write('\n')
        assert result.returncode == 0 and value and value.get('finished_at')
        assert reward in (0, 1), 'Native grade missing; audit before further action'


if __name__ == '__main__':
    main()
