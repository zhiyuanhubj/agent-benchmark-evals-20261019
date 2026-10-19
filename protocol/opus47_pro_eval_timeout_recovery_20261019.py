"""Re-evaluate one saved Opus 4.7 Pro patch after its verifier timed out.

The recovery uses AgentCompass's fresh-evaluation checkpoint.  The model URL is
deliberately disabled, so a failed checkpoint cannot silently draw a new patch.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from agentcompass.runtime.checkpoint import read_checkpoint

ROOT = Path(__file__).resolve().parent
REPO = Path('/fsx/home/zhiyuan/agent-benchmark-evals-20261019')
TASK = 'instance_element-hq__element-web-459df4583e01e4744a52d45446e34183385442d6-vnan'
SOURCE_ID = 'opus47-pro-full-r1'
RECOVERY_ID = 'opus47-pro-eval-recovery-element-hq-20261019'
RESULTS = ROOT / 'pro-results/opus47_full/claude-opus-4-7_swebench_pro_verified_mini_swe_agent'
SOURCE = RESULTS / SOURCE_ID
TARGET = RESULTS / RECOVERY_ID
DETAIL = next((SOURCE / 'details').glob(f'{TASK}--*'))
SOURCE_RESULT = DETAIL / 'attempt-1/result.json'
CHECKPOINT = DETAIL / 'attempt-1/checkpoint.json'
PATCH = DETAIL / 'attempt-1/artifacts/app/patch.txt'
RECEIPT = REPO / 'evidence/opus47_pro_eval_timeout_recovery.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(tmp, path)


def replace_option(command, name, value):
    i = command.index(name)
    command[i + 1] = value


def preflight():
    result = json.loads(SOURCE_RESULT.read_text())
    checkpoint = json.loads(CHECKPOINT.read_text())['evaluation']
    read_checkpoint(CHECKPOINT)  # Validates the artifact fingerprint, not raw-file SHA-256.
    command = json.loads((ROOT / 'pro-command.json').read_text())
    source_args = command[command.index('--execution-params') + 1]
    assert json.loads(source_args)['evaluation_timeout_seconds'] == 3600
    assert result['status'] == 'eval_error'
    assert 'evaluate timed out after 3600 seconds' in result['error']
    assert checkpoint['task_id'] == TASK and checkpoint['attempt'] == 1
    assert checkpoint['source_run_id'] == SOURCE_ID
    assert checkpoint['source_evaluation_mode'] == 'fresh' and checkpoint['run_completed'] is True
    assert checkpoint['artifacts']['complete'] is True
    patch = PATCH.read_text()
    assert patch and patch == result['final_answer']
    assert any(e.get('source') == '/app/patch.txt' and e.get('status') == 'collected'
               for e in checkpoint['artifacts']['entries'])
    assert command[command.index('--run-id') + 1] == SOURCE_ID
    assert command[command.index('--k') + 1] == '1'
    assert command[command.index('--attempt-strategy') + 1] == 'pass'
    assert '--reuse' not in command and '--no-checkpoint-resume' not in command
    assert command[command.index('--model-base-url') + 1].startswith('http://10.')
    command = list(command)
    replace_option(command, '--run-id', RECOVERY_ID)
    replace_option(command, '--benchmark-params', json.dumps({'sample_ids': [TASK]}))
    replace_option(command, '--task-concurrency', '1')
    replace_option(command, '--model-base-url', 'http://127.0.0.1:9/v1')
    command.extend(['--reuse', SOURCE_ID])
    assert not TARGET.exists(), f'Recovery run already exists: {TARGET}'
    return command, {'task': TASK, 'source_run_id': SOURCE_ID, 'recovery_run_id': RECOVERY_ID,
                     'source_result_sha256': sha(SOURCE_RESULT), 'checkpoint_sha256': sha(CHECKPOINT),
                     'patch_sha256': sha(PATCH), 'same_evaluation_timeout_seconds': 3600,
                     'model_endpoint_disabled': True}


def wait_for_source():
    exit_file = ROOT / 'state/pro-controller-exit.json'
    while not exit_file.exists():
        status = subprocess.run(['systemctl', '--user', 'is-active', 'opus47-pro-full-20261018.service'],
                                capture_output=True, text=True)
        if status.stdout.strip() != 'active':
            raise RuntimeError('Original Pro controller stopped without exit receipt; inspect before recovery')
        time.sleep(60)
    outcome = json.loads(exit_file.read_text())
    assert outcome['returncode'] == 0, f'Original Pro controller exited abnormally: {outcome}'


def execute(command, receipt):
    state = subprocess.run(['squeue', '-h', '-j', '2867', '-o', '%T'], capture_output=True, text=True)
    assert state.stdout.strip() == 'RUNNING', 'CPU host allocation 2867 is unavailable'
    save(RECEIPT, dict(receipt, status='running', started_utc=datetime.now(timezone.utc).isoformat()))
    env_command = ['env', 'HF_HOME=/fsx/home/zhiyuan/bench/hf_home',
                   'UV_CACHE_DIR=/fsx/home/zhiyuan/bench/uv_cache',
                   'TMPDIR=/opt/dlami/nvme/zhiyuan-opus47-pro-20261018']
    proc = subprocess.run(['srun', '--jobid=2867', '--overlap', '--gres=none', '-N1', '-n1', '-c16',
                           '--immediate=10', *env_command, *command], cwd='/fsx/home/zhiyuan/AgentCompass')
    output = dict(receipt, returncode=proc.returncode, finished_utc=datetime.now(timezone.utc).isoformat())
    progress = TARGET / 'progress.json'
    if progress.exists():
        output['progress'] = json.loads(progress.read_text())
    result_paths = list((TARGET / 'details').glob(f'{TASK}--*/attempt-1/result.json'))
    if len(result_paths) == 1:
        recovered = json.loads(result_paths[0].read_text())
        output['recovery_result_sha256'] = sha(result_paths[0])
        output['recovery_status'] = recovered['status']
        output['recovery_correct'] = recovered.get('metrics', {}).get('correct')
        output['same_patch'] = recovered['final_answer'] == PATCH.read_text()
    phases = []
    journal = TARGET / 'progress.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            row = json.loads(line)
            if row.get('task_id') == TASK and row.get('event') == 'phase_changed':
                phases.append(row.get('phase'))
    output['phases'] = phases
    output['no_new_model_run'] = 'recover_evaluation' in phases and not any(
        x in phases for x in ('start_harness', 'run_harness'))
    output['status'] = ('completed' if proc.returncode == 0 and output.get('recovery_status') == 'completed'
                        and output.get('same_patch')
                        and output['no_new_model_run'] else 'needs_review')
    save(RECEIPT, output)
    assert output['status'] == 'completed', f'Recovery needs review: {RECEIPT}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wait', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    command, receipt = preflight()
    if args.dry_run:
        print(json.dumps(receipt, indent=2))
        return
    if args.wait:
        wait_for_source()
        refreshed_command, refreshed_receipt = preflight()
        assert (refreshed_command, refreshed_receipt) == (command, receipt), 'Source checkpoint changed while waiting'
    else:
        assert (ROOT / 'state/pro-controller-exit.json').exists(), 'Original run still active'
    execute(command, receipt)


if __name__ == '__main__':
    main()
