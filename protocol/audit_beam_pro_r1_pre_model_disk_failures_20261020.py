#!/usr/bin/env python3
"""Identify Beam Pro round-1 trials that never sampled because CPU Docker disk filled."""

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/beam_20261018/legacy_bench_20261018/remaining_pro'
REPO = BASE / 'agent-benchmark-evals-20261019'
COMMAND = ROOT / 'handoff_20261020/command.json'
RESULTS = (ROOT / 'pro-results/beam_full_remaining603_handoff_20261020/'
           'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent/'
           'beam-pro-r1-handoff-unattempted/details')
OUTPUT = REPO / 'evidence/beam_pro_r1_pre_model_disk_failures.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    command = json.loads(COMMAND.read_text())
    assert command[command.index('--run-id') + 1] == 'beam-pro-r1-handoff-unattempted'
    declared = json.loads(command[command.index('--benchmark-params') + 1])['sample_ids']
    assert len(declared) == len(set(declared)) == 569
    eligible = []
    terminal_ids = set()
    categories = Counter()
    for path in sorted(RESULTS.glob('*/attempt-1/result.json')):
        result = json.loads(path.read_text())
        task_file = path.parent.parent / 'task.json'
        task = json.loads(task_file.read_text())['task_id']
        assert task in declared and task not in terminal_ids
        terminal_ids.add(task)
        error = (result.get('error') or '')
        if 'no space left on device' not in error.lower():
            continue
        checkpoint = path.parent / 'checkpoint.json'
        checkpoint_data = json.loads(checkpoint.read_text()) if checkpoint.exists() else None
        if not (result.get('status') == 'run_error_or_eval_error'
                and result.get('final_answer') is None
                and not result.get('trajectory')
                and not result.get('artifacts')
                and checkpoint_data == {'schema_version': 'agentcompass.attempt_checkpoint.v1'}):
            continue  # Model-sampled or evaluation-stage disk errors require separate handling.
        category = 'docker_pull_disk_full' if 'docker pull failed' in error.lower() else 'pre_model_environment_disk_full'
        categories[category] += 1
        eligible.append({'task': task, 'category': category,
                         'result': str(path), 'result_sha256': sha(path),
                         'task_file': str(task_file), 'task_file_sha256': sha(task_file),
                         'checkpoint': str(checkpoint), 'checkpoint_sha256': sha(checkpoint)})
    assert len(eligible) == len({x['task'] for x in eligible})
    assert categories['docker_pull_disk_full'] >= 130
    assert categories['pre_model_environment_disk_full'] >= 6
    document = {
        'audited_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Only Beam BF16 SWE-bench Pro Verified round-1 handoff terminal trials with disk-full failure before any model answer.',
        'source_command': str(COMMAND), 'source_command_sha256': sha(COMMAND),
        'source_run_id': 'beam-pro-r1-handoff-unattempted',
        'declared_source_tasks': len(declared), 'terminal_source_tasks': len(terminal_ids),
        'pre_model_disk_failure_count': len(eligible), 'categories': dict(categories),
        'no_model_response_evidence': 'Each selected native result has null final_answer, empty trajectory and artifacts, and only a schema-version checkpoint. Errors occurred in Docker pull or environment setup. Model-sampled and verifier-stage failures are excluded.',
        'score_policy': 'These are infrastructure non-samples, not incorrect model answers. Preserve original results. A separately identified first actual model draw may be scheduled for each task; do not use best-of selection.',
        'tasks': eligible,
    }
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'audited_utc': document['audited_utc'],
                      'terminal_source_tasks': len(terminal_ids),
                      'pre_model_disk_failure_count': len(eligible),
                      'categories': dict(categories)}))


if __name__ == '__main__':
    main()
