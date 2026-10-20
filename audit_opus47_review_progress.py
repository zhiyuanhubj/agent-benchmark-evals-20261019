#!/usr/bin/env python3
"""Publish Opus 4.7 SWE-Review review-stage progress without inventing DA/RRR."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = Path('/fsx/home/zhiyuan/.private/opus47_review_20261020')
PLAN = json.loads((SOURCE / 'plan.json').read_text())
rows = {}
for split, item in PLAN['splits'].items():
    config = SOURCE / 'configs' / f'{split}.json'
    assert hashlib.sha256(config.read_bytes()).hexdigest() == item['frozen_config_sha256']
    job = SOURCE / 'swe_review' / split / 'results' / item['job_name']
    result_path = job / 'result.json'
    row = {
        'expected': item['expected'],
        'job_name': item['job_name'],
        'frozen_config_sha256': item['frozen_config_sha256'],
        'status': 'not_started',
        'DA': None,
        'RRR': None,
    }
    if result_path.exists():
        result = json.loads(result_path.read_text())
        counts = result['stats']
        completed = counts['n_completed_trials']
        errored = counts['n_errored_trials']
        running = counts['n_running_trials']
        pending = counts['n_pending_trials']
        cancelled = counts['n_cancelled_trials']
        assert 0 <= errored <= completed
        assert completed + running + pending + cancelled == item['expected']
        row.update(
            status='review_stage_complete_da_pending' if result['finished_at'] else 'review_stage_running',
            completed_trials=completed,
            errored_trials=errored,
            running_trials=running,
            pending_trials=pending,
            cancelled_trials=cancelled,
            started_at=result['started_at'],
            finished_at=result['finished_at'],
        )
    rows[split] = row

output = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'model': PLAN['model'],
    'precision': PLAN['precision'],
    'protocol': 'Official SWE-Review review phase, one attempt per task',
    'qualification': 'Review-stage progress is not a DA or RRR score. Native downstream scoring and original-revision generation are separate.',
    'splits': rows,
}
target = ROOT / 'evidence/opus47_swe_review_progress.json'
target.write_text(json.dumps(output, indent=2) + '\n')
print(target)
