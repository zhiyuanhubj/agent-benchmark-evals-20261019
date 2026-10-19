#!/usr/bin/env python3
"""Reconcile Beam and Opus exact-image TB first-round scores with release I/O."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
MANIFESTS = ROOT / 'input_output/archive_manifests'
remote = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
verified_assets = {row['asset'] for row in remote['items'] if row.get('sha256_matches') and row.get('bytes_match')}
PROFILES = {'opus47': 'opus47', 'beam_bf16': 'beam'}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for model, config_dir in PROFILES.items():
    config_path = SOURCE / config_dir / 'configs/r1.json'
    config = json.loads(config_path.read_text())
    expected = {Path(item['path']).name: item['path'] for item in config['tasks']}
    assert len(expected) == 89
    assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
    manifest_path = sorted(MANIFESTS.glob(f'{model}_exact_tb_live_*.json'))[-1]
    manifest = json.loads(manifest_path.read_text())
    archive = ROOT / '.release_assets' / manifest['archive_name']
    listing = subprocess.run(
        ['tar', '--use-compress-program=zstd', '-tf', str(archive)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    entries = set(listing.stdout.splitlines())
    errors = []
    if manifest['archive_name'] not in verified_assets:
        errors.append('Latest archive is not SHA-256 and size verified on GitHub')
    if str(config_path.relative_to(BASE)) not in entries:
        errors.append('Original round-one job config missing from archive')
    missing_inputs = sorted(
        task for task, path in expected.items()
        if str((Path(path) / 'task.toml').relative_to(BASE)) not in entries
    )
    rows = {}
    ungraded = []
    job_dir = SOURCE / 'results' / model / config['job_name']
    for trial in sorted(job_dir.iterdir()):
        if not trial.is_dir():
            continue
        result = trial / 'result.json'
        if not result.exists():
            continue
        value = json.loads(result.read_text())
        if not value.get('finished_at'):
            continue
        task = Path(value['config']['task']['path']).name
        if task not in expected or task in rows:
            errors.append(f'unexpected or duplicate terminal task: {task}')
            continue
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        if reward not in (0, 1):
            ungraded.append(task)
        raw_files = sorted((trial / 'agent/raw_responses').glob('*.json'))
        if not raw_files:
            errors.append(f'terminal task has no original model responses: {task}')
        result_key = str(result.relative_to(BASE))
        trial_key = str(trial.relative_to(BASE)) + '/'
        if result_key not in entries:
            errors.append(f'result missing from release archive: {task}')
        if not any(entry.startswith(trial_key + 'agent/raw_responses/') for entry in entries):
            errors.append(f'raw responses missing from release archive: {task}')
        if trial_key + 'agent/trajectory.json' not in entries:
            errors.append(f'trajectory missing from release archive: {task}')
        reasoning_count = 0
        for raw in raw_files:
            try:
                response = json.loads(raw.read_text())
                if any((choice.get('message') or {}).get('reasoning_content') for choice in response.get('choices') or []):
                    reasoning_count += 1
            except (OSError, ValueError, TypeError) as exc:
                errors.append(f'invalid raw response for {task}: {raw.name}: {exc}')
        rows[task] = {
            'reward': reward,
            'result_sha256': digest(result),
            'result_path': result_key,
            'raw_response_count': len(raw_files),
            'responses_with_reasoning_content': reasoning_count,
        }
    graded = {task: row for task, row in rows.items() if row['reward'] in (0, 1)}
    missing_scored_inputs = sorted(set(missing_inputs) & set(graded))
    if missing_scored_inputs:
        errors.append(f'{len(missing_scored_inputs)} scored task descriptions missing from archive')
    record = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'model': model,
        'profile': 'exact user-supplied prebuilt TB2.1 images',
        'job_config_sha256': digest(config_path),
        'archive_name': manifest['archive_name'],
        'expected': 89,
        'terminal': len(rows),
        'graded': len(graded),
        'success': sum(row['reward'] == 1 for row in graded.values()),
        'missing_graded_tasks': sorted(set(expected) - set(graded)),
        'ungraded_terminal_tasks': sorted(ungraded),
        'missing_task_inputs_in_archive': missing_inputs,
        'missing_scored_task_inputs_in_archive': missing_scored_inputs,
        'errors': errors,
        'qualification': 'complete_verified' if len(graded) == 89 and not errors and not ungraded else 'partial_or_needs_review',
        'accuracy': sum(row['reward'] == 1 for row in graded.values()) / 89 if len(graded) == 89 and not errors and not ungraded else None,
        'reasoning_note': 'Nonempty reasoning_content is counted in preserved raw responses; this does not certify absence of reward hacking.',
        'tasks': {task: rows[task] for task in sorted(rows)},
    }
    out = ROOT / 'evidence' / f'{model}_exact_round1_audit.json'
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('model', 'graded', 'success', 'qualification', 'errors')}))
