#!/usr/bin/env python3
"""Give two idle, equivalent Beam replicas disjoint, never-started Pro R1 tasks."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler

BASE = Path('/fsx/home/zhiyuan')
REPO = BASE / 'agent-benchmark-evals-20261019'
BEAM = BASE / '.private/beam_20261018'
HANDOFF = BEAM / 'legacy_bench_20261018/remaining_pro/handoff_20261020'
SOURCE = HANDOFF / 'command.json'
SOURCE_AUDIT = HANDOFF / 'audit.json'
RESULTS = BEAM / 'legacy_bench_20261018/remaining_pro/pro-results'
EVIDENCE = REPO / 'evidence/beam_pro_r1_unstarted_20261020'
STATE = BEAM / 'legacy_bench_20261018/remaining_pro/handoff_unstarted_20261020'
CLAIM = EVIDENCE / 'claim.json'
DISK_AUDIT = REPO / 'evidence/beam_pro_r1_pre_model_disk_failures.json'
ORIGINAL_READY = BEAM / 'serve-launch.json'
MODEL_NAME = 'Beam-1.0-501B-A23B'
MODEL_SLUG = 'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent'
CPU_JOB = 2968
SPLITS = {
    '2733': {'endpoint': 'http://10.1.25.253:31328/v1', 'host': 'ip-10-1-25-253'},
    '2887': {'endpoint': 'http://10.1.69.108:31328/v1', 'host': 'ip-10-1-69-108',
             'ready': BEAM / 'expanded_capacity_20261018/allocation-2887-rank-0/serving-conformance-ready.json'},
}


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as out:
        json.dump(value, out, indent=2, ensure_ascii=False)
        out.write('\n')


def option(args, name):
    return args[args.index(name) + 1]


def set_option(args, name, value):
    args[args.index(name) + 1] = value


def run_name(node):
    return f'beam_full_remaining603_unstarted_{node}_20261020'


def run_id(node):
    return f'beam-pro-r1-unstarted-{node}-20261020'


def target(node):
    return RESULTS / run_name(node) / MODEL_SLUG / run_id(node)


def slurm_running(job, host):
    state = subprocess.check_output(['squeue', '-h', '-j', str(job), '-o', '%T|%N'], text=True).strip()
    assert state == f'RUNNING|{host}', (job, state)


def model_ready(node):
    model = load(ORIGINAL_READY)
    endpoint = SPLITS[node]['endpoint']
    if node == '2887':
        replica = load(SPLITS[node]['ready'])
        for key in ('model', 'revision', 'precision', 'image_digest'):
            assert replica[key] == model[key], (node, key)
        assert replica['api_base'] == endpoint
    assert model['model'] == 'reflection/Beam-1.0-501B-A23B' and model['precision'] == 'BF16'
    opener = build_opener(ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=8) as response:
        assert any(row['id'] == MODEL_NAME for row in json.load(response)['data'])


def original_handoff_root(args):
    return RESULTS / option(args, '--run-name') / MODEL_SLUG / option(args, '--run-id')


def prepare():
    assert not CLAIM.exists(), 'Tasks already frozen for this continuation'
    for node, info in SPLITS.items():
        slurm_running(int(node), info['host'])
        model_ready(node)
        assert not target(node).exists(), f'Continuation already started on {node}'
    slurm_running(CPU_JOB, 'ip-10-1-100-204')
    assert subprocess.check_output(['systemctl', '--user', 'show', '-p', 'MainPID',
                                    'beam-pro-r1-handoff-2919-20261020.service'],
                                   text=True).strip() == 'MainPID=0'

    original = load(SOURCE)
    source_audit = load(SOURCE_AUDIT)
    sample = json.loads(option(original, '--benchmark-params'))['sample_ids']
    assert len(sample) == len(set(sample)) == 569
    assert source_audit['pending_count'] == len(sample)
    assert not set(sample) & set(source_audit['terminal_ids'])
    assert option(original, '--model-base-url') == SPLITS['2733']['endpoint']
    assert option(original, '--task-concurrency') == '6'
    assert json.loads(option(original, '--harness-params'))['interleaved_thinking'] is True

    previous = original_handoff_root(original)
    task_files = list(previous.glob('details/*/task.json'))
    started = {load(path)['task_id'] for path in task_files}
    results = {load(path.parent.parent / 'task.json')['task_id']
               for path in previous.glob('details/*/attempt-1/result.json')}
    assert len(task_files) == len(started) == 297
    assert len(results) == 291 and results <= started <= set(sample)
    interrupted = sorted(started - results)
    selected = sorted(set(sample) - started)
    assert len(interrupted) == 6 and len(selected) == 272
    assert not set(selected) & set(source_audit['terminal_ids'])
    assert set(selected).isdisjoint(started)
    disk_tasks = {row['task'] for row in load(DISK_AUDIT)['tasks']}
    assert disk_tasks <= started and set(selected).isdisjoint(disk_tasks)

    commands = {}
    halves = {'2733': selected[:136], '2887': selected[136:]}
    assert set(halves['2733']).isdisjoint(halves['2887'])
    for node, tasks in halves.items():
        assert len(tasks) == 136
        command = list(original)
        changes = {'--run-name': run_name(node), '--run-id': run_id(node),
                   '--task-concurrency': '4',
                   '--benchmark-params': json.dumps({'sample_ids': tasks}, separators=(',', ':')),
                   '--model-base-url': SPLITS[node]['endpoint']}
        for key, value in changes.items():
            set_option(command, key, value)
        restored = list(command)
        for key in changes:
            set_option(restored, key, option(original, key))
        assert restored == original, 'Benchmark protocol drift'
        commands[node] = command

    for node, command in commands.items():
        save_new(EVIDENCE / f'command_{node}.json', command)
    claim = {
        'prepared_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Beam BF16 SWE-bench Pro Verified round 1; only tasks with no task directory in the killed original handoff.',
        'source_command': str(SOURCE), 'source_command_sha256': digest(SOURCE),
        'source_audit': str(SOURCE_AUDIT), 'source_audit_sha256': digest(SOURCE_AUDIT),
        'source_handoff_root': str(previous), 'source_handoff_launch_sha256': digest(HANDOFF / 'launch.json'),
        'disk_correction_audit_sha256': digest(DISK_AUDIT),
        'source_handoff_task_dirs': len(started), 'source_handoff_result_tasks': len(results),
        'source_interrupted_with_no_result': interrupted,
        'selected_never_started_task_count': len(selected), 'selected_never_started_tasks': selected,
        'cpu_allocation': CPU_JOB, 'model': load(ORIGINAL_READY)['model'],
        'revision': load(ORIGINAL_READY)['revision'], 'precision': 'BF16',
        'model_image_digest': load(ORIGINAL_READY)['image_digest'],
        'splits': {node: {'allocation': int(node), 'endpoint': SPLITS[node]['endpoint'],
                          'tasks': tasks, 'run_name': run_name(node), 'run_id': run_id(node),
                          'command': str(EVIDENCE / f'command_{node}.json'),
                          'command_sha256': digest(EVIDENCE / f'command_{node}.json')}
                   for node, tasks in halves.items()},
        'only_changes': ['disjoint never-started task selection', 'equivalent pinned BF16 endpoint',
                         'distinct result run ID', 'task concurrency 6 to 4', 'CPU allocation 2968'],
        'thinking_preserved': True, 'no_best_of_selection': True,
        'interrupted_originals_retained_not_scored_as_failures': True,
    }
    save_new(CLAIM, claim)
    print(json.dumps({'claim': str(CLAIM), 'tasks': len(selected),
                      'splits': {node: len(tasks) for node, tasks in halves.items()}}))


def run(node):
    assert node in SPLITS
    claim = load(CLAIM)
    assert claim['source_command_sha256'] == digest(SOURCE)
    assert claim['source_audit_sha256'] == digest(SOURCE_AUDIT)
    assert claim['disk_correction_audit_sha256'] == digest(DISK_AUDIT)
    command_path = EVIDENCE / f'command_{node}.json'
    assert claim['splits'][node]['command_sha256'] == digest(command_path)
    assert not (STATE / f'exit_{node}.json').exists()
    slurm_running(CPU_JOB, 'ip-10-1-100-204')
    slurm_running(int(node), SPLITS[node]['host'])
    model_ready(node)
    temp_dir = f'/opt/sagemaker/tmp/zhiyuan-beam-pro-r1-unstarted-{node}'
    subprocess.run(['srun', f'--jobid={CPU_JOB}', '--overlap', '--gres=none', '-N1', '-n1',
                    '-c1', '--immediate=10', 'mkdir', '-p', temp_dir], check=True)
    command = load(command_path)
    environment = ['env', 'OPENAI_API_KEY=EMPTY',
                   f'MIX_SERVER_IP={urlsplit(SPLITS[node]["endpoint"]).hostname}',
                   'HF_HOME=/fsx/home/zhiyuan/bench/hf_home',
                   'UV_CACHE_DIR=/fsx/home/zhiyuan/bench/uv_cache', f'TMPDIR={temp_dir}']
    STATE.mkdir(parents=True, exist_ok=True)
    log = STATE / f'controller_{node}.log'
    with log.open('a') as out:
        process = subprocess.run(['srun', f'--jobid={CPU_JOB}', '--overlap', '--gres=none',
                                  '-N1', '-n1', '-c16', '--immediate=10', *environment,
                                  *command], cwd=BASE / 'AgentCompass', stdout=out,
                                 stderr=subprocess.STDOUT)
    save_new(STATE / f'exit_{node}.json', {'utc': datetime.now(timezone.utc).isoformat(),
             'node': node, 'returncode': process.returncode})
    if process.returncode:
        raise SystemExit(process.returncode)


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif len(sys.argv) == 3 and sys.argv[1] == 'run' and sys.argv[2] in SPLITS:
        run(sys.argv[2])
    else:
        raise SystemExit('usage: script.py prepare | run {2733|2887}')
