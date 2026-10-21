#!/usr/bin/env python3
"""Run a predeclared, independent Pro Verified round-two shard on Muse NVFP4."""

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/muse_spark_open_20261016'
WORK = SOURCE / 'pro_round2_20261021'
STATE = WORK / 'shard0-2900'
COMMAND = STATE / 'command.json'
CLAIM = STATE / 'claim.json'
READY = (BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/'
         'muse_nvfp4/state/replica-2900/endpoint-ready.json')
INVENTORY = (BASE / 'AgentCompass-official-baseline/data/'
             'swe_bench_pro_verified/swebench_pro_verified.jsonl')
ENDPOINT = 'http://10.1.101.159:31321/v1'
RUN_NAME = 'muse-pro-r2'
RUN_ID = 'muse-nvfp4-pro-r2-shard0-2900'
RESULTS = WORK / 'results'
RUN_DIR = (RESULTS / RUN_NAME /
           'muse-spark-open-nvfp4_swebench_pro_verified_mini_swe_agent' / RUN_ID)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def source_shards():
    paths = [SOURCE / f'shard{i}/configs/pro-command.json' for i in range(4)]
    commands = [json.loads(path.read_text()) for path in paths]
    groups = []
    for command in commands:
        assert command[command.index('--k') + 1] == '1'
        assert command[command.index('--attempt-strategy') + 1] == 'pass'
        groups.append(json.loads(command[command.index('--benchmark-params') + 1])['sample_ids'])
    all_ids = [task for group in groups for task in group]
    inventory = [json.loads(line)['instance_id'] for line in INVENTORY.open()]
    assert len(all_ids) == len(set(all_ids)) == len(inventory) == len(set(inventory)) == 731
    assert set(all_ids) == set(inventory)
    assert [len(group) for group in groups] == [183, 183, 183, 182]
    return paths, commands, groups


def set_option(command, option, value):
    command[command.index(option) + 1] = value


def prepare():
    assert not STATE.exists() and not RUN_DIR.exists()
    ready = json.loads(READY.read_text())
    assert ready['allocation'] == 2900 and ready['precision'] == 'NVFP4'
    assert ready['model'] == 'muse-spark-open-nvfp4' and ready['api_base'] == ENDPOINT
    paths, commands, groups = source_shards()
    original = commands[0]
    command = list(original)
    set_option(command, '--results-dir', str(RESULTS))
    set_option(command, '--run-name', RUN_NAME)
    set_option(command, '--run-id', RUN_ID)
    set_option(command, '--model-base-url', ENDPOINT)
    set_option(command, '--task-concurrency', '2')
    assert json.loads(command[command.index('--benchmark-params') + 1])['sample_ids'] == groups[0]
    assert command[command.index('--model-params') + 1] == original[original.index('--model-params') + 1]
    assert command[command.index('--harness-params') + 1] == original[original.index('--harness-params') + 1]
    STATE.mkdir(parents=True)
    write_once(COMMAND, command)
    write_once(CLAIM, {
        'utc': datetime.now(timezone.utc).isoformat(),
        'purpose': 'Independent second draw, predeclared shard zero of the 731 official Pro Verified task IDs',
        'model_allocation': 2900, 'precision': 'NVFP4', 'endpoint': ENDPOINT,
        'run_id': RUN_ID, 'run_name': RUN_NAME, 'expected_shard_tasks': len(groups[0]),
        'full_inventory_tasks': 731, 'task_ids': groups[0],
        'source_shards': [{'path': str(path), 'sha256': sha(path)} for path in paths],
        'inventory': str(INVENTORY), 'inventory_sha256': sha(INVENTORY),
        'endpoint_ready': str(READY), 'endpoint_ready_sha256': sha(READY),
        'command': str(COMMAND), 'command_sha256': sha(COMMAND),
        'runner': str(Path(__file__)), 'runner_sha256': sha(Path(__file__)),
        'protocol_changes': ['new round and output IDs', 'verified 2900 NVFP4 endpoint',
                             'task concurrency 4 to 2 for local Docker disk capacity'],
        'scoring_policy': 'Score only this independent round-two shard; never merge it into round one.',
    })
    print(json.dumps({'run_id': RUN_ID, 'tasks': len(groups[0]), 'claim_sha256': sha(CLAIM)}))


def run():
    assert os.environ.get('SLURM_JOB_ID') == '2900'
    assert os.uname().nodename == 'ip-10-1-101-159'
    claim = json.loads(CLAIM.read_text())
    assert claim['command_sha256'] == sha(COMMAND)
    assert claim['endpoint_ready_sha256'] == sha(READY)
    assert claim['runner_sha256'] == sha(Path(__file__))
    assert not RUN_DIR.exists(), 'Preserve partial attempts; do not restart this draw'
    assert shutil.disk_usage('/opt/dlami/nvme').free >= 300 * 2**30
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(ENDPOINT + '/models', timeout=20) as response:
        assert any(row['id'] == 'muse-spark-open-nvfp4'
                   for row in json.load(response)['data'])
    with (STATE / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not (STATE / 'started.json').exists()
        write_once(STATE / 'started.json', {
            'utc': datetime.now(timezone.utc).isoformat(), 'claim_sha256': sha(CLAIM),
            'command_sha256': sha(COMMAND), 'allocation': 2900,
        })
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.101.159',
                   HF_HOME=str(BASE / 'bench/hf_home'),
                   UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
                   TMPDIR='/opt/dlami/nvme/zhiyuan-pro-r2-2900')
        Path(env['TMPDIR']).mkdir(parents=True, exist_ok=True)
        with (STATE / 'controller.log').open('a') as stream:
            outcome = subprocess.run(json.loads(COMMAND.read_text()),
                                     cwd=BASE / 'AgentCompass', env=env,
                                     stdout=stream, stderr=subprocess.STDOUT)
        write_once(STATE / 'exit.json', {
            'utc': datetime.now(timezone.utc).isoformat(), 'returncode': outcome.returncode,
            'run_dir': str(RUN_DIR),
        })
        raise SystemExit(outcome.returncode)


if __name__ == '__main__':
    assert len(sys.argv) == 2 and sys.argv[1] in ('prepare', 'run')
    (prepare if sys.argv[1] == 'prepare' else run)()
