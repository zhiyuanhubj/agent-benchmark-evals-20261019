#!/usr/bin/env python3
"""Verify Muse's sealed review receipts and task-generation-only adapters."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018')
V2 = PRIVATE / 'revision/task-preparation-plan-v2.json'
ORIGINAL = PRIVATE / 'revision/task-preparation-plan.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    plan = json.loads(V2.read_text())
    assert plan['supersedes_plan_sha256'] == sha(ORIGINAL)
    for path, expected in plan['source_files_sha256'].items():
        assert sha(path) == expected, path
    official_da = json.loads((ROOT / 'evidence/swe_review_complete_split_da.json').read_text())
    splits = {}
    for split, spec in plan['splits'].items():
        receipt_path = PRIVATE / 'revision/prepared' / split / 'receipt.json'
        receipt = json.loads(receipt_path.read_text())
        assert set(receipt['reviews']) == set(spec['expected_ids'])
        assert receipt['prepared_tasks'] == len(receipt['expected_rejected']) == len(receipt['generator_task_ids'])
        assert receipt['included_in_model_metrics'] is False
        expected_plan = plan['supersedes_plan_sha256'] if split == 'qwen3_30b_instruct2507_500' else sha(V2)
        assert receipt['plan_sha256'] == expected_plan
        if split == 'qwen3_30b_instruct2507_500':
            assert sha(receipt_path) == plan['legacy_instruct_receipt_sha256']
        for path, expected in receipt['prepared_files_sha256'].items():
            assert sha(path) == expected, path
        generated = {path.name for path in (receipt_path.parent / 'tasks').iterdir() if path.is_dir()}
        assert generated == set(receipt['generator_task_ids'])
        native = {name: row for name, row in receipt['reviews'].items()
                  if row.get('native_verifier_complete_without_harbor_summary')}
        adapters = receipt.get('input_adapters_sha256', {})
        assert len(adapters) == len(native) * 3
        assert receipt.get('task_generation_adapter_count', 0) == len(native)
        adapter_rows = []
        for name, row in sorted(native.items()):
            trial = Path(row['trial'])
            assert not (trial / 'result.json').exists()
            adapter = receipt_path.parent / 'review-input' / trial.name
            marker = adapter / 'result.json'
            data = json.loads(marker.read_text())
            assert data['task_name'] == name and data['_task_generation_adapter_only'] is True
            assert data['_native_trial'] == str(trial)
            assert not {'finished_at', 'verifier_result', 'exception_info'} & set(data)
            assert data['_native_review_report_sha256'] == sha(trial / 'verifier/review_report.json')
            assert (adapter / 'config.json').resolve() == trial / 'config.json'
            assert (adapter / 'verifier/review_report.json').resolve() == trial / 'verifier/review_report.json'
            for path in (marker, adapter / 'config.json', adapter / 'verifier/review_report.json'):
                assert adapters[str(path)] == sha(path)
            adapter_rows.append({'task': name, 'original_trial': str(trial),
                                 'adapter_result_sha256': sha(marker),
                                 'native_review_report_sha256': data['_native_review_report_sha256'],
                                 'decision': row['decision']})
        final_da = official_da['reviewers']['muse-nvfp4'][split]
        assert final_da['status'] == 'final_da_for_this_split'
        assert final_da['canonical_receipt_sha256'] == sha(receipt_path)
        assert final_da['expected'] == spec['expected']
        splits[split] = {
            'expected_reviews': spec['expected'], 'prepared_revision_tasks': receipt['prepared_tasks'],
            'receipt_sha256': sha(receipt_path), 'plan_sha256': receipt['plan_sha256'],
            'native_adapter_count': len(native), 'native_adapters': adapter_rows,
            'official_DA': final_da['metrics']['DA'], 'RRR': None,
            'qualification': 'Task-generation adapters have no Harbor completion or reward fields and are excluded from model metrics.'
        }
    result = {'generated_utc': datetime.now(timezone.utc).isoformat(),
              'v2_plan_sha256': sha(V2), 'original_plan_sha256': sha(ORIGINAL),
              'official_da_evidence_sha256': sha(ROOT / 'evidence/swe_review_complete_split_da.json'),
              'splits': splits,
              'qualification': 'All three reviewer DA splits have sealed receipts; original-generator revision scoring and RRR remain separate.'}
    out = ROOT / 'evidence/muse_swe_review_revision_v2_receipts.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: {'tasks': row['prepared_revision_tasks'], 'adapters': row['native_adapter_count'],
                              'DA': row['official_DA']} for name, row in splits.items()}))


if __name__ == '__main__':
    main()
