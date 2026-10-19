#!/usr/bin/env python3
"""Reconcile Beam and Opus exact-image TB round scores with release I/O."""

import argparse
import copy
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
parser = argparse.ArgumentParser()
parser.add_argument('--model', choices=PROFILES)
parser.add_argument('--round', type=int, choices=(1, 2, 3), default=1)
args = parser.parse_args()
if args.round != 1 and not args.model:
    parser.error('--model is required when auditing rounds 2 or 3')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for model, config_dir in PROFILES.items():
    if args.model and model != args.model:
        continue
    config_path = SOURCE / config_dir / f'configs/r{args.round}.json'
    config = json.loads(config_path.read_text())
    expected = {Path(item['path']).name: item['path'] for item in config['tasks']}
    assert len(expected) == 89
    assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
    manifest_path = sorted(MANIFESTS.glob(f'{model}_exact_tb_live_*.json'))[-1]
    manifest = json.loads(manifest_path.read_text())
    archive_started = datetime.strptime(manifest['archive_name'].rsplit('_', 1)[-1].split('.')[0], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    archive = ROOT / '.release_assets' / manifest['archive_name']
    listing = subprocess.run(
        ['tar', '--use-compress-program=zstd', '-tf', str(archive)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    entries = set(listing.stdout.splitlines())
    errors = []
    expected_api_base = config['agents'][0]['kwargs']['api_base']
    if model == 'beam_bf16' and args.round in (2, 3):
        claim_path = SOURCE / f'beam/state/r{args.round}-launch.json'
        if claim_path.exists():
            claim = json.loads(claim_path.read_text())
            if claim.get('owner') == 'beam_exact_parallel_r23_2887.py':
                effective_path = Path(claim['effective_config'])
                handoff_path = SOURCE / 'beam/state/r23-2887-handoff.json'
                if not effective_path.exists() or not handoff_path.exists():
                    errors.append('Replica config or handoff receipt is missing')
                else:
                    effective = json.loads(effective_path.read_text())
                    normalized = copy.deepcopy(effective)
                    expected_api_base = effective['agents'][0]['kwargs']['api_base']
                    normalized['agents'][0]['kwargs']['api_base'] = config['agents'][0]['kwargs']['api_base']
                    if normalized != config:
                        errors.append('Replica config differs from the frozen round config beyond model endpoint')
                    if digest(config_path) != claim['source_config_sha256'] or digest(effective_path) != claim['effective_config_sha256']:
                        errors.append('Replica config hash differs from the launch receipt')
                    for receipt in (claim_path, handoff_path, effective_path):
                        if str(receipt.relative_to(BASE)) not in entries:
                            errors.append(f'Replica provenance missing from release archive: {receipt.name}')
    if manifest['archive_name'] not in verified_assets:
        errors.append('Latest archive is not SHA-256 and size verified on GitHub')
    if str(config_path.relative_to(BASE)) not in entries:
        errors.append(f'Original round-{args.round} job config missing from archive')
    missing_inputs = sorted(
        task for task, path in expected.items()
        if str((Path(path) / 'task.toml').relative_to(BASE)) not in entries
    )
    rows = {}
    ungraded = []
    unarchived_new_terminal = []
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
        if value['config']['task']['path'] != expected[task]:
            errors.append(f'terminal task path differs from the declared input: {task}')
        if model == 'beam_bf16' and value['config']['agent']['kwargs'].get('api_base') != expected_api_base:
            errors.append(f'terminal task used a different model endpoint: {task}')
        result_key = str(result.relative_to(BASE))
        if result_key not in entries and datetime.fromtimestamp(result.stat().st_mtime, timezone.utc) >= archive_started:
            unarchived_new_terminal.append(task)
            continue
        reward = ((value.get('verifier_result') or {}).get('rewards') or {}).get('reward')
        if reward not in (0, 1):
            ungraded.append(task)
        raw_files = sorted((trial / 'agent/raw_responses').glob('*.json'))
        if not raw_files:
            errors.append(f'terminal task has no original model responses: {task}')
        trial_key = str(trial.relative_to(BASE)) + '/'
        if result_key not in entries:
            errors.append(f'result missing from release archive: {task}')
        if not any(entry.startswith(trial_key + 'agent/raw_responses/') for entry in entries):
            errors.append(f'raw responses missing from release archive: {task}')
        missing_raw = [raw.name for raw in raw_files if str(raw.relative_to(BASE)) not in entries]
        if missing_raw:
            errors.append(f'{len(missing_raw)} original model responses missing from release archive: {task}')
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
        'round': args.round,
        'profile': 'exact user-supplied prebuilt TB2.1 images',
        'job_config_sha256': digest(config_path),
        'archive_name': manifest['archive_name'],
        'expected': 89,
        'terminal': len(rows),
        'graded': len(graded),
        'success': sum(row['reward'] == 1 for row in graded.values()),
        'missing_graded_tasks': sorted(set(expected) - set(graded)),
        'ungraded_terminal_tasks': sorted(ungraded),
        'unarchived_new_terminal_tasks': sorted(unarchived_new_terminal),
        'missing_task_inputs_in_archive': missing_inputs,
        'missing_scored_task_inputs_in_archive': missing_scored_inputs,
        'errors': errors,
        'qualification': 'complete_verified' if len(graded) == 89 and not errors and not ungraded else 'partial_or_needs_review',
        'accuracy': sum(row['reward'] == 1 for row in graded.values()) / 89 if len(graded) == 89 and not errors and not ungraded else None,
        'reasoning_note': 'Nonempty reasoning_content is counted in preserved raw responses; this does not certify absence of reward hacking.',
        'tasks': {task: rows[task] for task in sorted(rows)},
    }
    out = ROOT / 'evidence' / f'{model}_exact_round{args.round}_audit.json'
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('model', 'graded', 'success', 'qualification', 'errors')}))
