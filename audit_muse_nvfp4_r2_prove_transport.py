#!/usr/bin/env python3
"""Anchor the declared replacement's pre-model credential transport failure."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
CLAIM = BASE / 'muse_nvfp4/state/r2-prove-plus-comm-infra-replacement-claim.json'
JOB = BASE / 'results/muse_nvfp4/muse-nvfp4-tb-v1-exact-r2-infra-replacement-prove-plus-comm'
TARGET = ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_transport_failure.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


claim = json.loads(CLAIM.read_text())
assert claim['replacement_job_name'] == JOB.name and claim['task'] == 'prove-plus-comm'
assert digest(Path(claim['replacement_job_config'])) == claim['replacement_job_config_sha256']
trials = [path for path in JOB.glob('prove-plus-comm__*') if path.is_dir()]
assert len(trials) == 1
trial = trials[0]
result_path = trial / 'result.json'
result = json.loads(result_path.read_text())
assert result['finished_at'] and Path(result['task_name']).name == 'prove-plus-comm'
assert result['verifier_result'] is None
agent_result = result['agent_result']
assert agent_result['n_input_tokens'] == agent_result['n_output_tokens'] == 0
assert not agent_result['rollout_details'] and not agent_result['metadata']['api_request_times_msec']
assert not list((trial / 'agent/raw_responses').glob('*.json'))
error = result['exception_info']
assert error['exception_type'] == 'InternalServerError'
assert 'Missing credentials' in error['exception_message']

record = dict(
    generated_utc=datetime.now(timezone.utc).isoformat(),
    scope='First declared infrastructure replacement; failed before any model response.',
    task='prove-plus-comm', job=JOB.name, native_trial=trial.name,
    result_path=str(result_path), result_sha256=digest(result_path),
    claim_path=str(CLAIM), claim_sha256=digest(CLAIM),
    exception_type=error['exception_type'], exception_message=error['exception_message'],
    exception_occurred_at=error['occurred_at'], model_raw_response_count=0,
    native_verifier_reward=None,
    disposition='Transport configuration failed before the first model call because the transient service process lacked OPENAI_API_KEY. Preserve as infrastructure failure; no model score or best-of draw exists.',
)
if TARGET.exists():
    existing = json.loads(TARGET.read_text())
    assert {k: v for k, v in existing.items() if k != 'generated_utc'} == {
        k: v for k, v in record.items() if k != 'generated_utc'
    }
else:
    TARGET.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(task='prove-plus-comm', model_raw_responses=0, native_reward=None)))
