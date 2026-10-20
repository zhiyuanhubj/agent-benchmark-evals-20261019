#!/usr/bin/env python3
"""Declare a single corrected service-environment run after zero model draws."""
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
SOURCE = BASE / 'muse_nvfp4/configs/r2-infra-replacement-prove-plus-comm.json'
JOB = 'muse-nvfp4-tb-v1-exact-r2-infra-transport-correction-prove-plus-comm'
CONFIG = BASE / 'muse_nvfp4/configs/r2-infra-transport-correction-prove-plus-comm.json'
CLAIM = BASE / 'muse_nvfp4/state/r2-prove-plus-comm-transport-correction-claim.json'
ORIGINAL = ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json'
FAILED = ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    serialized = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    if path.exists():
        assert path.read_text() == serialized, f'Existing declaration changed: {path}'
    else:
        path.write_text(serialized)


original = json.loads(ORIGINAL.read_text())
failed = json.loads(FAILED.read_text())
assert original['native_verifier_reward'] is None and original['model_raw_response_count'] == 0
assert failed['native_verifier_reward'] is None and failed['model_raw_response_count'] == 0
assert digest(Path(original['result_path'])) == original['result_sha256']
assert digest(Path(failed['result_path'])) == failed['result_sha256']
source = json.loads(SOURCE.read_text())
assert source['job_name'] == 'muse-nvfp4-tb-v1-exact-r2-infra-replacement-prove-plus-comm'
assert source['retry']['max_retries'] == 0 and source['n_attempts'] == 1
assert [Path(item['path']).name for item in source['tasks']] == [TASK]
assert source['agents'][0]['env']['OPENAI_API_KEY'] == 'EMPTY'
endpoint = source['agents'][0]['kwargs']['api_base']
with urlopen(endpoint + '/models', timeout=5) as response:
    models = json.load(response)
assert any(item.get('id') == 'muse-spark-open-nvfp4' for item in models.get('data', []))

correction = copy.deepcopy(source)
correction['job_name'] = JOB
save_new(CONFIG, correction)
assert not (BASE / 'results/muse_nvfp4' / JOB).exists(), 'Correction already started'
claim = dict(
    prepared_utc=datetime.now(timezone.utc).isoformat(),
    scope='One corrected service-environment run after both earlier attempts ended before any model response.',
    task=TASK, original_ungraded_evidence=str(ORIGINAL), original_ungraded_evidence_sha256=digest(ORIGINAL),
    failed_transport_evidence=str(FAILED), failed_transport_evidence_sha256=digest(FAILED),
    source_job_config=str(SOURCE), source_job_config_sha256=digest(SOURCE),
    replacement_job_config=str(CONFIG), replacement_job_config_sha256=digest(CONFIG),
    replacement_job_name=JOB, model_endpoint=endpoint, model_id='muse-spark-open-nvfp4',
    model_ready_check=models, service_process_environment={'OPENAI_API_KEY': 'EMPTY'},
    only_changes=['job_name', 'service process OPENAI_API_KEY=EMPTY to satisfy LiteLLM client construction'],
    no_retry=True,
    metric_policy='Both earlier attempts have zero raw model responses and no native grade. Count at most one native grade from this correction for the original task; preserve all attempts and never select best-of.',
)
save_new(CLAIM, claim)
print(json.dumps(dict(claim=str(CLAIM), config=str(CONFIG), config_sha256=digest(CONFIG))))
