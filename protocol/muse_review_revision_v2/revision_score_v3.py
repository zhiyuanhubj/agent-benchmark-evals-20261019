"""Compute official DA/RRR from the declared gateway recovery queue.

The pinned v1/v2 scorers and host-IP trial failures remain unchanged. This v3
reads only the one-response-per-task gateway recovery results. It preserves v2's
malformed-review fallback; the official metric functions are unchanged.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_revision_outcome(path, instance_id):
    """Absent or ungraded results are pending, never silently converted to zero."""
    path = Path(path)
    result = json.loads(path.read_text())
    if not result.get('finished_at'):
        return None
    reward = (result.get('verifier_result') or {}).get('rewards', {}).get('reward')
    report_path = path.parent / 'verifier/report.json'
    if type(reward) not in {int, float} or reward not in {0, 1} or not report_path.exists():
        return None
    report = json.loads(report_path.read_text())
    assert instance_id in report, 'Native verifier report has unexpected instance identity'
    resolved = report[instance_id]['resolved']
    assert type(resolved) is bool and resolved == bool(reward), 'Reward disagrees with native verifier'
    return dict(resolved=resolved, reward=reward, source_sha256={str(p): sha(p) for p in [path, report_path]})


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({**value, 'utc': time.time()}, indent=2) + '\n')
    temp.replace(path)


def load_function(path, name):
    spec = importlib.util.spec_from_file_location('official_' + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


def main():
    plan = json.loads((ROOT / 'revision-execution-plan.json').read_text())
    official = Path(plan['official_repo']) / 'SWE-Review-Bench'
    sys.path.insert(0, str(official))
    da = load_function(official / 'compute_da.py', 'compute_da')
    rrr = load_function(official / 'compute_rrr.py', 'compute_rrr')
    for name, expected in plan['source_sha256'].items():
        assert sha(name) == expected, name
    while True:
        observed = {}
        for reviewer, root_name in plan['reviewers'].items():
            root = Path(root_name)
            observed[reviewer] = {}
            aggregate_reviews, aggregate_benchmark, aggregate_revisions = [], [], {}
            for split, spec in plan['splits'].items():
                receipt_path = root / 'revision/prepared' / split / 'receipt.json'
                if not receipt_path.exists():
                    observed[reviewer][split] = dict(phase='waiting_for_full_canonical_review', complete=False)
                    continue
                receipt = json.loads(receipt_path.read_text())
                assert set(receipt['reviews']) == set(spec['expected_ids'])
                benchmark_path = Path(spec['benchmark_snapshot'])
                assert sha(benchmark_path) == spec['benchmark_snapshot_sha256']
                benchmark = json.loads(benchmark_path.read_text())
                reviews = []
                invalid_reports = []
                for iid, row in sorted(receipt['reviews'].items()):
                    for name, expected in row['source_hashes'].items():
                        assert sha(name) == expected, 'Canonical review mutation'
                    report_path = Path(row['trial']) / 'verifier/review_report.json'
                    report = None
                    if report_path.exists():
                        try:
                            report = json.loads(report_path.read_text())
                        except json.JSONDecodeError as error:
                            invalid_reports.append(dict(instance_id=iid, path=str(report_path),
                                                        sha256=sha(report_path), parse_error=str(error)))
                    decision = (report or {}).get('decision')
                    if isinstance(decision, dict):
                        decision = decision.get('recommendation')
                    assert decision == row['decision'], 'Canonical decision changed'
                    reviews.append(dict(instance_id=iid, report=report))
                da_metrics = da(reviews, benchmark)
                assert da_metrics['total'] == spec['expected']
                work = root / 'revision/generation' / split
                outcomes, ungraded, seen, sources = {}, {}, set(), {}
                for path in (work / 'gateway-recovery-20261020/queue/results' / split).glob('*/*/result.json'):
                    result = json.loads(path.read_text())
                    if not result.get('task_name'):
                        continue
                    task = Path(result['config']['task']['path']).name
                    config_path = receipt_path.parent / 'tasks' / task / 'tests/config.json'
                    assert config_path.is_file(), 'Unexpected revision task'
                    iid = json.loads(config_path.read_text())['instance_id']
                    assert iid in receipt['expected_rejected'] and iid not in seen, 'Repeated or unexpected revision attempt'
                    seen.add(iid)
                    outcome = native_revision_outcome(path, iid)
                    if outcome is None:
                        ungraded[iid] = dict(result=str(path), finished=bool(result.get('finished_at')),
                            exception_type=(result.get('exception_info') or {}).get('exception_type'))
                    else:
                        outcomes[iid] = outcome['resolved']
                        sources.update(outcome['source_sha256'])
                exit_path = work / 'gateway-recovery-20261020/queue/queue-exit.json'
                queue_done = exit_path.exists() and json.loads(exit_path.read_text()).get('scheduled_attempts_finished') is True
                missing = set(receipt['expected_rejected']) - set(outcomes)
                complete = queue_done and not missing and not ungraded
                evidence = dict(canonical_receipt=str(receipt_path), canonical_receipt_sha256=sha(receipt_path),
                    graded_revision_sources_sha256=sources, outcomes=outcomes, ungraded=ungraded,
                    invalid_original_reports=invalid_reports,
                    missing_native_grades=sorted(missing),
                    qualification='Unfinished or ungraded infrastructure outcomes never become model failures or reward zero. Native first attempts and original approved patches are preserved.')
                state = dict(DA=da_metrics, invalid_report_count=len(invalid_reports),
                    invalid_reports=invalid_reports, expected_revisions=len(receipt['expected_rejected']),
                    native_graded_revisions=len(outcomes), revision_queue_terminal=queue_done,
                    complete=complete, phase='complete' if complete else 'waiting_for_revision_native_grades',
                    missing_native_grade_count=len(missing), RRR=None)
                if complete:
                    metrics = rrr(reviews, outcomes, benchmark)
                    assert metrics['total'] == spec['expected'] and metrics['revised'] == len(outcomes)
                    # Only original model review failures can use the official fallback.
                    assert metrics['fallback'] == da_metrics['model_fail']
                    state['RRR'] = metrics
                    save(root / 'revision/metrics' / (split + '-evidence.json'), evidence)
                    save(root / 'revision/metrics' / (split + '-summary.json'), state)
                observed[reviewer][split] = state
                # Namespacing is solely for aggregating distinct patches sharing a SWE iid.
                aggregate_reviews += [{**row, 'instance_id': split + '/' + row['instance_id']} for row in reviews]
                aggregate_benchmark += [{**row, 'instance_id': split + '/' + row['instance_id']} for row in benchmark]
                aggregate_revisions.update({split + '/' + iid: resolved for iid, resolved in outcomes.items()})
            if len(observed[reviewer]) == 3 and all(value['complete'] for value in observed[reviewer].values()):
                assert len(aggregate_reviews) == len(aggregate_benchmark) == 1384
                summary = dict(complete=True, expected=1384,
                    DA=da(aggregate_reviews, aggregate_benchmark),
                    RRR=rrr(aggregate_reviews, aggregate_revisions, aggregate_benchmark),
                    per_split=observed[reviewer],
                    protocol='Unchanged official metric functions; one canonical review and one original-generator revision per rejection; task identity prefixed by split only during metric aggregation.')
                save(root / 'revision/metrics/full-completion-summary.json', summary)
        current = ROOT / ('revision-scoring-v3-preflight.json' if '--once' in sys.argv
                          else 'revision-scoring-current.json')
        save(current, dict(reviewers=observed,
                           scorer_version='v3_gateway_recovery_and_malformed_original_report_fallback'))
        if '--once' in sys.argv:
            return
        if all((Path(root) / 'revision/metrics/full-completion-summary.json').exists() for root in plan['reviewers'].values()):
            return
        time.sleep(60)


if __name__ == '__main__':
    main()
