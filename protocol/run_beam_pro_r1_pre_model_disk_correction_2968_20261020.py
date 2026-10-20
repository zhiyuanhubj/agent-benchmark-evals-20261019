#!/usr/bin/env python3
"""Run one Beam Pro round-1 draw for audited pre-model disk failures on CPU 2968."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

BASE = Path('/fsx/home/zhiyuan')
REPO = BASE / 'agent-benchmark-evals-20261019'
SOURCE = BASE / '.private/beam_20261018/legacy_bench_20261018/remaining_pro/handoff_20261020/command.json'
AUDIT = REPO / 'evidence/beam_pro_r1_pre_model_disk_failures.json'
READY = BASE / '.private/beam_20261018/expanded_capacity_20261018/allocation-2888-rank-0/serving-conformance-ready.json'
STATE = BASE / '.private/beam_20261018/legacy_bench_20261018/remaining_pro/disk_correction_2968_20261020'
COMMAND = STATE / 'command.json'
CLAIM = STATE / 'claim.json'
EXIT = STATE / 'exit.json'
RUN_NAME = 'beam_pro_r1_pre_model_disk_correction_2968_20261020'
RUN_ID = 'beam-pro-r1-pre-model-disk-2968-20261020'
RESULTS = BASE / '.private/beam_20261018/legacy_bench_20261018/disk_correction_results'
ENDPOINT = 'http://10.1.108.251:31328/v1'
TMPDIR = '/opt/sagemaker/tmp/zhiyuan-beam-pro-r1-disk-2968'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_option(args, name, value):
    args[args.index(name) + 1] = value


def verify_preflight():
    audit = json.loads(AUDIT.read_text())
    original = json.loads(SOURCE.read_text())
    ready = json.loads(READY.read_text())
    assert audit['source_command_sha256'] == sha(SOURCE)
    assert audit['source_run_id'] == 'beam-pro-r1-handoff-unattempted'
    assert audit['pre_model_disk_failure_count'] == len(audit['tasks']) >= 136
    assert ready['model'] == 'reflection/Beam-1.0-501B-A23B'
    assert ready['precision'] == 'BF16' and ready['api_base'] == ENDPOINT
    assert ready['full_retry_conformance'] == '133/133'
    source_ids = json.loads(original[original.index('--benchmark-params') + 1])['sample_ids']
    selected = sorted(row['task'] for row in audit['tasks'])
    assert len(selected) == len(set(selected)) and set(selected) <= set(source_ids)
    for row in audit['tasks']:
        for key, digest_key in (('result', 'result_sha256'),
                                ('task_file', 'task_file_sha256'),
                                ('checkpoint', 'checkpoint_sha256')):
            assert sha(Path(row[key])) == row[digest_key]
    job = subprocess.check_output(['squeue', '-h', '-j', '2968', '-o', '%T|%N'], text=True).strip()
    assert job == 'RUNNING|ip-10-1-100-204', f'CPU allocation 2968 changed: {job}'
    with urlopen(ENDPOINT.removesuffix('/v1') + '/health', timeout=8) as response:
        assert response.status == 200
    with urlopen(ENDPOINT + '/models', timeout=8) as response:
        models = json.loads(response.read())['data']
    assert any(model['id'] == 'Beam-1.0-501B-A23B' for model in models)
    target = RESULTS / RUN_NAME / 'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent' / RUN_ID
    assert not target.exists(), f'Duplicate correction run exists: {target}'
    command = list(original)
    changes = {
        '--results-dir': str(RESULTS), '--run-name': RUN_NAME, '--run-id': RUN_ID,
        '--task-concurrency': '4', '--benchmark-params': json.dumps({'sample_ids': selected}, separators=(',', ':')),
        '--model-base-url': ENDPOINT,
    }
    for key, value in changes.items():
        set_option(command, key, value)
    restored = list(command)
    for key in changes:
        set_option(restored, key, original[original.index(key) + 1])
    assert restored == original, 'Generation, harness, verifier or task protocol changed'
    return command, {
        'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Separate first actual Beam BF16 Pro round-1 model draw for tasks whose original handoff failed before any answer due to CPU disk full.',
        'source_run_id': audit['source_run_id'], 'source_command': str(SOURCE),
        'source_command_sha256': sha(SOURCE), 'pre_model_audit': str(AUDIT),
        'pre_model_audit_sha256': sha(AUDIT), 'model_ready': str(READY),
        'model_ready_sha256': sha(READY), 'cpu_allocation': 2968,
        'model_allocation': 2888, 'endpoint': ENDPOINT, 'task_count': len(selected),
        'run_name': RUN_NAME, 'run_id': RUN_ID, 'result_root': str(RESULTS),
        'same_sampling_harness_verifier_and_task_protocol': True,
        'infrastructure_only_changes': ['dedicated CPU allocation', 'verified equivalent Beam BF16 endpoint',
                                        'disjoint correction result root', 'task concurrency 6 to 4'],
        'original_results_preserved': True, 'no_best_of_selection': True,
        'scoring_policy': 'Keep correction separate until task-level reconciliation proves exactly one valid model draw per source task.',
    }


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def prepare():
    assert not COMMAND.exists() and not CLAIM.exists()
    command, claim = verify_preflight()
    save(COMMAND, command)
    claim['command'] = str(COMMAND)
    claim['command_sha256'] = sha(COMMAND)
    save(CLAIM, claim)
    print(json.dumps({'claim': str(CLAIM), 'task_count': claim['task_count'],
                      'command_sha256': claim['command_sha256']}))


def run():
    claim = json.loads(CLAIM.read_text())
    assert claim['command_sha256'] == sha(COMMAND)
    assert claim['pre_model_audit_sha256'] == sha(AUDIT)
    assert claim['model_ready_sha256'] == sha(READY)
    assert not EXIT.exists()
    subprocess.run(['srun', '--jobid=2968', '--overlap', '--gres=none', '-N1', '-n1', '-c1',
                    '--immediate=10', 'mkdir', '-p', TMPDIR], check=True)
    command = json.loads(COMMAND.read_text())
    env = ['env', 'OPENAI_API_KEY=EMPTY', 'MIX_SERVER_IP=10.1.108.251',
           'HF_HOME=/fsx/home/zhiyuan/bench/hf_home',
           'UV_CACHE_DIR=/fsx/home/zhiyuan/bench/uv_cache', f'TMPDIR={TMPDIR}']
    process = subprocess.run(['srun', '--jobid=2968', '--overlap', '--gres=none',
                              '-N1', '-n1', '-c24', '--immediate=10', *env, *command],
                             cwd=BASE / 'AgentCompass')
    save(EXIT, {'utc': datetime.now(timezone.utc).isoformat(), 'run_id': RUN_ID,
                'cpu_allocation': 2968, 'returncode': process.returncode})
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in ('prepare', 'run'):
        raise SystemExit('usage: script.py prepare|run')
    {'prepare': prepare, 'run': run}[sys.argv[1]]()
