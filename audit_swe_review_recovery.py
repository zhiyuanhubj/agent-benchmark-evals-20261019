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
NEW3 = OLD.parent / 'unfinished_report_replacement_20261019'


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
verifier_complete = {}
unfinished_reports = set()
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
            assert len(trial_dirs) == 1
            trial = trial_dirs[0]
            report_path = trial / 'verifier/review_report.json'
            if not report_path.exists():
                unfinished_reports.add((split, task))
                continue
            grade_path = trial / 'verifier/report.json'
            reward_path = trial / 'verifier/reward.txt'
            trajectory_path = trial / 'agent/trajectory.json'
            assert grade_path.exists() and reward_path.exists() and trajectory_path.exists()
            report = json.loads(report_path.read_text())
            grade = json.loads(grade_path.read_text())
            trajectory = json.loads(trajectory_path.read_text())
            assert trajectory['steps'][-1]['tool_calls'][0]['function_name'] == 'finish'
            assert report['decision']['recommendation'] in ('approve', 'request_changes')
            assert grade['recommendation'] == report['decision']['recommendation']
            assert float(reward_path.read_text().strip()) == grade['reward']
            verifier_complete[split + '/' + task] = {
                'trial': str(trial), 'review_report_sha256': sha(report_path),
                'verifier_report_sha256': sha(grade_path),
                'reward_sha256': sha(reward_path),
                'trajectory_sha256': sha(trajectory_path),
                'native_harbor_result_missing': True,
            }
    rows[stem] = {'declared': len(claim['tasks']), 'terminal': terminal,
                  'ungraded_or_not_terminal': len(claim['tasks']) - terminal}
new2 = json.loads((NEW2 / 'parallel-plan.json').read_text())
assert new2['model_id'] == old['model_id'] and new2['harness_root'] == old['harness_root']
assert new2['splits'] == old['splits'] and new2['execution_sha256'] == old['execution_sha256']
assert {(batch['split'], task) for batch in new2['batches'] for task in batch['tasks']} == no_trial_tasks
assert len(no_trial_tasks) == 23 and len(partial_sampled_tasks) == 16
assert no_trial_tasks.isdisjoint(partial_sampled_tasks)
assert len(verifier_complete) == 10 and len(unfinished_reports) == 6
new3 = json.loads((NEW3 / 'parallel-plan.json').read_text())
assert {(batch['split'], task) for batch in new3['batches'] for task in batch['tasks']} == unfinished_reports
assert new3['model_id'] == old['model_id'] and new3['splits'] == old['splits']
evidence = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'old_controller': unit('muse-swe-review-relayed-three-replica-20261018.service'),
    'old_plan_sha256': sha(OLD / 'parallel-plan.json'),
    'old_claims': len(old_claims), 'old_exits': len(list((OLD / 'exits').glob('*.json'))),
    'interrupted_claimed_batches': rows,
    'interrupted_tasks_without_trial_directory': len(no_trial_tasks),
    'interrupted_tasks_with_partial_sampled_trajectory_preserved': len(partial_sampled_tasks),
    'original_native_verifier_complete_without_harbor_summary': verifier_complete,
    'interrupted_without_final_review_report_replacement_count': len(unfinished_reports),
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
    'unfinished_report_replacement': {
        'controller': unit('muse-swe-review-unfinished-6-20261019.service'),
        'plan_sha256': sha(NEW3 / 'parallel-plan.json'),
        'receipt_sha256': sha(NEW3 / 'replacement-receipt.json'),
        'task_count': len(unfinished_reports),
        'sandbox_allocation': 2869, 'model_allocation': 2866,
    },
    'qualification': 'The old controller was killed before three claimed batches ended. Disjoint continuations own 11 unclaimed tasks, 23 claimed tasks with no trial directory, and 6 interrupted tasks with no final review report. Ten original trials already have a completed agent finish step and native verifier report/reward, but lack only the Harbor summary result. Their original outputs are preserved and no replacement draw is scheduled for them.',
}
(ROOT / 'evidence/swe_review_recovery_control.json').write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(evidence))
