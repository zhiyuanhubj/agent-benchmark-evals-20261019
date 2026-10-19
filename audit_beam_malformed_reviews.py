#!/usr/bin/env python3
"""Identify sampled Beam reviews whose final report is invalid JSON."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PRIVATE = Path('/fsx/home/zhiyuan/.private/beam_20261018/review_bench')
PLAN = PRIVATE / 'revision/task-preparation-plan-v2.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    plan = json.loads(PLAN.read_text())
    for path, expected in plan['source_files_sha256'].items():
        assert sha(path) == expected, path
    rows = {}
    for split, spec in plan['splits'].items():
        bad = []
        seen = set()
        for path in (PRIVATE / 'queue/results' / split).glob('*/*/result.json'):
            result = json.loads(path.read_text())
            if not result.get('finished_at'):
                continue
            name = result['task_name']
            assert name in spec['expected_ids'] and name not in seen
            seen.add(name)
            trial = path.parent
            report = trial / 'verifier/review_report.json'
            if not report.exists():
                continue
            try:
                json.loads(report.read_text())
            except json.JSONDecodeError as error:
                completions = sorted((trial / 'agent/completions').glob('*.json'))
                assert completions, 'Malformed report without a sampled model response: ' + name
                bad.append({
                    'task': name, 'trial': str(trial), 'parse_error': str(error),
                    'result_sha256': sha(path), 'invalid_report_sha256': sha(report),
                    'raw_model_response_count': len(completions),
                    'raw_model_responses_sha256': hashlib.sha256(''.join(
                        str(p) + ':' + sha(p) + '\n' for p in completions).encode()).hexdigest(),
                    'verifier_report_exists': (trial / 'verifier/report.json').exists(),
                    'verifier_reward_exists': (trial / 'verifier/reward.txt').exists(),
                    'selection_policy': 'decision=None; no resampling; raw report bytes preserved',
                })
        rows[split] = {'terminal_results_seen': len(seen), 'invalid_report_count': len(bad),
                       'invalid_reports': sorted(bad, key=lambda row: row['task'])}
    evidence = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'plan_sha256': sha(PLAN),
        'selector_sha256': sha(PRIVATE / 'canonical_reviews_v2.py'),
        'preparation_controller_sha256': sha(PRIVATE / 'prepare_revision_after_reviews_v2.py'),
        'official_generator_sha256': sha(Path(plan['official_repo']) / 'scripts/data_pipeline/generate_review_tasks.py'),
        'splits': rows,
        'qualification': 'These are actual sampled terminal tasks. The official revision generator skips invalid JSON reports. The v2 selector records their original file hashes and treats them as missing decisions without parsing a leading JSON fragment or running another model attempt.',
    }
    dest = ROOT / 'evidence/beam_swe_review_malformed_reports.json'
    dest.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({name: row['invalid_report_count'] for name, row in rows.items()}))


if __name__ == '__main__':
    main()
