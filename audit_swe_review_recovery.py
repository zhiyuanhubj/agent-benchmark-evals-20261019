#!/usr/bin/env python3
"""Reconcile the interrupted SWE-Review controller with its disjoint continuation."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/review_recovery_20261018/parallel_20261018/relayed_20261018')
NEW = OLD.parent / 'unclaimed_continuation_20261019'
NEW2 = OLD.parent / 'no_trial_continuation_20261019'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit(name):
    output = subprocess.check_output(['systemctl', '--user', 'show', name, '-p', 'ActiveState', '-p', 'MainPID', '-p', 'Result'], text=True)
    return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)


old = json.loads((OLD / 'parallel-plan.json').read_text())
new = json.loads((NEW / 'parallel-plan.json').read_text())
assert len(new['batches']) == 1
assert new['batches'][0]['split'] == 'glm5_500' and new['batches'][0]['index'] == 16
assert len(new['batches'][0]['tasks']) == 11
assert new['batches'][0] in old['batches']
assert new['model_id'] == old['model_id'] and new['harness_root'] == old['harness_root']
assert new['splits'] == old['splits'] and new['execution_sha256'] == old['execution_sha256']
old_claims = {p.stem: json.loads(p.read_text()) for p in (OLD / 'claims').glob('*.json')}
new_claims = {p.stem: json.loads(p.read_text()) for p in (NEW / 'claims').glob('*.json')}
new_tasks = set(new['batches'][0]['tasks'])
assert new_tasks.isdisjoint({task for stem, claim in old_claims.items()
                             if stem.startswith('glm5_500-') for task in claim['tasks']})
assert set(new_claims).issubset({'glm5_500-16'})
assert all(set(claim['tasks']) == new_tasks for claim in new_claims.values())
interrupted = sorted(stem for stem in old_claims if not (OLD / 'exits' / (stem + '.json')).exists())
assert set(interrupted) == {'glm5_500-15', 'qwen3_coder_30b_500-14', 'qwen3_coder_30b_500-15'}
rows = {}
no_trial_tasks = set()
partial_sampled_tasks = set()
for stem in interrupted:
    claim = old_claims[stem]
    split, batch = stem.rsplit('-', 1)
    job = Path(old['results_root']) / split / (old['job_prefix'] + '-' + split + '-batch' + batch)
    terminal = 0
    for path in job.glob('*/result.json'):
        terminal += bool(json.loads(path.read_text()).get('finished_at'))
    for task in claim['tasks']:
        trial_dirs = list(job.glob(task + '__*'))
        if not trial_dirs:
            no_trial_tasks.add((split, task))
        elif not any((trial / 'result.json').exists() for trial in trial_dirs):
            partial_sampled_tasks.add((split, task))
    rows[stem] = {'declared': len(claim['tasks']), 'terminal': terminal,
                  'ungraded_or_not_terminal': len(claim['tasks']) - terminal}
new2 = json.loads((NEW2 / 'parallel-plan.json').read_text())
assert new2['model_id'] == old['model_id'] and new2['harness_root'] == old['harness_root']
assert new2['splits'] == old['splits'] and new2['execution_sha256'] == old['execution_sha256']
assert {(batch['split'], task) for batch in new2['batches'] for task in batch['tasks']} == no_trial_tasks
assert len(no_trial_tasks) == 23 and len(partial_sampled_tasks) == 16
assert no_trial_tasks.isdisjoint(partial_sampled_tasks)
evidence = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'old_controller': unit('muse-swe-review-relayed-three-replica-20261018.service'),
    'old_plan_sha256': sha(OLD / 'parallel-plan.json'),
    'old_claims': len(old_claims), 'old_exits': len(list((OLD / 'exits').glob('*.json'))),
    'interrupted_claimed_batches': rows,
    'interrupted_tasks_without_trial_directory': len(no_trial_tasks),
    'interrupted_tasks_with_partial_sampled_trajectory_preserved': len(partial_sampled_tasks),
    'disjoint_never_claimed_continuation': {
        'controller': unit('muse-swe-review-never-claimed-11-20261019.service'),
        'plan_sha256': sha(NEW / 'parallel-plan.json'),
        'receipt_sha256': sha(NEW / 'continuation-receipt.json'),
        'task_count': len(new_tasks), 'claimed': bool(new_claims),
        'sandbox_allocation': 2869, 'model_allocation': 2866,
    },
    'disjoint_no_trial_continuation': {
        'controller': unit('muse-swe-review-no-trial-23-20261019.service'),
        'plan_sha256': sha(NEW2 / 'parallel-plan.json'),
        'receipt_sha256': sha(NEW2 / 'continuation-receipt.json'),
        'task_count': len(no_trial_tasks),
        'sandbox_allocation': 2869, 'model_allocation': 2866,
    },
    'qualification': 'The old controller was killed before three claimed batches ended. Two new controllers own only 11 unclaimed tasks and 23 claimed tasks with no native trial directory. The 16 interrupted trajectories containing sampled model output remain untouched for separate per-trial reconciliation.',
}
(ROOT / 'evidence/swe_review_recovery_control.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence))
