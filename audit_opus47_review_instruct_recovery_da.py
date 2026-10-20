#!/usr/bin/env python3
"""Score the complete Opus instruct review split with its declared interruption recovery."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
PRIVATE = HOME / '.private/opus47_review_20261020'
CLAIM = ROOT / 'evidence/opus47_review_instruct_cancelled_recovery_claim.json'
SOURCE_RELEASE = ROOT / 'evidence/opus47_review_instruct_cancelled_source_release_receipt.json'
METRIC_PLAN = HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision_capacity_20261018/revision-execution-plan.json'
SOURCE_JOB = PRIVATE / 'swe_review/qwen3_30b_instruct2507_500/results/opus47-swe-review-qwen3_30b_instruct2507_500-r1'
RECOVERY_JOB = SOURCE_JOB.parent / 'opus47-swe-review-instruct-cancelled-recovery-20261020'
OUTPUT = ROOT / 'evidence/opus47_review_instruct_recovery_da.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_trials(root):
    rows = {}
    for trial in root.iterdir():
        result_path = trial / 'result.json'
        if not trial.is_dir() or not result_path.is_file():
            continue
        result = json.loads(result_path.read_text())
        task = Path(result['task_id']['path']).name
        assert task not in rows, (root, task)
        rows[task] = (trial, result_path, result)
    return rows


def main():
    claim = json.loads(CLAIM.read_text())
    receipt = json.loads(SOURCE_RELEASE.read_text())
    assert receipt['claim_sha256'] == sha(CLAIM)
    assert receipt['remote_sha256_and_size_verified']
    assert receipt['source_native_result_matches_claim']
    assert receipt['source_model_completion_files_matching_claim'] == claim['original_model_completion_count']
    assert sha(claim['original_config']) == claim['original_config_sha256']
    assert sha(claim['replacement_config']) == claim['replacement_config_sha256']
    assert sha(claim['original_trial'] + '/result.json') == claim['original_trial_result_sha256']
    assert sha(METRIC_PLAN) == claim['official_metric_plan_sha256']

    plan = json.loads(METRIC_PLAN.read_text())
    split = plan['splits']['qwen3_30b_instruct2507_500']
    expected = set(split['expected_ids'])
    assert len(expected) == split['expected'] == 422
    source = native_trials(SOURCE_JOB)
    assert set(source) == expected
    cancelled = claim['task']
    assert cancelled in source
    original = source[cancelled][2]
    assert original['exception_info']['exception_type'] == 'CancelledError'
    assert not (source[cancelled][0] / 'verifier/review_report.json').exists()
    assert not (source[cancelled][0] / 'agent/trajectory.json').exists()

    assert (RECOVERY_JOB / 'result.json').is_file(), 'Recovery has not finished'
    job = json.loads((RECOVERY_JOB / 'result.json').read_text())
    stats = job['stats']
    assert job['finished_at'] and job['n_total_trials'] == 1
    assert stats['n_completed_trials'] == 1 and stats['n_errored_trials'] == 0
    replacement = native_trials(RECOVERY_JOB)
    assert set(replacement) == {cancelled}
    trial, result_path, result = replacement[cancelled]
    assert result['exception_info'] is None and result['verifier_result'] is not None
    assert result['config']['agent']['model_name'] == 'openai/claude-opus-4-7'
    replacement_report = trial / 'verifier/review_report.json'
    assert replacement_report.is_file()

    benchmark = Path(split['benchmark_snapshot'])
    assert sha(benchmark) == split['benchmark_snapshot_sha256']
    official = Path(plan['official_repo']) / 'SWE-Review-Bench'
    sys.path.insert(0, str(official))
    from compute_da import compute_da
    from utils import extract_decision

    selected = {}
    reviews = []
    for task in sorted(expected):
        if task == cancelled:
            chosen_trial, chosen_result = trial, result_path
            selection = 'declared_cancelled_interruption_recovery'
        else:
            chosen_trial, chosen_result, source_result = source[task]
            assert source_result['finished_at'] is not None
            selection = 'original_first_attempt'
        report_path = chosen_trial / 'verifier/review_report.json'
        assert report_path.is_file(), (task, report_path)
        report = json.loads(report_path.read_text())
        reviews.append({'instance_id': task, 'report': report})
        selected[task] = {
            'selection': selection,
            'native_result': str(chosen_result),
            'native_result_sha256': sha(chosen_result),
            'review_report': str(report_path),
            'review_report_sha256': sha(report_path),
            'parseable_decision': extract_decision(report) is not None,
        }
    metrics = compute_da(reviews, json.loads(benchmark.read_text()))
    assert metrics['total'] == 422
    assert sum(row['selection'] == 'declared_cancelled_interruption_recovery'
               for row in selected.values()) == 1
    output = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'model': 'claude-opus-4-7',
        'split': 'qwen3_30b_instruct2507_500',
        'status': 'complete_with_declared_infrastructure_replacement_release_pending',
        'metric': 'Official compute_da.py on 421 original native reviews and one predeclared interruption replacement.',
        'official_compute_da_sha256': sha(official / 'compute_da.py'),
        'metric_benchmark_sha256': sha(benchmark),
        'claim_sha256': sha(CLAIM),
        'source_release_receipt_sha256': sha(SOURCE_RELEASE),
        'source_job_result_sha256': sha(SOURCE_JOB / 'result.json'),
        'recovery_job_result_sha256': sha(RECOVERY_JOB / 'result.json'),
        'DA': metrics,
        'RRR': None,
        'selected': selected,
        'qualification': 'This is a complete decision-accuracy calculation with one declared infrastructure replacement, not an unchanged first-attempt-only split. RRR and release coverage of the replacement remain pending.',
    }
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'output': str(OUTPUT), 'DA': metrics, 'selected': len(selected)}))


if __name__ == '__main__':
    main()
