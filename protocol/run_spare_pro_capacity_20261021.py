#!/usr/bin/env python3
"""Use idle replicas for disjoint, declared Pro draws; never restart a sampled draw."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
WORK = BASE / '.private/spare_pro_capacity_20261021'
MUSE = BASE / '.private/muse_spark_open_20261016'
BEAM = BASE / '.private/beam_20261018'
INVENTORY = BASE / 'AgentCompass-official-baseline/data/swe_bench_pro_verified/swebench_pro_verified.jsonl'
PLAN = {
    2923: ('muse', 2, 1, '10.1.76.28', 31320, 2),
    2924: ('muse', 2, 2, '10.1.98.133', 31320, 2),
    2927: ('muse', 2, 3, '10.1.98.127', 31320, 2),
    2928: ('muse', 3, 0, '10.1.69.108', 31320, 2),
    2888: ('beam', 3, 0, '10.1.108.251', 31328, 2),
    2901: ('beam', 3, 1, '10.1.95.27', 31328, 2),
    2733: ('beam', 3, 2, '10.1.25.253', 31328, 1),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def layout(job):
    model, round_number, shard, host, port, concurrency = PLAN[job]
    run_id = f'{model}-pro-r{round_number}-shard{shard}-{job}-capacity-20261021'
    state = WORK / 'claims' / run_id
    return model, round_number, shard, host, port, concurrency, run_id, state


def prepare(job):
    model, round_number, shard, host, port, concurrency, run_id, state = layout(job)
    assert not state.exists(), 'Existing claim must be preserved'
    inventory = [json.loads(line)['instance_id'] for line in INVENTORY.open()]
    assert len(inventory) == len(set(inventory)) == 731
    if model == 'muse':
        sources = [MUSE / f'shard{i}/configs/pro-command.json' for i in range(4)]
        commands = [json.loads(p.read_text()) for p in sources]
        groups = [json.loads(c[c.index('--benchmark-params')+1])['sample_ids'] for c in commands]
        assert len(set(t for group in groups for t in group)) == sum(map(len, groups)) == 731
        assert set(t for group in groups for t in group) == set(inventory)
        command = list(commands[shard])
        task_ids = groups[shard]
        model_id, precision = 'muse-spark-open-nvfp4', 'NVFP4'
    else:
        sources = [BEAM / 'legacy_bench_20261018/remaining_pro/pro-command.template.json']
        command = json.loads(sources[0].read_text())
        task_ids = inventory[shard::3]
        model_id, precision = 'Beam-1.0-501B-A23B', 'BF16'
    assert command[command.index('--k')+1] == '1'
    assert command[command.index('--attempt-strategy')+1] == 'pass'
    endpoint = f'http://{host}:{port}/v1'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(endpoint + '/models', timeout=15) as response:
        assert model_id in {row['id'] for row in json.load(response)['data']}
    with opener.open(f'http://{host}:{port}/get_server_info', timeout=15) as response:
        info = json.load(response)
    assert info['dtype'] in ('bfloat16', 'auto')
    assert info['quantization'] == ('modelopt_fp4' if model == 'muse' else None)
    result_root = WORK / 'results'
    changes = {'--results-dir': str(result_root), '--run-name': run_id, '--run-id': run_id,
               '--model-base-url': endpoint, '--task-concurrency': str(concurrency)}
    params = json.loads(command[command.index('--benchmark-params')+1])
    params['sample_ids'] = task_ids
    changes['--benchmark-params'] = json.dumps(params, separators=(',', ':'))
    for flag, value in changes.items():
        command[command.index(flag)+1] = value
    state.mkdir(parents=True)
    save_new(state / 'command.json', command)  # Private; not archived.
    save_new(state / 'claim.json', dict(
        utc=datetime.now(timezone.utc).isoformat(), allocation=job, host=host, model=model,
        model_id=model_id, precision=precision, round=round_number, shard=shard,
        task_ids=task_ids, expected=len(task_ids), full_inventory=731,
        endpoint=endpoint, concurrency=concurrency, run_id=run_id, results_root=str(result_root),
        runner_sha256=sha(__file__), command_sha256=sha(state / 'command.json'),
        inventory_sha256=sha(INVENTORY), source_sha256={str(p): sha(p) for p in sources},
        model_params=json.loads(command[command.index('--model-params')+1]),
        harness_params=json.loads(command[command.index('--harness-params')+1]),
        policy='Independent declared round and disjoint shard; one native attempt per task; '
               'no correctness-based retries or merging across rounds. Returned thinking remains in native traces.'))
    print(json.dumps({'allocation': job, 'run_id': run_id, 'tasks': len(task_ids)}), flush=True)


def prune_graded_images(state, run_dir):
    if shutil.disk_usage('/opt/dlami/nvme').free >= 150 * 2**30:
        return
    graded = {}
    for path in run_dir.glob('*/*/details/*/attempt-1/result.json'):
        row = json.loads(path.read_text())
        evaluation = ((row.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {}
        if evaluation.get('completed') is True and type((row.get('metrics') or {}).get('correct')) is bool:
            task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
            graded[task] = sha(path)
    images = subprocess.check_output(['docker', '--host=unix:///var/run/docker.sock', 'image', 'ls',
                                      '--format', '{{json .}}'], text=True)
    for line in images.splitlines():
        if shutil.disk_usage('/opt/dlami/nvme').free >= 350 * 2**30:
            break
        row = json.loads(line)
        matches = [task for task in graded if task.removeprefix('instance_') in row['Tag']]
        if row['Repository'] != 'jefzda/sweap-images' or len(matches) != 1:
            continue
        tag = row['Repository'] + ':' + row['Tag']
        result = subprocess.run(['docker', '--host=unix:///var/run/docker.sock', 'image', 'rm', tag],
                                capture_output=True, text=True, timeout=90)  # Never force active containers.
        with (state / 'image-guard.jsonl').open('a') as stream:
            stream.write(json.dumps({'utc': time.time(), 'task': matches[0],
                                     'graded_result_sha256': graded[matches[0]], 'tag': tag,
                                     'returncode': result.returncode})+'\n')


def run(job):
    model, round_number, shard, host, port, concurrency, run_id, state = layout(job)
    assert os.environ.get('SLURM_JOB_ID') == str(job)
    assert os.uname().nodename == 'ip-' + host.replace('.', '-')
    claim = json.loads((state / 'claim.json').read_text())
    assert claim['runner_sha256'] == sha(__file__)
    assert claim['command_sha256'] == sha(state / 'command.json')
    assert all(sha(p) == digest for p, digest in claim['source_sha256'].items())
    assert shutil.disk_usage('/opt/dlami/nvme').free >= 250 * 2**30
    run_dir = WORK / 'results' / run_id
    assert not run_dir.exists(), 'A partially sampled draw must not be restarted'
    with (state / 'controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save_new(state / 'started.json', {'utc': time.time(), 'claim_sha256': sha(state / 'claim.json')})
        env = dict(os.environ)
        for name in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            env.pop(name, None)
        env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP=host,
                   HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
                   TMPDIR='/opt/dlami/nvme/zhiyuan-' + run_id)
        Path(env['TMPDIR']).mkdir(exist_ok=True)
        with (state / 'controller.log').open('a') as stream:
            process = subprocess.Popen(json.loads((state / 'command.json').read_text()),
                cwd=BASE / 'AgentCompass', env=env, stdout=stream, stderr=subprocess.STDOUT)
            while process.poll() is None:
                try:
                    prune_graded_images(state, run_dir)
                except Exception as error:
                    with (state / 'guard-errors.log').open('a') as log:
                        log.write(type(error).__name__ + ': ' + str(error) + '\n')
                time.sleep(30)
        save_new(state / 'exit.json', {'utc': time.time(), 'returncode': process.returncode})
        raise SystemExit(process.returncode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('prepare', 'run'))
    parser.add_argument('allocation', type=int, choices=PLAN)
    args = parser.parse_args()
    (prepare if args.operation == 'prepare' else run)(args.allocation)
