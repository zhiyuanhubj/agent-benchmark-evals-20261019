#!/usr/bin/env python3
"""Execute the predeclared single-task expiry correction once."""

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
CLAIM = STATE / 'r2-fasttext-expiry-2902-20261020-claim.json'
START = STATE / 'r2-fasttext-expiry-2902-20261020-start.json'
EXIT = STATE / 'r2-fasttext-expiry-2902-20261020-exit.json'
LOCK = STATE / 'r2-fasttext-expiry-2902-20261020.lock'
LOG = STATE / 'r2-fasttext-expiry-2902-20261020.log'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim = read(CLAIM)
        assert claim['old_allocation'] == 2867 and claim['new_allocation'] == 2902
        assert claim['task'] == 'train-fasttext' and claim['no_model_retry']
        assert claim['no_best_of_selection'] and claim['same_task_and_sampling_settings']
        assert not START.exists() and not EXIT.exists()
        job_dir = ROOT / 'results/muse_nvfp4' / claim['job_name']
        assert not job_dir.exists(), 'Existing draw requires audit before relaunch'
        assert subprocess.check_output(['squeue', '-h', '-j', '2902', '-o', '%T'],
                                       text=True).strip() == 'RUNNING'
        for key in ('config', 'source_config', 'route', 'source_result',
                    'new_endpoint_ready', 'new_reasoning_preflight', 'image_proof'):
            assert sha(Path(claim[key])) == claim[key + '_sha256']
        source = Path(claim['source_result'])
        assert sha(source.parent / 'agent/trajectory.json') == claim['source_trajectory_sha256']
        original = read(source)
        assert original['exception_info']['exception_type'] == 'ContextAccountingError'
        assert ((original.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
        raw = sorted((source.parent / 'agent/raw_responses').glob('*.json'))
        assert len(raw) == claim['source_raw_response_count']
        raw_hash = hashlib.sha256()
        for path in raw:
            raw_hash.update(path.name.encode() + b'\0' + sha(path).encode() + b'\n')
        assert raw_hash.hexdigest() == claim['source_raw_responses_manifest_sha256']
        task = Path(original['config']['task']['path'])
        assert sha(task / 'task.toml') == claim['task_toml_sha256']
        config = read(Path(claim['config']))
        assert config['job_name'] == claim['job_name']
        assert len(config['tasks']) == 1 and Path(config['tasks'][0]['path']) == task
        assert config['n_attempts'] == 1 and config['retry']['max_retries'] == 0
        ready, preflight = read(Path(claim['new_endpoint_ready'])), read(Path(claim['new_reasoning_preflight']))
        assert ready['allocation'] == preflight['allocation'] == 2902
        assert preflight['nonempty_reasoning_content']
        endpoint = ready['api_base']
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
        found = {}
        for path in job_dir.glob('*/result.json'):
            value = read(path)
            if value.get('finished_at'):
                name = Path(value['config']['task']['path']).name
                assert name not in found
                found[name] = str(path)
        with EXIT.open('x') as stream:
            json.dump({'utc': time.time(), 'returncode': result.returncode,
                       'terminal': len(found), 'expected': 1,
                       'missing': sorted({'train-fasttext'} - set(found)),
                       'results': found}, stream, indent=2)
            stream.write('\n')
        assert result.returncode == 0 and set(found) == {'train-fasttext'}


if __name__ == '__main__':
    main()
