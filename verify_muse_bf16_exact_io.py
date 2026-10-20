#!/usr/bin/env python3
"""Reconcile BF16 exact-image TB round 1 with the verified release archives."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
BF = BASE / '.private/muse_bf16_20261018/legacy_bench'
MANIFESTS = ROOT / 'input_output/archive_manifests'
EVIDENCE = ROOT / 'evidence'


def load(path):
    return json.loads(path.read_text())


score = load(ROOT / 'results/scores.json')['models']['muse_bf16']['tb2_1_exact_supplied_images']['rounds']['1']
identity = load(EVIDENCE / 'muse_bf16_exact_image_identity.json')
config = load(BF / 'configs/tb-r1.json')
expected = {Path(row['path']).name for row in config['tasks']}
assert len(expected) == 89 and not identity['errors']

scored = {}
ungraded_native = {}
errors = []
raw_reasoning_by_task = {}
thinking_warnings = []
for result_path in (BF / 'tb-results/muse-bf16-tb-r1').glob('*/result.json'):
    row = load(result_path)
    if not row.get('finished_at'):
        continue
    task = Path(row['config']['task']['path']).name
    reward = ((row.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    if task not in expected or task in scored or task in ungraded_native:
        errors.append(f'unexpected or duplicate BF16 task: {task}')
        continue
    if reward not in (0, 1):
        exception = (row.get('exception_info') or {}).get('exception_type')
        ungraded_native[task] = {
            'result_path': str(result_path.relative_to(BASE)),
            'exception_type': exception,
            'raw_response_count': len(list((result_path.parent / 'agent/raw_responses').glob('*.json'))),
            'qualification': 'No native verifier reward; excluded from scored counts pending task-level audit.',
        }
        continue
    scored[task] = {'reward': reward, 'result_path': str(result_path.relative_to(BASE))}
    raw_files = sorted((result_path.parent / 'agent/raw_responses').glob('*.json'))
    with_reasoning = 0
    for raw_path in raw_files:
        raw = load(raw_path)
        if raw.get('model') != 'muse-spark-open-bf16':
            errors.append(f'BF16 raw response has an unexpected model name: {task}')
        if any(bool(choice.get('message', {}).get('reasoning_content')) for choice in raw.get('choices', [])):
            with_reasoning += 1
    raw_reasoning_by_task[task] = {'raw_responses': len(raw_files), 'nonempty_reasoning_content': with_reasoning}
    if with_reasoning != len(raw_files):
        thinking_warnings.append(task)
    if not raw_files:
        errors.append(f'BF16 scored task lacks native raw responses: {task}')
if (score['graded'], score['success']) != (len(scored), sum(row['reward'] == 1 for row in scored.values())):
    errors.append('BF16 published graded/success counts differ from native terminal results')

manifest_paths = [MANIFESTS / 'muse_bf16.json', *sorted(MANIFESTS.glob('muse_bf16_delta_*.json')),
                  MANIFESTS / 'muse_nvfp4_exact_tb_round1_inputs_20261019.json']
manifests = [load(path) for path in manifest_paths]
entries = set()
for manifest in manifests:
    archive = ROOT / '.release_assets' / manifest['archive_name']
    listed = subprocess.run(['tar', '--use-compress-program=zstd', '-tf', str(archive)],
                            capture_output=True, text=True, timeout=120, check=True)
    entries.update(listed.stdout.splitlines())

input_paths = {str((Path(row['path']) / 'task.toml').relative_to(BASE)) for row in config['tasks']}
missing_inputs = sorted(input_paths - entries)
missing_results = []
missing_raw = []
missing_trajectories = []
for task, row in scored.items():
    path = row['result_path']
    prefix = path.removesuffix('result.json')
    if path not in entries:
        missing_results.append(task)
    if not any(name.startswith(prefix + 'agent/raw_responses/') for name in entries):
        missing_raw.append(task)
    if prefix + 'agent/trajectory.json' not in entries:
        missing_trajectories.append(task)

release = load(EVIDENCE / 'release-assets-verification.json')
verified_names = {row['asset'] for row in release['items'] if row.get('sha256_matches') and row.get('bytes_match')}
unverified_assets = sorted(row['archive_name'] for row in manifests if row['archive_name'] not in verified_names)
for label, missing in [('task inputs', missing_inputs), ('scored results', missing_results),
                       ('raw-response sets', missing_raw), ('trajectories', missing_trajectories),
                       ('release assets', unverified_assets)]:
    if missing:
        errors.append(f'{len(missing)} {label} missing or unverified')
if score['graded'] == 89 and set(scored) != expected:
    errors.append('BF16 full round lacks all 89 unique task results')

audit = {'generated_utc': datetime.now(timezone.utc).isoformat(), 'expected_tasks': 89,
         'scored_tasks': len(scored), 'success_count': sum(row['reward'] == 1 for row in scored.values()),
         'tasks': scored,
         'ungraded_native_terminal_tasks': ungraded_native,
         'covered_inputs': 89 - len(missing_inputs), 'covered_results': len(scored) - len(missing_results),
         'covered_raw_response_sets': len(scored) - len(missing_raw),
         'covered_trajectories': len(scored) - len(missing_trajectories),
         'scored_raw_response_count': sum(row['raw_responses'] for row in raw_reasoning_by_task.values()),
         'nonempty_reasoning_response_count': sum(row['nonempty_reasoning_content'] for row in raw_reasoning_by_task.values()),
         'raw_reasoning_by_task': raw_reasoning_by_task, 'thinking_warnings': thinking_warnings,
         'archives': [row['archive_name'] for row in manifests],
         'missing_inputs': missing_inputs, 'missing_results': missing_results,
         'missing_raw_responses': missing_raw, 'missing_trajectories': missing_trajectories,
         'unverified_assets': unverified_assets, 'errors': errors,
         'qualification': 'complete_verified' if not errors and len(scored) == 89 else 'partial_or_needs_review'}
(EVIDENCE / 'muse_bf16_exact_io_coverage.json').write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps({key: audit[key] for key in ('scored_tasks', 'success_count', 'covered_inputs',
                                              'covered_results', 'covered_raw_response_sets',
                                              'covered_trajectories', 'scored_raw_response_count',
                                              'nonempty_reasoning_response_count', 'thinking_warnings', 'errors')}))
raise SystemExit(1 if errors else 0)
