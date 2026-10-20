#!/usr/bin/env python3
"""Anchor the original ungraded task whose shared Docker disk reached 100%."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
BASE = HOME / '.private/beam_20261018/tb_v1_exact_images_20261019'
TASK = 'pytorch-model-cli'
JOB = 'muse-nvfp4-tb-v1-exact-r2-completion-2866-b06'
TRIAL = BASE / 'results/muse_nvfp4' / JOB / 'pytorch-model-cli__mJNSKQ5'
RESULT = TRIAL / 'result.json'
TRAJECTORY = TRIAL / 'agent/trajectory.json'
ROUTE = BASE / 'muse_nvfp4/state/future-routes/r2-completion-2866-b06-route.json'
TARGET = ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_ungraded.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


route = json.loads(ROUTE.read_text())
assert route['round'] == 2 and route['job_name'] == JOB and TASK in route['tasks']
original = Path(route['original_config'])
effective = Path(route['effective_config'])
assert digest(original) == route['original_sha256']
assert digest(effective) == route['effective_sha256']
source_config = json.loads(original.read_text())
actual_config = json.loads(effective.read_text())
assert source_config['tasks'] == actual_config['tasks']
assert actual_config['agents'][0]['kwargs']['api_base'] == route['endpoint']
assert source_config['retry']['max_retries'] == actual_config['retry']['max_retries'] == 0
assert source_config['n_attempts'] == actual_config['n_attempts'] == 1

result = json.loads(RESULT.read_text())
assert Path(result['task_name']).name == TASK and result['finished_at']
assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') is None
error = result['exception_info']
assert error['exception_type'] == 'RuntimeError'
assert 'tmux send-keys' in error['exception_message']
assert 'No space left on device' in error['exception_message']
trajectory = json.loads(TRAJECTORY.read_text())
assert trajectory['steps']
observations = '\n'.join(item.get('content', '') for step in trajectory['steps']
                         for item in (step.get('observation') or {}).get('results', []))
assert 'overlay                   500G  500G   32K 100%' in observations
assert '/dev/nvme1n1              500G  500G   32K 100%' in observations
raw = sorted((TRIAL / 'agent/raw_responses').glob('*.json'))
assert raw
raw_rows = []
for path in raw:
    response = json.loads(path.read_text())
    assert response['model'] == 'muse-spark-open-nvfp4'
    raw_rows.append(dict(path=str(path), sha256=digest(path),
                         nonempty_reasoning=any(bool((item.get('message') or {}).get('reasoning_content'))
                                                for item in response.get('choices', []))))

record = dict(
    generated_utc=datetime.now(timezone.utc).isoformat(),
    scope='Exact user-supplied-image TB2.1, Muse NVFP4, round 2, original first attempt only.',
    task=TASK, job=JOB, native_trial=TRIAL.name,
    result_path=str(RESULT), result_sha256=digest(RESULT),
    trajectory_path=str(TRAJECTORY), trajectory_sha256=digest(TRAJECTORY),
    route_path=str(ROUTE), route_sha256=digest(ROUTE),
    original_config_path=str(original), original_config_sha256=digest(original),
    effective_config_path=str(effective), effective_config_sha256=digest(effective),
    exception_type=error['exception_type'], exception_message=error['exception_message'],
    exception_occurred_at=error['occurred_at'],
    observed_overlay_full='500G used / 500G total, 32K available, 100% utilization',
    model_raw_response_count=len(raw),
    model_raw_response_with_reasoning_count=sum(item['nonempty_reasoning'] for item in raw_rows),
    raw_responses=raw_rows, native_verifier_reward=None,
    disposition='Unscored first draw: tmux failed while the sandbox overlay backing filesystem reported 100% utilization. The observed full shared disk does not establish which process consumed the space. Preserve all original model replies and do not assign reward zero or success. Any later draw must be declared separately.',
)
if TARGET.exists():
    existing = json.loads(TARGET.read_text())
    assert {k: v for k, v in existing.items() if k != 'generated_utc'} == {
        k: v for k, v in record.items() if k != 'generated_utc'
    }
else:
    TARGET.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(dict(task=TASK, reward=None, raw_responses=len(raw),
                      thinking=sum(item['nonempty_reasoning'] for item in raw_rows))))
