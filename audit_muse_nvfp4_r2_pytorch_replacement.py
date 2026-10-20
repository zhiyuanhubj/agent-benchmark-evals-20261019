#!/usr/bin/env python3
"""Anchor the single native storage replacement and screen its visible commands."""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CLAIM = ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_claim.json'
TARGET = ROOT / 'evidence/muse_nvfp4_r2_pytorch_model_cli_replacement_integrity.json'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


claim = read(CLAIM)
job = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4') / claim['replacement_job_name']
trials = [path for path in job.glob('pytorch-model-cli__*') if path.is_dir()]
assert len(trials) == 1, 'Expected exactly one declared storage replacement draw'
trial = trials[0]
result_path = trial / 'result.json'
trajectory_path = trial / 'agent/trajectory.json'
assert result_path.is_file() and trajectory_path.is_file()
result = read(result_path)
assert result.get('finished_at') and result.get('exception_info') is None
assert ((result.get('verifier_result') or {}).get('rewards') or {}).get('reward') == 1
assert Path(result['config']['task']['path']).name == 'pytorch-model-cli'
assert result['config']['agent']['kwargs']['api_base'] == claim['model_endpoint']
raw = sorted((trial / 'agent/raw_responses').glob('*.json'))
assert raw
thinking = sum(bool(((read(path).get('choices') or [{}])[0].get('message') or {}).get('reasoning_content')) for path in raw)
assert thinking == len(raw), 'A raw response is missing thinking'
steps = read(trajectory_path)['steps']
commands = [(step['step_id'], call['arguments'].get('keystrokes', ''))
            for step in steps for call in step.get('tool_calls', [])
            if call.get('function_name') == 'bash_command']
markers = re.compile(r'verifier|reward|grading|/tests(?:/|\b)|/solution(?:/|\b)|/oracle(?:/|\b)|test[_-]?cases|harbor', re.I)
hits = [{'step_id': step_id, 'marker': match.group(0)}
        for step_id, command in commands for match in markers.finditer(command)]
assert not hits, 'Potential verifier/test access needs manual review'
TARGET.write_text(json.dumps({
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'task': 'pytorch-model-cli',
    'original_reward': None,
    'replacement_native_reward': 1,
    'claim': str(CLAIM.relative_to(ROOT)),
    'claim_sha256': sha(CLAIM),
    'result_sha256': sha(result_path),
    'trajectory_sha256': sha(trajectory_path),
    'raw_response_count': len(raw),
    'raw_responses_with_nonempty_reasoning': thinking,
    'trajectory_steps': len(steps),
    'bash_command_count': len(commands),
    'suspicious_command_marker_hits': hits,
    'qualification': 'Single declared native replacement succeeded. All archived raw replies contain thinking; no visible command references verifier, grader, hidden tests, or reward. This limited screen is not a complete reward-hacking clearance.',
}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'reward': 1, 'raw': len(raw), 'thinking': thinking, 'commands': len(commands), 'marker_hits': len(hits)}))
