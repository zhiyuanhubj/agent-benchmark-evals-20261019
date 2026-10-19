#!/usr/bin/env python3
"""Check live BF16 SWRBench generation-to-official-judge provenance."""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/review_bench')
OUT = SOURCE / 'swrbench'
EVIDENCE = ROOT / 'evidence/muse_bf16_swr_alignment.json'
EXPECTED = 1000


def read_jsonl(path):
    for attempt in range(3):
        data = path.read_bytes()
        complete = data if data.endswith(b'\n') else data[:data.rfind(b'\n') + 1]
        try:
            rows = [json.loads(line) for line in complete.splitlines() if line.strip()]
            return rows, hashlib.sha256(data).hexdigest(), len(data) != len(complete)
        except json.JSONDecodeError:
            if attempt == 2:
                raise
            time.sleep(0.2)


def indexed(rows, label, errors):
    by_id = {}
    for row in rows:
        instance_id = row.get('instance_id')
        if not isinstance(instance_id, str) or not instance_id:
            errors.append(f'{label}: missing instance_id')
            continue
        if instance_id in by_id:
            errors.append(f'{label}: duplicate {instance_id}')
        by_id[instance_id] = row
    return by_id


def main():
    binding = json.loads((SOURCE / 'judge-binding.json').read_text())
    official_source = SOURCE / 'vendor/swr_evaluation_struct.py'
    official_sha = hashlib.sha256(official_source.read_bytes()).hexdigest()
    errors = []
    if official_sha != binding['official_evaluator_sha256']:
        errors.append('Official judge source hash differs from pinned binding')
    if 'item[\'pred\'][\'review\'] = item[\'pred\'][\'review\'].replace("’", "\'")' not in official_source.read_text():
        errors.append('Pinned official judge no longer has the expected apostrophe normalization')

    # Read the judge first so a concurrent append cannot make its snapshot
    # appear newer than the generation snapshot used for the subset check.
    judged_rows, judged_sha, judged_partial_line = read_jsonl(OUT / 'evaluation-gpt-5.5.json.tmp.jsonl')
    generated_rows, generated_sha, generated_partial_line = read_jsonl(OUT / 'generation.jsonl')
    judged = indexed(judged_rows, 'judge', errors)
    generated = indexed(generated_rows, 'generation', errors)
    missing_generation = sorted(judged.keys() - generated.keys())
    if missing_generation:
        errors.append(f'{len(missing_generation)} judged IDs have no generated review')
    normalized_quotes = []
    mismatched_review = []
    for instance_id in judged.keys() & generated.keys():
        source_review = generated[instance_id].get('review')
        judged_review = judged[instance_id].get('review')
        if not isinstance(source_review, str) or not isinstance(judged_review, str):
            mismatched_review.append(instance_id)
        elif source_review == judged_review:
            continue
        elif source_review.replace('’', "'") == judged_review:
            normalized_quotes.append(instance_id)
        else:
            mismatched_review.append(instance_id)
    if mismatched_review:
        errors.append(f'{len(mismatched_review)} judged reviews differ after official normalization')
    if len(generated_rows) > EXPECTED or len(judged_rows) > EXPECTED:
        errors.append('SWRBench row count exceeds the 1000-task source')

    evidence = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'benchmark': 'SWRBench',
        'model': 'meta-models/Muse-Spark-Open-816B-A42B',
        'precision': 'BF16',
        'judge_model': binding['model'],
        'expected': EXPECTED,
        'generated': len(generated_rows),
        'judged': len(judged_rows),
        'unique_generated_ids': len(generated),
        'unique_judged_ids': len(judged),
        'judged_without_generation': missing_generation,
        'reviews_equal_after_official_normalization': len(judged.keys() & generated.keys()) - len(mismatched_review),
        'official_apostrophe_normalization_count': len(normalized_quotes),
        'review_mismatches': mismatched_review,
        'generated_jsonl_sha256': generated_sha,
        'judged_jsonl_sha256': judged_sha,
        'generated_trailing_partial_line_ignored': generated_partial_line,
        'judged_trailing_partial_line_ignored': judged_partial_line,
        'official_evaluator_sha256': official_sha,
        'errors': errors,
        'qualification': 'Live provenance and text-alignment check only; counts are progress, not final SWRBench accuracy.',
    }
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    temporary = EVIDENCE.with_name(EVIDENCE.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + '\n')
    temporary.replace(EVIDENCE)
    print(json.dumps({key: evidence[key] for key in ('generated_utc', 'generated', 'judged',
        'official_apostrophe_normalization_count', 'review_mismatches', 'errors')}))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
