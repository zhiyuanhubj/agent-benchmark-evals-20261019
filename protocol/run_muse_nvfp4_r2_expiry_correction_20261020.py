#!/usr/bin/env python3
"""Run the declared allocation-expiry correction once on the prepared CPU node."""

import fcntl
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
WORK = SOURCE / 'muse_nvfp4'
CLAIM_PATH = WORK / 'state/r2-expiry-correction-2902-20261020-claim.json'
START = CLAIM_PATH.with_name('r2-expiry-correction-2902-20261020-start.json')
EXIT = CLAIM_PATH.with_name('r2-expiry-correction-2902-20261020-exit.json')
LOCK = CLAIM_PATH.with_name('r2-expiry-correction-2902-20261020.lock')
LOG = CLAIM_PATH.with_name('r2-expiry-correction-2902-20261020.log')


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert os.environ.get('SLURM_JOB_ID') == '2919'
with LOCK.open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    claim = read(CLAIM_PATH)
    config_path = Path(claim['config'])
    assert claim['config_sha256'] == digest(config_path)
    assert claim['new_allocation'] == 2902 and claim['old_allocation'] == 2867
    assert claim['no_model_retry'] and claim['no_best_of_selection']
    assert not START.exists() and not EXIT.exists(), 'A prior launch requires audit'
    assert not (SOURCE / 'results/muse_nvfp4' / claim['job_name']).exists()
    assert subprocess.check_output(['squeue', '-h', '-j', '2902', '-o', '%T'], text=True).strip() == 'RUNNING'
    for key in ('source_config', 'source_claim', 'new_endpoint_ready',
                'new_reasoning_preflight', 'image_proof'):
        assert digest(Path(claim[key])) == claim[key + '_sha256']
    ready = read(Path(claim['new_endpoint_ready']))
    preflight = read(Path(claim['new_reasoning_preflight']))
    assert ready['allocation'] == preflight['allocation'] == 2902
    assert preflight['nonempty_reasoning_content']
    endpoint = ready['api_base']
    assert read(config_path)['agents'][0]['kwargs']['api_base'] == endpoint
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=20) as response:
        models = json.load(response)['data']
    assert any(row['id'] == 'muse-spark-open-nvfp4' for row in models)
    for row in claim['tasks']:
        assert digest(Path(row['source_original_result'])) == row['source_original_result_sha256']
        if row.get('previous_recovery_result'):
            assert digest(Path(row['previous_recovery_result'])) == row['previous_recovery_result_sha256']
    with START.open('x') as stream:
        json.dump({'utc': time.time(), 'job_name': claim['job_name'], 'model_allocation': 2902,
                   'cpu_allocation': 2919, 'claim_sha256': digest(CLAIM_PATH),
                   'config_sha256': digest(config_path), 'endpoint': endpoint}, stream, indent=2)
        stream.write('\n')
    env = dict(os.environ)
    env.update(OPENAI_API_KEY='EMPTY', HF_HOME=str(BASE / 'bench/hf_home'),
               UV_CACHE_DIR=str(BASE / 'bench/uv_cache'))
    with LOG.open('a') as stream:
        result = subprocess.run([str(BASE / 'AgentCompass/.venv/bin/python'),
                                 str(WORK / 'harbor_entry.py'), str(config_path)],
                                cwd=str(BASE / 'AgentCompass'), env=env,
                                stdout=stream, stderr=subprocess.STDOUT)
    found = {}
    for result_path in (SOURCE / 'results/muse_nvfp4' / claim['job_name']).glob('*/result.json'):
        value = read(result_path)
        if value.get('finished_at'):
            task = Path(value['config']['task']['path']).name
            assert task not in found
            found[task] = str(result_path)
    expected = {row['task'] for row in claim['tasks']}
    with EXIT.open('x') as stream:
        json.dump({'utc': time.time(), 'returncode': result.returncode,
                   'terminal': len(found), 'expected': len(expected),
                   'missing': sorted(expected - set(found)), 'results': found}, stream, indent=2)
        stream.write('\n')
    assert result.returncode == 0 and set(found) == expected
