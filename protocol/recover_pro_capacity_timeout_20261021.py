#!/usr/bin/env python3
"""Replace expired allocation 2928; continue only never-started Pro task IDs."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
REPO = BASE / 'agent-benchmark-evals-20261019'
WORK = BASE / '.private/spare_pro_capacity_20261021'
STATE = WORK / 'recovery-2928'
ORIGINAL = WORK / 'claims/muse-pro-r3-shard0-2928-capacity-20261021'
SOURCE = BASE / '.private/muse_spark_open_20261016/review_bench_20261018/deployment.json'
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
JOBS = (2989, 2990)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def prepare():
    STATE.mkdir(exist_ok=True)
    assert not (STATE / 'plan.json').exists()
    accounting = subprocess.check_output(['sacct', '-X', '-j', '2928', '-n', '-P',
        '-o', 'JobID,State,End,NodeList'], text=True).strip()
    assert '|TIMEOUT|' in accounting
    claim = read(ORIGINAL / 'claim.json')
    started, terminal, proof = [], [], {}
    for task in (WORK / 'results' / claim['run_id']).glob('*/*/details/*/task.json'):
        task_id = read(task)['task_id']
        assert task_id in claim['task_ids'] and task_id not in started
        started.append(task_id)
        proof[str(task)] = sha(task)
        result = task.parent / 'attempt-1/result.json'
        if result.exists():
            terminal.append(task_id)
            proof[str(result)] = sha(result)
    pending = [task for task in claim['task_ids'] if task not in started]
    assert len(pending) + len(started) == len(claim['task_ids'])
    save(STATE / 'plan.json', {
        'utc': time.time(), 'original_allocation': 2928, 'accounting': accounting,
        'original_claim': str(ORIGINAL / 'claim.json'),
        'original_claim_sha256': sha(ORIGINAL / 'claim.json'), 'original_run_id': claim['run_id'],
        'original_command_sha256': sha(ORIGINAL / 'command.json'),
        'started_task_ids': started, 'terminal_task_ids': terminal,
        'interrupted_task_ids': [task for task in started if task not in terminal],
        'pending_task_ids': pending, 'native_proof_sha256': proof,
        'deployment_sha256': sha(SOURCE), 'runner_sha256': sha(__file__),
        'candidate_allocations': list(JOBS), 'task_concurrency': 4,
        'policy': 'Only never-started tasks move. Original grades and sampled interrupted tasks '
                  'remain preserved; no restarted model draw, best-of, or correctness-based selection. '
                  'Original model/harness settings retained; concurrency increases from 2 to 4.'})
    print(json.dumps({'pending': len(pending), 'terminal': len(terminal),
                      'interrupted': len(started) - len(terminal)}), flush=True)


def verify():
    plan = read(STATE / 'plan.json')
    assert plan['runner_sha256'] == sha(__file__)
    assert plan['deployment_sha256'] == sha(SOURCE)
    assert plan['original_claim_sha256'] == sha(ORIGINAL / 'claim.json')
    assert plan['original_command_sha256'] == sha(ORIGINAL / 'command.json')
    assert all(sha(path) == digest for path, digest in plan['native_proof_sha256'].items())
    return plan


def local_env():
    env = dict(os.environ)
    for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        env.pop(key, None)
    return env


def serve(job):
    verify()
    assert int(os.environ['SLURM_JOB_ID']) == job
    assert not subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid',
        '--format=csv,noheader'], text=True).strip(), 'GPU already occupied'
    env = local_env()
    subprocess.run(['docker', '--host=unix:///var/run/docker.sock', 'info',
        '--format', '{{.ServerVersion}}'], env=env, check=True, stdout=subprocess.DEVNULL)
    command = list(read(SOURCE)['command'])
    command.insert(1, '--host=unix:///var/run/docker.sock')
    command[command.index('--name')+1] = f'zhiyuan-muse-pro-replace-{job}'
    process = subprocess.Popen(command, env=env)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for _ in range(360):
        assert process.poll() is None, f'Model startup exited: {process.returncode}'
        try:
            with opener.open('http://127.0.0.1:31320/get_server_info', timeout=5) as response:
                info = json.load(response)
            assert info['quantization'] == 'modelopt_fp4' and info['tp_size'] == 8
            assert info['kv_cache_dtype'] == 'fp8_e4m3' and info['max_running_requests'] == 8
            break
        except (OSError, ValueError):
            time.sleep(10)
    else:
        raise RuntimeError('Model not ready within one hour')
    ip = socket.gethostbyname(socket.gethostname())
    save(STATE / 'ready.json', {'utc': time.time(), 'allocation': job, 'host': ip,
        'endpoint': f'http://{ip}:31320/v1', 'model': 'muse-spark-open-nvfp4',
        'precision': 'NVFP4', 'kv_cache_dtype': info['kv_cache_dtype'],
        'runner_sha256': sha(__file__)})
    raise SystemExit(process.wait())


def run(job):
    plan = verify()
    ready = read(STATE / 'ready.json')
    assert ready['allocation'] == job == int(os.environ['SLURM_JOB_ID'])
    assert shutil.disk_usage('/opt/dlami/nvme').free >= 250 * 2**30
    assert not (STATE / 'started.json').exists(), 'Never restart a sampled continuation'
    run_id = f'muse-pro-r3-shard0-timeout2928-{job}-20261021'
    assert not (WORK / 'results' / run_id).exists()
    command = read(ORIGINAL / 'command.json')
    params = json.loads(command[command.index('--benchmark-params')+1])
    params['sample_ids'] = plan['pending_task_ids']
    for flag, value in {'--run-id': run_id, '--run-name': run_id,
                       '--model-base-url': ready['endpoint'], '--task-concurrency': '4',
                       '--benchmark-params': json.dumps(params)}.items():
        command[command.index(flag)+1] = value
    save(STATE / 'continuation-command.json', command)
    save(STATE / 'started.json', {'utc': time.time(), 'allocation': job, 'run_id': run_id,
        'plan_sha256': sha(STATE / 'plan.json'), 'command_sha256': sha(STATE / 'continuation-command.json'),
        'expected': len(plan['pending_task_ids']), 'ready_sha256': sha(STATE / 'ready.json')})
    env = local_env()
    env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP=ready['host'],
               HF_HOME=str(BASE / 'bench/hf_home'), UV_CACHE_DIR=str(BASE / 'bench/uv_cache'),
               TMPDIR=f'/opt/dlami/nvme/zhiyuan-{run_id}')
    Path(env['TMPDIR']).mkdir(exist_ok=True)
    with (STATE / 'controller.log').open('a') as stream:
        process = subprocess.Popen(command, env=env, cwd=BASE / 'AgentCompass',
                                   stdout=stream, stderr=subprocess.STDOUT)
        from protocol.run_spare_pro_capacity_20261021 import prune_graded_images
        while process.poll() is None:
            try:
                prune_graded_images(STATE, WORK / 'results' / run_id)
            except Exception as error:
                with (STATE / 'guard-errors.log').open('a') as log:
                    log.write(str(error)+'\n')
            time.sleep(30)
    save(STATE / 'exit.json', {'utc': time.time(), 'returncode': process.returncode})
    raise SystemExit(process.returncode)


def launch(unit, job, action, cpus):
    log = STATE / (action+'.log')
    subprocess.run(['systemd-run', '--user', '--unit='+unit,
        '--working-directory='+str(REPO),
        '--property=StandardOutput=append:'+str(log), '--property=StandardError=append:'+str(log),
        '/usr/local/bin/srun', f'--jobid={job}', '--overlap', '--gres=none',
        '-N1', '-n1', f'-c{cpus}', '--immediate=10', PYTHON, '-m',
        'protocol.recover_pro_capacity_timeout_20261021', action, '--job', str(job)],
        cwd=REPO, check=True)


def watch():
    verify()
    with (STATE / 'watcher.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not (STATE / 'assignment.json').exists()
        while True:
            rows = subprocess.check_output(['squeue', '-h', '-j', ','.join(map(str,JOBS)),
                                           '-o', '%i|%T'], text=True)
            states = dict(line.split('|') for line in rows.splitlines())
            granted = [job for job in JOBS if states.get(str(job)) == 'RUNNING']
            if granted:
                job = granted[0]
                save(STATE / 'assignment.json', {'utc': time.time(), 'allocation': job})
                for other in JOBS:
                    if other != job and states.get(str(other)) in ('PENDING', 'RUNNING'):
                        subprocess.run(['scancel', str(other)], check=True)
                break
            time.sleep(30)
        unit = f'muse-pro-replacement-{job}-20261021'
        launch(unit+'-serve', job, 'serve', 32)
        for _ in range(150):
            if (STATE / 'ready.json').exists():
                launch(unit+'-run', job, 'run', 16)
                return
            phase = subprocess.check_output(['systemctl','--user','is-active',unit+'-serve.service'],
                                            text=True).strip()
            assert phase in ('active','activating'), phase
            time.sleep(30)
        raise RuntimeError('Replacement deployment readiness timeout')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare','watch','serve','run'))
    parser.add_argument('--job', type=int, choices=JOBS)
    args = parser.parse_args()
    if args.action in ('serve','run'):
        globals()[args.action](args.job)
    else:
        globals()[args.action]()
