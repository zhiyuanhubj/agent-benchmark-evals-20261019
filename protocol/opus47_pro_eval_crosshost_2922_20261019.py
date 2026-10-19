"""Retry only the saved Opus 4.7 Pro verification on a separate CPU host.

The model endpoint remains disabled. This run must reuse the original patch and
the original 3600-second evaluator limit; it cannot generate a new answer.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import recover_pro_eval_timeout as original

RUN_ID = 'opus47-pro-eval-recovery-element-hq-2922-20261019'
JOB_ID = '2922'
TMPDIR = '/tmp/zhiyuan-opus47-pro-eval-2922-20261019'
RECEIPT = original.REPO / 'evidence/opus47_pro_eval_crosshost_2922.json'
FIRST_RECEIPT = original.REPO / 'evidence/opus47_pro_eval_timeout_recovery.json'


def preflight():
    first = json.loads(FIRST_RECEIPT.read_text())
    assert first['status'] == 'needs_review'
    assert first['recovery_status'] == 'eval_error' and first['no_new_model_run']
    assert first['same_evaluation_timeout_seconds'] == 3600
    assert first['patch_sha256'] == original.sha(original.PATCH)
    first_result = next((original.TARGET / 'details').glob(f'{original.TASK}--*/attempt-1/result.json'))
    assert 'evaluate timed out after 3600 seconds' in json.loads(first_result.read_text())['error']
    original.RECOVERY_ID = RUN_ID
    original.TARGET = original.RESULTS / RUN_ID
    command, receipt = original.preflight()
    assert command[command.index('--model-base-url') + 1] == 'http://127.0.0.1:9/v1'
    assert command[command.index('--run-id') + 1] == RUN_ID
    return command, dict(receipt, evaluation_host_job=JOB_ID,
                         previous_recovery_result_sha256=first['recovery_result_sha256'],
                         reason='Repeat identical saved-patch verification on an independent CPU host')


def main():
    command, receipt = preflight()
    state = subprocess.check_output(['squeue', '-h', '-j', JOB_ID, '-o', '%T'], text=True).strip()
    assert state == 'RUNNING', f'CPU allocation {JOB_ID} is {state!r}'
    prefix = ['srun', f'--jobid={JOB_ID}', '--overlap', '--gres=none', '-N1', '-n1', '-c1', '--immediate=10']
    subprocess.run([*prefix, 'mkdir', '-p', TMPDIR], check=True)
    original.save(RECEIPT, dict(receipt, status='running', started_utc=datetime.now(timezone.utc).isoformat()))
    env = ['env', 'HF_HOME=/fsx/home/zhiyuan/bench/hf_home',
           'UV_CACHE_DIR=/fsx/home/zhiyuan/bench/uv_cache', f'TMPDIR={TMPDIR}']
    proc = subprocess.run(['srun', f'--jobid={JOB_ID}', '--overlap', '--gres=none', '-N1', '-n1', '-c16',
                           '--immediate=10', *env, *command], cwd='/fsx/home/zhiyuan/AgentCompass')
    output = dict(receipt, returncode=proc.returncode,
                  finished_utc=datetime.now(timezone.utc).isoformat())
    target = original.TARGET
    progress = target / 'progress.json'
    if progress.exists():
        output['progress'] = json.loads(progress.read_text())
    results = list((target / 'details').glob(f'{original.TASK}--*/attempt-1/result.json'))
    if len(results) == 1:
        recovered = json.loads(results[0].read_text())
        output['recovery_result_sha256'] = original.sha(results[0])
        output['recovery_status'] = recovered['status']
        output['recovery_correct'] = recovered.get('metrics', {}).get('correct')
        output['same_patch'] = recovered.get('final_answer') == original.PATCH.read_text()
    phases = []
    journal = target / 'progress.jsonl'
    if journal.exists():
        for line in journal.read_text().splitlines():
            row = json.loads(line)
            if row.get('task_id') == original.TASK and row.get('event') == 'phase_changed':
                phases.append(row.get('phase'))
    output['phases'] = phases
    output['no_new_model_run'] = ('recover_evaluation' in phases and
                                  not any(p in phases for p in ('start_harness', 'run_harness')))
    output['status'] = ('completed' if proc.returncode == 0 and output.get('recovery_status') == 'completed'
                        and output.get('same_patch') and output['no_new_model_run'] else 'needs_review')
    original.save(RECEIPT, output)
    assert output['status'] == 'completed', f'Cross-host recovery needs review: {RECEIPT}'


if __name__ == '__main__':
    main()
