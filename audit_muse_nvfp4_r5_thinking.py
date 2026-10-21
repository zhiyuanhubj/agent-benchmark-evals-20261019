#!/usr/bin/env python3
"""Audit thinking in the released Muse NVFP4 exact-image TB round-five snapshot."""

import hashlib
import json
import subprocess
import tarfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_DIR = ROOT / 'input_output/archive_manifests'
manifests = sorted(MANIFEST_DIR.glob('muse_nvfp4_exact_tb_live_*.json'))
assert manifests, 'No Muse exact-image TB live archive'
manifest_path = manifests[-1]
manifest = json.loads(manifest_path.read_text())
archive = ROOT / '.release_assets' / manifest['archive_name']
assert archive.stat().st_size == manifest['archive_size_bytes']
with archive.open('rb') as stream:
    assert hashlib.file_digest(stream, 'sha256').hexdigest() == manifest['archive_sha256']

released = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
matched = [row for row in released['items'] if row['manifest'] == str(manifest_path.relative_to(ROOT))]
assert len(matched) == 1 and matched[0]['sha256_matches'] and matched[0]['bytes_match'], (
    'Latest TB archive has not been verified against its GitHub Release asset'
)

score = json.loads((ROOT / 'results/scores.json').read_text())
round5 = score['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['5']
prefix = ('muse-nvfp4-tb-v1-exact-r5-2899-20261021/')
results = {}
raw = Counter()
empty_reasoning = Counter()
unreadable = []
unexpected_model = []

proc = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE)
try:
    with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
        for member in tar:
            if not member.isfile() or prefix not in member.name:
                continue
            rel = member.name.split(prefix, 1)[1]
            parts = rel.split('/')
            if len(parts) < 2:
                continue
            task = parts[0].split('__', 1)[0]
            if rel.endswith('/result.json') and len(parts) == 2:
                result = json.load(tar.extractfile(member))
                if result.get('finished_at'):
                    reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
                    results[task] = reward
            elif '/agent/raw_responses/' in rel and rel.endswith('.json'):
                try:
                    response = json.load(tar.extractfile(member))
                    message = response['choices'][0]['message']
                    reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
                    raw[task] += 1
                    if not isinstance(reasoning, str) or not reasoning.strip():
                        empty_reasoning[task] += 1
                    if response.get('model') != 'muse-spark-open-nvfp4':
                        unexpected_model.append(member.name)
                except (KeyError, ValueError, TypeError):
                    unreadable.append(member.name)
finally:
    proc.stdout.close()
    assert proc.wait() == 0, 'zstd failed while reading TB archive'

graded = {task: reward for task, reward in results.items() if reward in (0, 1)}
assert len(graded) >= round5['graded'], (len(graded), round5['graded'])
assert sum(reward == 1 for reward in graded.values()) >= round5['success']
assert all(raw[task] > 0 for task in graded), 'A graded task has no archived raw response'
assert not unreadable and not unexpected_model, (unreadable, unexpected_model)

audit = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'score_generated_utc': score['generated_utc'],
    'archive_manifest': str(manifest_path.relative_to(ROOT)),
    'archive_sha256': manifest['archive_sha256'],
    'github_release_sha256_and_size_match': True,
    'score_graded_tasks': round5['graded'],
    'score_successes': round5['success'],
    'graded_tasks_in_archive': len(graded),
    'successes_in_archive': sum(reward == 1 for reward in graded.values()),
    'archived_graded_task_raw_response_counts': {task: raw[task] for task in sorted(graded)},
    'archived_graded_nonempty_reasoning_response_count': sum(
        raw[task] - empty_reasoning[task] for task in graded),
    'archived_graded_empty_reasoning_response_count': sum(empty_reasoning[task] for task in graded),
    'empty_reasoning_tasks': sorted(task for task in graded if empty_reasoning[task]),
    'qualification': ('no_graded_trials_yet' if not graded else
                      'all_archived_graded_raw_responses_have_thinking' if not empty_reasoning else
                      'some_archived_graded_raw_responses_lack_thinking'),
    'limitation': ('This checks thinking preservation for archived graded trials, not correctness '
                   'or trajectory integrity. An archive may contain a new terminal trial captured '
                   'after the score snapshot.'),
}
target = ROOT / 'evidence/muse_nvfp4_r5_thinking_audit.json'
target.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: audit[key] for key in (
    'graded_tasks_in_archive', 'successes_in_archive',
    'archived_graded_nonempty_reasoning_response_count',
    'archived_graded_empty_reasoning_response_count')}, ensure_ascii=False))
