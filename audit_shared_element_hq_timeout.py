#!/usr/bin/env python3
"""Anchor the same ungraded Pro verifier timeout in two original runs."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
TASK = 'instance_element-hq__element-web-459df4583e01e4744a52d45446e34183385442d6-vnan'
TASK_SHA256 = '5afc604afa86c4d178ea6aef9803cca24e1a948504110f5eefedcb8503117a8a'
TIMEOUT = 'agentcompass.runtime.timeouts.PhaseTimeoutError: evaluate timed out after 3600 seconds'
RUNS = {
    'beam_bf16': (
        BASE / '.private/beam_20261018/legacy_bench_20261018/pro-results',
        'beam-pro-r1-initial128',
        'a803e6921f0d0c6e6dd640b5fa762c639e2f0cebecf0045d1c8bcda60999b9de',
    ),
    'opus_4_7': (
        BASE / 'bench/opus47_full_20261018/pro-results',
        'opus47-pro-full-r1',
        '00e9d05845500c0637a36936a9eed43b1dcfe36c12a33308561bf5376678acaa',
    ),
}
ARCHIVES = {'beam_bf16': 'beam_legacy.tar.zst', 'opus_4_7': 'opus47_legacy.tar.zst'}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = {}
release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
verified_assets = {row['asset'] for row in release['items']
                   if row.get('sha256_matches') and row.get('bytes_match')}
for model, (run_root, run_id, expected_result_sha) in RUNS.items():
    matches = list(run_root.glob(f'*/*/{run_id}/details/{TASK}--*/attempt-1/result.json'))
    assert len(matches) == 1, (model, matches)
    result_path = matches[0]
    task_path = result_path.parent.parent / 'task.json'
    result = json.loads(result_path.read_text())
    task = json.loads(task_path.read_text())
    benchmark = (result.get('meta') or {}).get('benchmark') or {}
    native_grade = benchmark.get('eval_raw_data') or {}
    assert task['task_id'] == TASK
    assert sha256(task_path) == TASK_SHA256
    assert sha256(result_path) == expected_result_sha
    assert result['status'] == 'eval_error'
    assert TIMEOUT in (result.get('error') or '')
    assert native_grade.get('completed') is not True
    assert not isinstance((result.get('metrics') or {}).get('correct'), bool)
    archive_name = ARCHIVES[model]
    assert archive_name in verified_assets, f'Original I/O archive is not verified on GitHub: {model}'
    listing = subprocess.run(['tar', '--use-compress-program=zstd', '-tf',
                              str(ROOT / '.release_assets' / archive_name)],
                             capture_output=True, text=True, check=True, timeout=120)
    entries = set(listing.stdout.splitlines())
    assert str(task_path.relative_to(BASE)) in entries
    assert str(result_path.relative_to(BASE)) in entries
    rows[model] = {
        'scoring_run_id': run_id,
        'task_json': str(task_path.relative_to(BASE)),
        'task_json_sha256': TASK_SHA256,
        'original_result': str(result_path.relative_to(BASE)),
        'original_result_sha256': expected_result_sha,
        'native_status': result['status'],
        'native_evaluate_timeout_seconds': 3600,
        'native_grader_completed': False,
        'valid_binary_score': False,
        'verified_release_archive': archive_name,
        'task_and_result_in_verified_release': True,
    }

record = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'The original first-draw SWE-bench Pro Verified runs only',
    'task_id': TASK,
    'models': rows,
    'opus_saved_patch_verifier_only_recovery_evidence': [
        'evidence/opus47_pro_eval_timeout_recovery.json',
        'evidence/opus47_pro_eval_crosshost_2922.json',
    ],
    'qualification': (
        'Both original runs reached the same task and timed out in the native evaluate phase '
        'after 3600 seconds. This is evidence of a shared task-level scoring gap, not proof '
        'of the underlying cause or of either model succeeding or failing. Keep both original '
        'tasks ungraded. Saved-patch verifier-only retries remain separate and cannot add a '
        'model draw or success to the original round.'
    ),
}
out = ROOT / 'evidence/shared_element_hq_eval_timeout.json'
out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'evidence': str(out), 'task': TASK, 'models': sorted(rows)}, ensure_ascii=False))
