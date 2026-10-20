#!/usr/bin/env python3
"""Audit live SWE-Review revision attempts without inventing partial RRR scores."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
GROUPS = (
    ('muse-nvfp4', 'qwen3_coder_30b_500', HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_coder_30b_500'),
    ('muse-nvfp4', 'qwen3_30b_instruct2507_500', HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500'),
    ('beam-bf16', 'qwen3_coder_30b_500', HOME / '.private/beam_20261018/review_bench/revision/generation/qwen3_coder_30b_500'),
    ('beam-bf16', 'qwen3_30b_instruct2507_500', HOME / '.private/beam_20261018/review_bench/revision/generation/qwen3_30b_instruct2507_500'),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def trial_results(root):
    for path in sorted(root.rglob('result.json')) if root.exists() else ():
        try:
            data = path.read_bytes()
            result = json.loads(data)
        except json.JSONDecodeError:
            continue  # A live native writer may be updating its result file.
        if result.get('task_name'):
            yield path, result, hashlib.sha256(data).hexdigest()


rows = []
for reviewer, split, work in GROUPS:
    recovery = work / 'gateway-recovery-20261020'
    queue = recovery / 'queue'
    plan_path = queue / 'queue-plan.json'
    plan = json.loads(plan_path.read_text())
    tasks = plan['splits'][split]['tasks']
    expected = set(tasks)
    assert len(tasks) == len(expected)
    assert plan['api_base'].startswith('http://172.17.0.1:')
    gate = Path(plan['required_gate_files'][0])
    gate_receipt = json.loads(gate.read_text())
    assert gate_receipt['passed'] and gate_receipt['native_reward'] == 1.0
    old = work / 'queue/results'
    old_raw = list(old.rglob('raw_responses/*.json')) if old.exists() else []
    old_trajectories = list(old.rglob('trajectory.json')) if old.exists() else []
    old_completions = list(old.rglob('completions/*.json')) if old.exists() else []
    records = {}
    errors = []
    for path, result, result_sha in trial_results(queue / 'results'):
        task = result['task_name']
        if task not in expected:
            errors.append(f'unexpected_task:{task}')
            continue
        if task in records:
            errors.append(f'duplicate_model_attempt:{task}')
            continue
        finished = bool(result.get('finished_at'))
        reward = (result.get('verifier_result') or {}).get('rewards', {}).get('reward')
        report = path.parent / 'verifier/report.json'
        graded = finished and type(reward) in (int, float) and reward in (0, 1) and report.exists()
        exception = result.get('exception_info') or {}
        records[task] = dict(result=str(path.relative_to(HOME)), result_sha256=result_sha,
                             finished=finished, native_graded=graded,
                             reward=reward if graded else None,
                             verifier_report_sha256=sha(report) if graded else None,
                             trajectory_saved=(path.parent / 'agent/trajectory.json').exists(),
                             exception_type=exception.get('exception_type'),
                             exception_message=exception.get('exception_message'))
    exit_path = queue / 'queue-exit.json'
    exit_state = json.loads(exit_path.read_text()) if exit_path.exists() else None
    graded = sum(row['native_graded'] for row in records.values())
    success = sum(row['reward'] == 1 for row in records.values())
    failures_before_response = sum(row['exception_message'] == 'Model unavailable before first response'
                                   for row in records.values())
    if old_raw or old_trajectories or old_completions:
        errors.append('old_host_ip_attempt_has_saved_model_output')
    if failures_before_response:
        errors.append('gateway_recovery_has_pre_model_connection_failure')
    rows.append(dict(reviewer=reviewer, split=split, expected_revisions=len(tasks),
                     queue_plan_sha256=sha(plan_path), synthetic_preflight_sha256=sha(gate),
                     old_host_ip_native_results=sum(1 for _ in trial_results(old)),
                     old_host_ip_saved_model_responses=len(old_raw) + len(old_trajectories) + len(old_completions),
                     gateway_model_attempt_result_files=len(records), native_graded_revisions=graded,
                     native_successful_revisions=success,
                     gateway_trajectories=sum(row['trajectory_saved'] for row in records.values()),
                     pre_model_connection_failures=failures_before_response,
                     queue_scheduled_attempts_finished=bool(exit_state and exit_state.get('scheduled_attempts_finished')),
                     complete=bool(exit_state and exit_state.get('scheduled_attempts_finished') and
                                   len(records) == len(tasks) and graded == len(tasks) and not errors),
                     errors=errors, records=records))

out = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
           scope='Live native SWE-Review original-generator revision results. Partial graded counts are progress, not RRR or a benchmark accuracy. Synthetic preflights and old pre-model connection failures are excluded.',
           model_attempt_policy='One scored gateway-recovery result per canonically rejected PR; native verifier reward and report are required for a grade.',
           groups=rows)
target = ROOT / 'evidence/swe_review_revision_gateway_progress.json'
temp = target.with_suffix('.tmp')
temp.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
temp.replace(target)
print(json.dumps({f"{r['reviewer']}/{r['split']}":
                  dict(graded=r['native_graded_revisions'], expected=r['expected_revisions'],
                       errors=r['errors']) for r in rows}))
