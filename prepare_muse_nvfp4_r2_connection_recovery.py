#!/usr/bin/env python3
"""Declare one infrastructure replacement for each round-2 connection failure."""

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
CONFIGS = ROOT / 'muse_nvfp4/configs'
RESULTS = ROOT / 'results/muse_nvfp4'
STATE = ROOT / 'muse_nvfp4/state'
JOB = 'muse-nvfp4-tb-v1-exact-r2-connection-recovery-20261020'
CONFIG = CONFIGS / 'r2-connection-recovery-20261020.json'
CLAIM = STATE / 'r2-connection-recovery-20261020-claim.json'
READY = STATE / 'reassigned-2867/endpoint-ready.json'
IMAGES = ROOT / 'allocation-2919/images-ready.json'

FAILURES = {
    'path-tracing': 5,
    'path-tracing-reverse': 5,
    'polyglot-c-py': 5,
    'protein-assembly': 6,
    'qemu-startup': 6,
    'query-optimize': 6,
    'sanitize-git-repo': 7,
    'schemelike-metacircular-eval': 7,
    'sparql-university': 7,
    'sqlite-db-truncate': 7,
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert not CONFIG.exists() and not CLAIM.exists(), 'An existing claim requires audit'
assert not (RESULTS / JOB).exists(), 'A recovery attempt has already started'
images = json.loads(IMAGES.read_text())
assert images['count'] == 89 and images['all_archive_identities_verified']
ready = json.loads(READY.read_text())
assert ready['allocation'] == 2867 and ready['model'] == 'muse-spark-open-nvfp4'
assert ready['api_base'] == 'http://10.1.105.182:31321/v1'

source_configs = {}
for batch in (5, 6, 7):
    path = CONFIGS / f'r2-completion-2866-b{batch:02}.json'
    value = json.loads(path.read_text())
    assert value['job_name'] == f'muse-nvfp4-tb-v1-exact-r2-completion-2866-b{batch:02}'
    assert value['retry']['max_retries'] == 0 and value['n_attempts'] == 1
    source_configs[batch] = (path, value)
reference = copy.deepcopy(source_configs[5][1])
for _, value in source_configs.values():
    comparable = copy.deepcopy(value)
    comparable['job_name'] = reference['job_name']
    comparable['tasks'] = reference['tasks']
    comparable['agents'][0]['kwargs']['api_base'] = reference['agents'][0]['kwargs']['api_base']
    assert comparable == reference, 'Source batches differ beyond task list and job name'

tasks = []
origins = []
for name, batch in FAILURES.items():
    source_path, source = source_configs[batch]
    matches = [task for task in source['tasks'] if Path(task['path']).name == name]
    assert len(matches) == 1, (name, batch)
    task = matches[0]
    job_dir = RESULTS / source['job_name']
    result_paths = []
    for path in job_dir.glob('*/result.json'):
        result = json.loads(path.read_text())
        if Path(result['config']['task']['path']).name == name:
            result_paths.append(path)
    assert len(result_paths) == 1, (name, result_paths)
    result_path = result_paths[0]
    result = json.loads(result_path.read_text())
    route_path = STATE / f'future-routes/r2-completion-2866-b{batch:02}-route.json'
    route = json.loads(route_path.read_text())
    assert route['original_sha256'] == sha(source_path)
    assert route['effective_sha256'] == sha(Path(route['effective_config']))
    assert result['finished_at']
    assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
    error = result.get('exception_info') or {}
    assert error.get('exception_type') == 'InternalServerError'
    assert 'Connection error' in error.get('exception_message', '')
    assert result['config']['agent']['kwargs']['api_base'] == route['endpoint']
    task_card = Path(task['path']) / 'task.toml'
    assert task_card.is_file()
    origins.append({
        'task': name,
        'source_batch': batch,
        'source_config': str(source_path),
        'source_config_sha256': sha(source_path),
        'route_receipt': str(route_path),
        'route_receipt_sha256': sha(route_path),
        'original_result': str(result_path),
        'original_result_sha256': sha(result_path),
        'original_endpoint': route['endpoint'],
        'original_raw_model_responses': len(list((result_path.parent / 'agent/raw_responses').glob('*.json'))),
        'task_toml_sha256': sha(task_card),
        'original_exception_type': error['exception_type'],
    })
    tasks.append(task)

replacement = copy.deepcopy(reference)
replacement['job_name'] = JOB
replacement['tasks'] = tasks
replacement['n_concurrent_trials'] = 2
replacement['agents'][0]['kwargs']['api_base'] = ready['api_base']
CONFIG.write_text(json.dumps(replacement, ensure_ascii=False, indent=2) + '\n')
claim = {
    'prepared_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'One separate infrastructure replacement per ungraded round-2 model-endpoint connection failure',
    'job_name': JOB,
    'config': str(CONFIG),
    'config_sha256': sha(CONFIG),
    'model_endpoint': ready['api_base'],
    'ready_proof': str(READY),
    'ready_proof_sha256': sha(READY),
    'image_proof': str(IMAGES),
    'image_proof_sha256': sha(IMAGES),
    'origins': origins,
    'one_replacement_draw_per_task': True,
    'model_retry_disabled': True,
    'metric_policy': 'Preserve original ungraded attempts and partial responses; count at most one separately declared replacement native reward for each task, with no best-of selection.',
}
CLAIM.write_text(json.dumps(claim, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'claim': str(CLAIM), 'config': str(CONFIG), 'tasks': len(tasks), 'config_sha256': sha(CONFIG)}))
