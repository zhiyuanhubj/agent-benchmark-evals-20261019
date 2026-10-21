#!/usr/bin/env python3
"""Audit the one-draw Beam TB2.1 round-three setup-failure replacement."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
CLAIM = SOURCE / 'beam/state/r3-setup-replacement-20261021-claim.json'
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'evidence/beam_r3_setup_recovery_20261021.json'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


claim = read(CLAIM)
assert claim['round'] == 3 and claim['maximum_replacements_per_task'] == 1
assert len(claim['originals']) == 11
assert sha(Path(claim['original_config'])) == claim['original_config_sha256']
assert sha(Path(claim['replacement_config'])) == claim['replacement_config_sha256']
assert sha(SOURCE / 'allocation-2919/images-ready.json') == claim['image_ready_sha256']
originals = {}
for name, proof in claim['originals'].items():
    path = Path(proof['result_path'])
    assert sha(path) == proof['result_sha256']
    result = read(path)
    assert result.get('finished_at') and result.get('verifier_result') is None
    assert not list((path.parent / 'agent/raw_responses').glob('*.json'))
    assert Path(result['config']['task']['path']).name == name
    assert sha(Path(result['config']['task']['path']) / 'task.toml') == proof['task_toml_sha256']
    originals[name] = {'result_sha256': proof['result_sha256'],
                       'exception_type': proof['exception_type'],
                       'original_raw_response_count': 0}
replacements = {}
raw_count = 0
nonempty_reasoning = 0
empty_reasoning = 0
job = SOURCE / 'results/beam_bf16' / claim['replacement_job']
trial_dirs = [p for p in job.iterdir() if p.is_dir()] if job.exists() else []
for trial in trial_dirs:
    raw_paths = sorted((trial / 'agent/raw_responses').glob('*.json'))
    raw_count += len(raw_paths)
    for path in raw_paths:
        response = read(path)
        assert response.get('model') == 'Beam-1.0-501B-A23B'
        message = response.get('choices', [{}])[0].get('message') or {}
        reasoning = message.get('reasoning_content')
        if isinstance(reasoning, str) and reasoning.strip():
            nonempty_reasoning += 1
        else:
            empty_reasoning += 1
    result_path = trial / 'result.json'
    if not result_path.exists():
        continue
    result = read(result_path)
    if not result.get('finished_at'):
        continue
    name = Path(result['config']['task']['path']).name
    assert name in originals and name not in replacements
    reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    assert reward is None or reward in (0, 1)
    replacements[name] = {'reward': reward, 'result_sha256': sha(result_path),
                          'result_path': str(result_path),
                          'exception_type': (result.get('exception_info') or {}).get('exception_type'),
                          'raw_response_count': len(raw_paths)}
graded = sum(row['reward'] in (0, 1) for row in replacements.values())
success = sum(row['reward'] == 1 for row in replacements.values())
receipt = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'claim': str(CLAIM), 'claim_sha256': sha(CLAIM),
    'scoring_source_sha256': sha(SOURCE / 'status.py'),
    'round': 3, 'precision': 'BF16', 'expected_original_setup_failures': 11,
    'originals': originals, 'replacement_job': claim['replacement_job'],
    'replacement_trial_directories': len(trial_dirs),
    'replacement_terminal': len(replacements), 'replacement_graded': graded,
    'replacement_success': success, 'replacements': replacements,
    'replacement_raw_responses': raw_count,
    'nonempty_reasoning_responses': nonempty_reasoning,
    'empty_or_missing_reasoning_responses': empty_reasoning,
    'score_policy': claim['score_policy'],
    'qualification': 'Original ungraded attempts remain immutable and separate. At most one declared replacement draw per setup failure; no best-of selection.',
}
temp = OUTPUT.with_suffix('.json.tmp')
temp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
temp.replace(OUTPUT)
print(json.dumps({k: receipt[k] for k in ('generated_utc', 'replacement_terminal',
                                         'replacement_graded', 'replacement_success',
                                         'replacement_raw_responses')}))
