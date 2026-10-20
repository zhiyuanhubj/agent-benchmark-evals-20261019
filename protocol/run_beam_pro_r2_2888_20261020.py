#!/usr/bin/env python3
"""Launch one independent 731-task Beam Pro round on the verified 2888 replica."""

import fcntl
import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path('/fsx/home/zhiyuan/.private/beam_20261018')
WORK = ROOT / 'legacy_bench_20261018/remaining_pro'
STATE = WORK / 'round2_2888_20261020'
SOURCE = WORK / 'pro-command.template.json'
INITIAL = ROOT / ('legacy_bench_20261018/pro-results/beam_initial_fixed128/'
                  'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent/'
                  'beam-pro-r1-initial128/params.json')
INVENTORY = Path('/fsx/home/zhiyuan/AgentCompass-official-baseline/data/'
                 'swe_bench_pro_verified/swebench_pro_verified.jsonl')
READY = ROOT / 'expanded_capacity_20261018/allocation-2888-rank-0/serving-conformance-ready.json'
ENDPOINT = 'http://10.1.108.251:31328/v1'
RUN_NAME = 'beam_pro_full731_round2_2888_20261020'
RUN_ID = 'beam-pro-full731-r2-2888-20261020'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_option(command, option, value):
    command[command.index(option) + 1] = value


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2922'
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim = STATE / 'launch-claim.json'
        assert not claim.exists(), 'Existing claim requires audit before another launch'
        ready = json.loads(READY.read_text())
        assert ready['api_base'] == ENDPOINT
        assert ready['precision'] == 'BF16'
        assert ready['revision'] == '78f8f654d40a40919b8e9954b40dd879ecb9a692'
        assert ready['full_retry_conformance'] == '133/133'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(ENDPOINT + '/models', timeout=15) as response:
            assert any(model['id'] == 'Beam-1.0-501B-A23B'
                       for model in json.load(response)['data'])

        inventory = [json.loads(line)['instance_id'] for line in INVENTORY.open()]
        assert len(inventory) == len(set(inventory)) == 731
        source = json.loads(SOURCE.read_text())
        source_ids = json.loads(source[source.index('--benchmark-params') + 1])['sample_ids']
        initial_ids = json.loads(INITIAL.read_text())['benchmark']['params']['sample_ids']
        assert len(source_ids) == 603 and len(initial_ids) == 128
        assert not set(source_ids) & set(initial_ids)
        assert set(source_ids) | set(initial_ids) == set(inventory)
        assert source[source.index('--run-id') + 1] == 'beam-pro-r1-remaining603'
        assert source[source.index('--model-base-url') + 1] == 'http://10.1.25.253:31328/v1'
        assert source[source.index('--k') + 1] == '1'
        assert source[source.index('--attempt-strategy') + 1] == 'pass'
        output = WORK / 'pro-results' / RUN_NAME
        assert not output.exists(), 'Independent round already has a result directory'

        command = list(source)
        set_option(command, '--run-name', RUN_NAME)
        set_option(command, '--run-id', RUN_ID)
        set_option(command, '--task-concurrency', '6')
        set_option(command, '--benchmark-params', json.dumps({'sample_ids': inventory}, separators=(',', ':')))
        set_option(command, '--model-base-url', ENDPOINT)
        (STATE / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        claim.write_text(json.dumps({
            'utc': datetime.now(timezone.utc).isoformat(),
            'purpose': 'Independent second model draw on all 731 official Pro Verified task IDs',
            'precision': 'BF16', 'model_allocation': 2888, 'cpu_allocation': 2922,
            'endpoint': ENDPOINT, 'run_name': RUN_NAME, 'run_id': RUN_ID,
            'task_count': len(inventory), 'task_inventory_sha256': digest(INVENTORY),
            'source_command_sha256': digest(SOURCE), 'initial_params_sha256': digest(INITIAL),
            'replica_ready_sha256': digest(READY),
            'same_protocol_except': ['independent round id', 'all 731 task IDs',
                                     'verified 2888 model endpoint', 'task concurrency 2 to 6'],
            'scoring_policy': 'Score native round-2 rewards separately; do not mix with round 1 or reuse trajectories.',
        }, indent=2) + '\n')
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.108.251',
                   HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache',
                   TMPDIR='/opt/sagemaker/tmp/zhiyuan-beam-pro-r2-2888')
        Path(env['TMPDIR']).mkdir(parents=True, exist_ok=True)
        outcome = subprocess.run(command, cwd='/fsx/home/zhiyuan/AgentCompass', env=env)
        (STATE / 'exit.json').write_text(json.dumps({
            'utc': datetime.now(timezone.utc).isoformat(),
            'returncode': outcome.returncode,
        }, indent=2) + '\n')
        raise SystemExit(outcome.returncode)


if __name__ == '__main__':
    main()
