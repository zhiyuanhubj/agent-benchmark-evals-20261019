#!/usr/bin/env python3
"""Publish official decision accuracy only for fully sealed SWE-Review splits."""
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAN_PATH = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/revision_capacity_20261018/revision-execution-plan.json')
PLAN = json.loads(PLAN_PATH.read_text())
OFFICIAL = Path(PLAN['official_repo']) / 'SWE-Review-Bench'
sys.path.insert(0, str(OFFICIAL))
from compute_da import compute_da  # noqa: E402


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    result = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'metric': 'Official SWE-Review compute_da.py, complete canonical review splits only',
        'metric_source_sha256': digest(OFFICIAL / 'compute_da.py'),
        'plan_sha256': digest(PLAN_PATH),
        'reviewers': {},
    }
    for reviewer, root_name in PLAN['reviewers'].items():
        root = Path(root_name)
        result['reviewers'][reviewer] = {}
        for split, spec in PLAN['splits'].items():
            receipt_path = root / 'revision/prepared' / split / 'receipt.json'
            if not receipt_path.exists():
                continue
            receipt = json.loads(receipt_path.read_text())
            assert set(receipt['reviews']) == set(spec['expected_ids'])
            assert len(receipt['reviews']) == spec['expected']
            benchmark_path = Path(spec['benchmark_snapshot'])
            assert digest(benchmark_path) == spec['benchmark_snapshot_sha256']
            reviews = []
            invalid_reports = []
            for iid, row in sorted(receipt['reviews'].items()):
                for source, expected in row['source_hashes'].items():
                    assert digest(source) == expected, source
                report_path = Path(row['trial']) / 'verifier/review_report.json'
                report = None
                if report_path.exists():
                    try:
                        report = json.loads(report_path.read_text())
                    except json.JSONDecodeError as error:
                        invalid_reports.append({'instance_id': iid, 'path': str(report_path),
                                                'sha256': digest(report_path), 'parse_error': str(error)})
                reviews.append({'instance_id': iid, 'report': report})
            metrics = compute_da(reviews, json.loads(benchmark_path.read_text()))
            assert metrics['total'] == spec['expected']
            result['reviewers'][reviewer][split] = {
                'status': 'final_da_for_this_split',
                'expected': spec['expected'],
                'metrics': metrics,
                'canonical_receipt_sha256': digest(receipt_path),
                'benchmark_sha256': digest(benchmark_path),
                'verified_review_count': len(reviews),
                'invalid_report_count': len(invalid_reports),
                'invalid_reports': invalid_reports,
                'RRR': None,
                'qualification': 'DA is final for this split; RRR requires the separate original-generator revision stage.',
            }
    output = ROOT / 'evidence/swe_review_complete_split_da.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {split: row['metrics'] for split, row in splits.items()}
                      for name, splits in result['reviewers'].items()}, ensure_ascii=False))


if __name__ == '__main__':
    main()
