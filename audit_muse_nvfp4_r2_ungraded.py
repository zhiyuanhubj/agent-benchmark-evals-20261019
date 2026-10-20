#!/usr/bin/env python3
"""Anchor the ungraded native TB2.1 round-two attempt without assigning reward."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'password-recovery'
JOB = 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b05'
TRIAL = BASE / 'results/muse_nvfp4' / JOB / 'password-recovery__mCY6tLR'
RESULT = TRIAL / 'result.json'
TRAJECTORY = TRIAL / 'agent/trajectory.json'
ROUTE = BASE / 'muse_nvfp4/state/future-routes/r2-completion-2866-b05-route.json'
TARGET = ROOT / 'evidence/muse_nvfp4_r2_password_recovery_ungraded.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path):
    return str(path.relative_to(HOME))


route = json.loads(ROUTE.read_text())
assert route['round'] == 2 and route['job_name'] == JOB and TASK in route['tasks']
original = Path(route['original_config'])
effective = Path(route['effective_config'])
assert sha(original) == route['original_sha256']
assert sha(effective) == route['effective_sha256']
source_config = json.loads(original.read_text())
actual_config = json.loads(effective.read_text())
assert [Path(x['path']).name for x in source_config['tasks']] == route['tasks']
assert actual_config['tasks'] == source_config['tasks']
assert actual_config['agents'][0]['kwargs']['api_base'] == route['endpoint']
assert source_config['retry']['max_retries'] == actual_config['retry']['max_retries'] == 0

result = json.loads(RESULT.read_text())
assert Path(result['task_name']).name == TASK and result['finished_at']
assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
error = result['exception_info']
assert error['exception_type'] == 'RuntimeError'
assert 'tmux send-keys' in error['exception_message']
assert 'no server running on /tmp/tmux-0/default' in error['exception_message']
trajectory = json.loads(TRAJECTORY.read_text())
assert trajectory['steps']
raw = sorted((TRIAL / 'agent/raw_responses').glob('*.json'))
assert raw
raw_rows = []
for path in raw:
    response = json.loads(path.read_text())
    assert response['model'] == 'muse-spark-open-nvfp4'
    messages = [x.get('message') or {} for x in response.get('choices', [])]
    raw_rows.append(dict(path=rel(path), sha256=sha(path),
                         nonempty_reasoning=any(bool(m.get('reasoning_content')) for m in messages)))

record = dict(
    generated_utc=datetime.now(timezone.utc).isoformat(),
    scope='Exact user-supplied-image TB2.1, Muse NVFP4, round 2, original first attempt only.',
    task=TASK, job=JOB, native_trial=TRIAL.name,
    result_path=rel(RESULT), result_sha256=sha(RESULT),
    trajectory_path=rel(TRAJECTORY), trajectory_sha256=sha(TRAJECTORY),
    route_path=rel(ROUTE), route_sha256=sha(ROUTE),
    original_config_path=rel(original), original_config_sha256=sha(original),
    effective_config_path=rel(effective), effective_config_sha256=sha(effective),
    exception_type=error['exception_type'],
    exception_message=error['exception_message'],
    exception_occurred_at=error['occurred_at'],
    model_raw_response_count=len(raw),
    model_raw_response_with_reasoning_count=sum(row['nonempty_reasoning'] for row in raw_rows),
    raw_responses=raw_rows,
    native_verifier_reward=None,
    disposition='Unscored original attempt. The agent lost its tmux session before native verification; preserve this trajectory and all raw responses. A replacement, if launched, must be declared separately as an infrastructure draw. This record does not establish why tmux exited.',
)
TARGET.parent.mkdir(parents=True, exist_ok=True)
if TARGET.exists():
    existing = json.loads(TARGET.read_text())
    assert {k: v for k, v in existing.items() if k != 'generated_utc'} == {
        k: v for k, v in record.items() if k != 'generated_utc'
    }, 'Previously anchored ungraded trial changed'
    record = existing
else:
    temporary = TARGET.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(TARGET)
print(json.dumps(dict(task=TASK, reward=None, raw_responses=len(raw),
                      nonempty_reasoning=record['model_raw_response_with_reasoning_count'])))
