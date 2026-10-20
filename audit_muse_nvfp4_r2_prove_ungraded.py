#!/usr/bin/env python3
"""Anchor the pre-model infrastructure failure on the original round-two trial."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'prove-plus-comm'
JOB = 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b06'
TRIAL = BASE / 'results/muse_nvfp4' / JOB / 'prove-plus-comm__UbAqwmS'
RESULT = TRIAL / 'result.json'
ROUTE = BASE / 'muse_nvfp4/state/future-routes/r2-completion-2866-b06-route.json'
TARGET = ROOT / 'evidence/muse_nvfp4_r2_prove_plus_comm_ungraded.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


route = json.loads(ROUTE.read_text())
assert route['round'] == 2 and route['job_name'] == JOB and TASK in route['tasks']
original_config = Path(route['original_config'])
effective_config = Path(route['effective_config'])
assert digest(original_config) == route['original_sha256']
assert digest(effective_config) == route['effective_sha256']
original = json.loads(original_config.read_text())
effective = json.loads(effective_config.read_text())
assert original['tasks'] == effective['tasks']
assert [Path(item['path']).name for item in original['tasks']] == route['tasks']
assert effective['agents'][0]['kwargs']['api_base'] == route['endpoint']
assert original['retry']['max_retries'] == effective['retry']['max_retries'] == 0
assert original['n_attempts'] == effective['n_attempts'] == 1

result = json.loads(RESULT.read_text())
assert Path(result['task_name']).name == TASK and result['finished_at']
assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
assert result['agent_result'] is None and result['verifier_result'] is None
assert result['agent_execution'] is None and result['step_results'] is None
assert not list((TRIAL / 'agent/raw_responses').glob('*.json'))
error = result['exception_info']
assert error['exception_type'] == 'RuntimeError'
assert error['exception_message'] == 'Command timed out after 120 seconds'
assert '_setup_agent' in error['exception_traceback']
assert '_install_recording_tools' in error['exception_traceback']

record = dict(
    generated_utc=datetime.now(timezone.utc).isoformat(),
    scope='Exact user-supplied-image TB2.1, Muse NVFP4, round 2, original first attempt only.',
    task=TASK, job=JOB, native_trial=TRIAL.name,
    result_path=str(RESULT), result_sha256=digest(RESULT),
    route_path=str(ROUTE), route_sha256=digest(ROUTE),
    original_config_path=str(original_config), original_config_sha256=digest(original_config),
    effective_config_path=str(effective_config), effective_config_sha256=digest(effective_config),
    exception_type=error['exception_type'], exception_message=error['exception_message'],
    exception_occurred_at=error['occurred_at'], model_raw_response_count=0,
    native_verifier_reward=None,
    disposition='Ungraded pre-model setup timeout while installing recording tools. No model response or agent execution exists. Preserve original result; one separately declared infrastructure replacement may fill its missing grade.',
)
TARGET.parent.mkdir(parents=True, exist_ok=True)
if TARGET.exists():
    existing = json.loads(TARGET.read_text())
    assert {k: v for k, v in existing.items() if k != 'generated_utc'} == {
        k: v for k, v in record.items() if k != 'generated_utc'
    }, 'Previously anchored ungraded trial changed'
else:
    TARGET.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(task=TASK, reward=None, model_raw_responses=0)))
