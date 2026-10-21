#!/usr/bin/env python3
"""Audit the declared Beam TB2.1 round-two tmux-failure replacement."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
CLAIM = SOURCE / 'beam/state/r2-git-multibranch-infra-replacement-claim.json'
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'evidence/beam_r2_git_multibranch_recovery_20261021.json'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


claim = read(CLAIM)
assert claim['model'] == 'Beam-1.0-501B-A23B'
assert claim['precision'] == 'BF16' and claim['round'] == 2
assert claim['resamples_after_replacement'] == 0
assert sha(Path(claim['replacement_config'])) == claim['replacement_config_sha256']
config = read(Path(claim['replacement_config']))
assert config['job_name'] == claim['replacement_job_name']
assert len(config['tasks']) == 1
assert Path(config['tasks'][0]['path']).name == 'git-multibranch'
assert config['retry']['max_retries'] == 0 and config['n_attempts'] == 1
assert config['agents'][0]['kwargs']['api_base'] == claim['endpoint']

proof = claim['source_proof']
original_trial = Path(claim['source_trial'])
original_result = original_trial / 'result.json'
original_trajectory = original_trial / 'agent/trajectory.json'
assert sha(original_result) == proof['source_result_sha256']
assert sha(original_trajectory) == proof['source_trajectory_sha256']
assert sha(SOURCE / 'beam/configs/r2-2887.json') == proof['source_config_sha256']
assert sha(SOURCE / 'beam/configs/r2.json') == proof['frozen_config_sha256']
assert sha(SOURCE / 'allocation-2919/images-ready.json') == proof['image_ready_sha256']
original = read(original_result)
assert original.get('finished_at') and original.get('verifier_result') is None
assert (original.get('exception_info') or {}).get('exception_type') == 'RuntimeError'
assert Path(original['config']['task']['path']).name == 'git-multibranch'
raw_original = sorted((original_trial / 'agent/raw_responses').glob('*.json'))
assert len(raw_original) == len(proof['source_raw_response_sha256']) == 6
assert {path.name: sha(path) for path in raw_original} == proof['source_raw_response_sha256']
for number in (1, 2, 3):
    receipt = SOURCE / f'beam/state/r{number}-exit.json'
    assert sha(receipt) == claim['original_round_exit_sha256'][str(number)]
    assert read(receipt)['returncode'] == 0

job = SOURCE / 'results/beam_bf16' / claim['replacement_job_name']
trial_dirs = [path for path in job.iterdir() if path.is_dir()] if job.exists() else []
assert len(trial_dirs) <= 1, 'Only one declared replacement draw is allowed'
replacement_raw = 0
nonempty_reasoning = 0
terminal = 0
reward = None
result_sha256 = None
result_path = None
trajectory_sha256 = None
tool_call_count = 0
suspicious_tool_calls = []
screen = re.compile(r'(?i)(verifier|reward|grader|hidden|/tests|nsenter|docker\.sock|/proc/1/root|/host|agentcompass)')
for trial in trial_dirs:
    raw = sorted((trial / 'agent/raw_responses').glob('*.json'))
    replacement_raw += len(raw)
    for path in raw:
        response = read(path)
        assert response.get('model') == claim['model']
        message = response.get('choices', [{}])[0].get('message') or {}
        if isinstance(message.get('reasoning_content'), str) and message['reasoning_content'].strip():
            nonempty_reasoning += 1
    path = trial / 'result.json'
    trajectory = trial / 'agent/trajectory.json'
    if trajectory.exists():
        trajectory_sha256 = sha(trajectory)
        for step in read(trajectory).get('steps', []):
            for call in step.get('tool_calls') or []:
                tool_call_count += 1
                argument = json.dumps(call.get('arguments') or {}, ensure_ascii=False)
                match = screen.search(argument)
                if match:
                    suspicious_tool_calls.append({'step_id': step.get('step_id'),
                                                  'tool_call_id': call.get('tool_call_id'),
                                                  'matched_term': match.group(0)})
    if not path.exists():
        continue
    result = read(path)
    if not result.get('finished_at'):
        continue
    assert Path(result['config']['task']['path']).name == 'git-multibranch'
    terminal = 1
    reward = ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward')
    assert reward is None or reward in (0, 1)
    result_sha256 = sha(path)
    result_path = str(path)

receipt = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'claim': str(CLAIM), 'claim_sha256': sha(CLAIM),
    'controller_source_sha256': sha(ROOT / 'beam_r2_git_multibranch_infra_recovery.py'),
    'scoring_source_sha256': sha(SOURCE / 'status.py'),
    'round': 2, 'precision': 'BF16', 'original_task': 'git-multibranch',
    'original_ungraded_raw_responses': len(raw_original),
    'original_result_sha256': proof['source_result_sha256'],
    'replacement_job': claim['replacement_job_name'],
    'replacement_trial_directories': len(trial_dirs),
    'replacement_terminal': terminal, 'replacement_graded': int(reward in (0, 1)),
    'replacement_success': int(reward == 1), 'replacement_reward': reward,
    'replacement_result_path': result_path, 'replacement_result_sha256': result_sha256,
    'replacement_trajectory_sha256': trajectory_sha256,
    'replacement_raw_responses': replacement_raw,
    'replacement_nonempty_reasoning_responses': nonempty_reasoning,
    'replacement_empty_or_missing_reasoning_responses': replacement_raw - nonempty_reasoning,
    'replacement_tool_call_count': tool_call_count,
    'suspicious_tool_calls': suspicious_tool_calls,
    'integrity_screen_qualification': 'Limited tool-argument keyword review only; no full reward-hacking clearance.',
    'score_policy': claim['score_policy'],
    'qualification': 'Original six-response model draw remains ungraded after tmux loss. Exactly one separately labeled replacement draw may fill its missing grade; no best-of selection.',
}
temp = OUTPUT.with_suffix('.json.tmp')
temp.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + '\n')
temp.replace(OUTPUT)
print(json.dumps({key: receipt[key] for key in ('generated_utc', 'replacement_terminal',
                                              'replacement_graded', 'replacement_success',
                                              'replacement_raw_responses')}))
