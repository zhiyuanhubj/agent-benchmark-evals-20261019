#!/usr/bin/env python3
"""Declare exactly one replacement for the pre-model prove-plus-comm timeout."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'prove-plus-comm'
JOB = 'muse-nvfp4-tb-v1-exact-r2-infra-replacement-prove-plus-comm'
SOURCE = BASE / 'muse_nvfp4/configs/r2-completion-2866-b06.json'
CONFIG = BASE / 'muse_nvfp4/configs/r2-infra-replacement-prove-plus-comm.json'
CLAIM = BASE / 'muse_nvfp4/state/r2-prove-plus-comm-infra-replacement-claim.json'
EVIDENCE = ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json'
ROUTE = BASE / 'muse_nvfp4/state/future-routes/r2-completion-2866-b06-route.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text() == serialized, f'Existing declaration changed: {path}'
    else:
        path.write_text(serialized)


evidence = json.loads(EVIDENCE.read_text())
assert evidence['native_verifier_reward'] is None and evidence['model_raw_response_count'] == 0
assert digest(Path(evidence['result_path'])) == evidence['result_sha256']
route = json.loads(ROUTE.read_text())
assert route['round'] == 2 and route['original_config'] == str(SOURCE)
assert digest(ROUTE) == evidence['route_sha256']
source = json.loads(SOURCE.read_text())
assert source['job_name'] == 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b06'
assert source['retry']['max_retries'] == 0 and source['n_attempts'] == 1
assert source['agents'][0]['kwargs']['api_base'] == 'http://10.1.95.27:31320/v1'
tasks = [item for item in source['tasks'] if Path(item['path']).name == TASK]
assert len(tasks) == 1
endpoint = source['agents'][0]['kwargs']['api_base']
with urlopen(endpoint + '/models', timeout=5) as response:
    models = json.load(response)
assert any(item.get('id') == 'muse-spark-open-nvfp4' for item in models.get('data', []))

replacement = copy.deepcopy(source)
replacement['job_name'] = JOB
replacement['tasks'] = tasks
replacement['n_concurrent_trials'] = 1
save_new(CONFIG, replacement)
assert not (BASE / 'results/muse_nvfp4' / JOB).exists(), 'Replacement already started'
claim = dict(
    prepared_utc=datetime.now(timezone.utc).isoformat(),
    scope='One infrastructure replacement of an original pre-model, ungraded Muse NVFP4 exact-image TB2.1 round-2 prove-plus-comm trial.',
    original_result_path=evidence['result_path'], original_result_sha256=evidence['result_sha256'],
    original_ungraded_evidence=str(EVIDENCE), original_ungraded_evidence_sha256=digest(EVIDENCE),
    original_route_path=str(ROUTE), original_route_sha256=digest(ROUTE),
    source_job_config=str(SOURCE), source_job_config_sha256=digest(SOURCE),
    replacement_job_config=str(CONFIG), replacement_job_config_sha256=digest(CONFIG),
    replacement_job_name=JOB, task=TASK, task_toml_sha256=digest(Path(tasks[0]['path']) / 'task.toml'),
    model_endpoint=endpoint, model_id='muse-spark-open-nvfp4', model_ready_check=models,
    only_changes=['job_name', 'single original task', 'one concurrent trial', 'endpoint restored to original pinned Muse NVFP4 service after routed 2812 attempt'],
    no_retry=True,
    metric_policy='Original attempt had no model response and no native grade. One replacement attempt may fill this single missing grade. Preserve both attempts; never select best-of.',
)
save_new(CLAIM, claim)
print(json.dumps(dict(claim=str(CLAIM), config=str(CONFIG), config_sha256=digest(CONFIG))))
