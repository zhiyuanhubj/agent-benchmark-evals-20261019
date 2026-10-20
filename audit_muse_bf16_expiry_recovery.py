#!/usr/bin/env python3
"""Publish provenance for the interrupted Muse BF16 run and its exact resume."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BF = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018')
RECOVERY = BF / 'recovery_20261020'
PRO = (BF / 'legacy_bench/pro-results/muse_bf16_full'
       / 'muse-spark-open-bf16_swebench_pro_verified_mini_swe_agent')


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


incident = read(RECOVERY / 'bridge-and-resume-claim.json')
pro_claim = read(RECOVERY / 'pro-resume-tmpfix-claim.json')
backups = read(RECOVERY / 'interrupted-original-dirs-manifest.json')
deployment = read(ROOT / 'evidence/muse_bf16_2886_deployment_audit.json')
original = read(PRO / pro_claim['source_run_id'] / 'progress.json')
resumed = read(PRO / pro_claim['derived_run_id'] / 'progress.json')
assert pro_claim['source_run_id'] == 'muse-bf16-pro-full-r1'
assert pro_claim['derived_run_id'] == 'muse-bf16-pro-full-r1-resume-20261020'
assert original['total_tasks'] == resumed['total_tasks'] == 731
assert original['finished_tasks'] == 147 and original['completed_tasks'] == 137
assert original['failed_tasks'] == 10 and resumed['reused_tasks'] == 137
assert incident['bridge_to_verified_2886_endpoint'] == deployment['endpoint']
assert deployment['revision'] == '0fb02478b02565b2ce7fc57e6051c91172774ac9'
assert sha(RECOVERY / 'interrupted-original-dirs-manifest.json') == incident['interrupted_native_trial_backup_manifest_sha256']

archive_rows = {}
for group in ('tb', 'deep'):
    row = backups['jobs'][group]
    path = Path(row['archive'])
    assert path.parent == RECOVERY and path.is_file()
    assert sha(path) == row['archive_sha256'] and path.stat().st_size == row['archive_bytes']
    assert row['job_name'] == incident['jobs'][group]['job_name']
    assert row['original_config_sha256'] == incident['jobs'][group]['original_config_sha256']
    archive_rows[group] = {
        'job_name': row['job_name'],
        'native_terminal_before_resume': incident['jobs'][group]['native_terminal_before_resume'],
        'interrupted_original_trial_names': incident['jobs'][group]['interrupted_trial_names'],
        'original_config_sha256': row['original_config_sha256'],
        'archive_name': path.name,
        'archive_sha256': row['archive_sha256'],
        'archive_bytes': row['archive_bytes'],
        'archive_members': row['archive_members'],
        'resultless_originals_are_ungraded': True,
    }

output = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'cause': backups['cause'],
    'old_allocation': 2865,
    'original_model_endpoint': incident['original_endpoint'],
    'bridge_to_verified_endpoint': deployment['endpoint'],
    'model_revision': deployment['revision'],
    'model_deployment_audit': 'evidence/muse_bf16_2886_deployment_audit.json',
    'original_completed_pro_tasks_reused_once': original['completed_tasks'],
    'original_pro_failed_tasks_not_reused': original['failed_tasks'],
    'original_pro_active_when_allocation_expired': len(original['active_tasks']),
    'pro_source_run_id': pro_claim['source_run_id'],
    'pro_scoring_run_id': pro_claim['derived_run_id'],
    'resumed_pro_current': {key: resumed[key] for key in
        ('status', 'finished_tasks', 'completed_tasks', 'failed_tasks', 'running_tasks', 'pending_tasks')},
    'resume_policy': 'Completed original results are reused once. Original failed and interrupted attempts remain preserved separately. Only native graded results in the derived run enter its live score; no correctness-selected reruns.',
    'interrupted_original_harbor_archives': archive_rows,
    'backup_manifest_sha256': incident['interrupted_native_trial_backup_manifest_sha256'],
    'bridge_preflight_sha256': incident['endpoint_provenance']['bridge_preflight_sha256'],
    'pro_resume_claim_sha256': sha(RECOVERY / 'pro-resume-tmpfix-claim.json'),
    'qualification': 'Infrastructure interruption; resultless original trials are not model failures. Native scores remain partial until their full benchmark denominators are graded.',
}
path = ROOT / 'evidence/muse_bf16_2865_expiry_recovery.json'
path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'generated_utc': output['generated_utc'],
                  'pro_reused': output['original_completed_pro_tasks_reused_once'],
                  'interrupted_harbor': {k: len(v['interrupted_original_trial_names']) for k, v in archive_rows.items()}}))
