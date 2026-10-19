#!/usr/bin/env python3
"""Score complete Muse reviews, retaining native verifier outputs lacking Harbor summaries."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018')
PLAN_PATH = PRIVATE / 'revision_capacity_20261018/revision-execution-plan.json'
SOURCE_PLAN = PRIVATE / 'revision/task-preparation-plan.json'
AUDIT = ROOT / 'evidence/swe_review_recovery_control.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    plan = json.loads(PLAN_PATH.read_text())
    source_plan = json.loads(SOURCE_PLAN.read_text())
    pinned_selector = PRIVATE / 'canonical_reviews.py'
    assert sha(pinned_selector) == source_plan['source_files_sha256'][str(pinned_selector)]
    selector = ROOT / 'review_native_selection.py'
    sys.path.insert(0, str(PRIVATE))
    from review_native_selection import inspect_canonical_split
    official = Path(plan['official_repo']) / 'SWE-Review-Bench'
    sys.path.insert(0, str(official))
    from compute_da import compute_da
    result = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Supplementary complete Muse NVFP4 DA based on preserved native verifier reports; '
                 'the pinned task-preparation receipt remains incomplete for two splits.',
        'official_compute_da_sha256': sha(official / 'compute_da.py'),
        'plan_sha256': sha(PLAN_PATH),
        'pinned_selector_sha256': sha(pinned_selector),
        'supplementary_selector_sha256': sha(selector),
        'interrupted_controller_audit_sha256': sha(AUDIT),
        'splits': {},
    }
    for split, spec in plan['splits'].items():
        assert set(spec['expected_ids']) == set(source_plan['splits'][split]['expected_ids'])
        rows = inspect_canonical_split(split, spec['expected_ids'])
        assert rows is not None and len(rows) == spec['expected']
        benchmark = Path(spec['benchmark_snapshot'])
        assert sha(benchmark) == spec['benchmark_snapshot_sha256']
        reviews = []
        selected = {}
        for name, row in sorted(rows.items()):
            for path, expected in row['source_hashes'].items():
                assert sha(path) == expected, path
            trial = Path(row['trial'])
            report_path = trial / 'verifier/review_report.json'
            reviews.append({'instance_id': name,
                            'report': json.loads(report_path.read_text()) if report_path.exists() else None})
            selected[name] = {
                'trial': str(trial),
                'original_result_sha256': row['original_result_sha256'],
                'review_report_sha256': sha(report_path) if report_path.exists() else None,
                'harbor_result_sha256': sha(trial / 'result.json') if (trial / 'result.json').exists() else None,
                'native_verifier_complete_without_harbor_summary': row['native_verifier_complete_without_harbor_summary'],
            }
        metrics = compute_da(reviews, json.loads(benchmark.read_text()))
        assert metrics['total'] == spec['expected']
        native_only = sorted(name for name, row in rows.items()
                             if row['native_verifier_complete_without_harbor_summary'])
        expected_native = {'glm5_500': 8, 'qwen3_coder_30b_500': 2,
                           'qwen3_30b_instruct2507_500': 0}[split]
        assert len(native_only) == expected_native
        receipt = PRIVATE / 'revision/prepared' / split / 'receipt.json'
        if receipt.exists():
            pinned = json.loads(receipt.read_text())
            assert set(pinned['reviews']) == set(rows)
            assert not native_only
        result['splits'][split] = {
            'status': 'pinned_receipt_complete' if receipt.exists() else 'supplementary_complete_da',
            'expected': spec['expected'], 'metrics': metrics,
            'native_verifier_complete_without_harbor_summary': native_only,
            'harbor_terminal_results': spec['expected'] - len(native_only),
            'pinned_receipt_sha256': sha(receipt) if receipt.exists() else None,
            'benchmark_sha256': sha(benchmark), 'selected': selected, 'RRR': None,
            'qualification': 'Official compute_da.py on all expected real review reports. The native-only '
                             'cases passed model-finish and verifier-consistency checks. The original pinned '
                             'revision-preparation protocol does not yet accept missing Harbor summaries.',
        }
    output = ROOT / 'evidence/swe_review_native_complete_da.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: row['metrics'] for name, row in result['splits'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
