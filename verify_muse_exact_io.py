#!/usr/bin/env python3
"""Check released Muse exact-TB archives cover every scored input and output."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
MANIFESTS = ROOT / 'input_output/archive_manifests'
EVIDENCE = ROOT / 'evidence'
audit = json.loads((EVIDENCE / 'muse_nvfp4_exact_round1_audit.json').read_text())
names = [
    'muse_exact_tb.json',
    'muse_nvfp4_exact_tb_round1_inputs_20261019.json',
    sorted(MANIFESTS.glob('muse_nvfp4_exact_tb_live_*.json'))[-1].name,
]
manifests = [json.loads((MANIFESTS / name).read_text()) for name in names]
entries = set()
for manifest in manifests:
    archive = ROOT / '.release_assets' / manifest['archive_name']
    listed = subprocess.run(
        ['tar', '--use-compress-program=zstd', '-tf', str(archive)],
        capture_output=True, text=True, check=True, timeout=120,
    )
    entries.update(listed.stdout.splitlines())

task_inputs = set()
for shard in (1, 2, 3):
    config = json.loads((BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/configs/r1-shard{shard}.json').read_text())
    for item in config['tasks']:
        task_inputs.add(str((Path(item['path']) / 'task.toml').relative_to(BASE)))
assert len(task_inputs) == 89
missing_inputs = sorted(task_inputs - entries)
missing_results = []
missing_raw = []
missing_trajectories = []
for task, row in audit['tasks'].items():
    result = row['result_path']
    if result not in entries:
        missing_results.append(task)
    trial_prefix = result.removesuffix('result.json')
    if not any(path.startswith(trial_prefix + 'agent/raw_responses/') for path in entries):
        missing_raw.append(task)
    if trial_prefix + 'agent/trajectory.json' not in entries:
        missing_trajectories.append(task)
required_handoff_files = []
if audit.get('replica_handoff'):
    required_handoff_files.append(str((BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867/r1-b06-b07-handoff.json').relative_to(BASE)))
    required_handoff_files.extend(str(Path(row['effective_config']).relative_to(BASE)) for row in audit['replica_handoff']['batches'])
missing_handoff_files = sorted(set(required_handoff_files) - entries)

remote_audit = json.loads((EVIDENCE / 'release-assets-verification.json').read_text())
verified_names = {item['asset'] for item in remote_audit['items'] if item.get('sha256_matches') and item.get('bytes_match')}
unverified = sorted(manifest['archive_name'] for manifest in manifests if manifest['archive_name'] not in verified_names)
errors = []
if missing_inputs:
    errors.append(f'{len(missing_inputs)} task input files missing')
if missing_results:
    errors.append(f'{len(missing_results)} scored result files missing')
if missing_raw:
    errors.append(f'{len(missing_raw)} scored raw-response sets missing')
if missing_trajectories:
    errors.append(f'{len(missing_trajectories)} scored trajectories missing')
if missing_handoff_files:
    errors.append(f'{len(missing_handoff_files)} replica handoff configs/receipt missing')
if unverified:
    errors.append(f'{len(unverified)} release assets not SHA/size verified')

record = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'archives': [manifest['archive_name'] for manifest in manifests],
    'expected_inputs': 89,
    'covered_inputs': 89 - len(missing_inputs),
    'audited_scored_tasks': len(audit['tasks']),
    'covered_results': len(audit['tasks']) - len(missing_results),
    'covered_raw_response_sets': len(audit['tasks']) - len(missing_raw),
    'covered_trajectories': len(audit['tasks']) - len(missing_trajectories),
    'missing_inputs': missing_inputs,
    'missing_results': missing_results,
    'missing_raw_responses': missing_raw,
    'missing_trajectories': missing_trajectories,
    'missing_handoff_files': missing_handoff_files,
    'unverified_assets': unverified,
    'errors': errors,
    'qualification': 'complete_verified' if not errors and audit['qualification'] == 'complete_verified' else 'partial_or_needs_review',
}
(EVIDENCE / 'muse_nvfp4_exact_io_coverage.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: record[key] for key in ('covered_inputs', 'covered_results', 'covered_raw_response_sets', 'covered_trajectories', 'errors', 'qualification')}))
