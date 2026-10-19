"""Start the pinned Muse NVFP4 server on a newly granted TB allocation."""
import fcntl
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'muse_nvfp4/state/extra_gpu'
SOURCE = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/deployment.json')
WEIGHTS = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/weights')
ALLOWED = {2812, 2923, 2924, 2927, 2928}
EARLY95 = Path('/fsx/home/zhiyuan/.private/nemotron35super/runs/opus48_mix3_20261014/early95_remaining_after_muse_swr_20261018')


def save(job, phase, **extra):
    path = STATE / f'{job}-status.json'
    temp = path.with_suffix('.tmp')
    value = {'utc': time.time(), 'job': job, 'host': socket.gethostname(), 'phase': phase, **extra}
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)
    if phase == 'ready':
        ready = STATE / f'{job}-ready.json'
        ready_temp = ready.with_suffix('.tmp')
        ready_temp.write_text(json.dumps(value, indent=2) + '\n')
        os.replace(ready_temp, ready)


def main():
    job = int(sys.argv[1])
    assert job in ALLOWED and os.environ.get('SLURM_JOB_ID') == str(job)
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / f'{job}-serve.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if job == 2812:
            previous = json.loads((EARLY95 / 'state/current.json').read_text())
            assert previous.get('phase') == 'declared_backlog_finished' and previous.get('returncodes') == [0, 0, 0]
            for index in range(3):
                assert json.loads((EARLY95 / f'state/job-{index}-exit.json').read_text())['returncode'] == 0
            last = json.loads((EARLY95 / 'results/early95-tb-r3-never-started-20261018/train-fasttext__y5h5Rq5/result.json').read_text())
            assert last.get('finished_at'), 'Last early95 TB task has not finished'
            pid = subprocess.check_output(['systemctl', '--user', 'show',
                'mix3-early95-existing-rounds-after-muse-swr-20261018.service', '-p', 'MainPID', '--value'], text=True).strip()
            assert pid in ('', '0'), 'Prior early95 controller is still running'
        assert (WEIGHTS / 'config.json').exists()
        docker_env = os.environ.copy()
        for key in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
            docker_env.pop(key, None)
        subprocess.run(['docker', '--host=unix:///var/run/docker.sock', 'info', '--format', '{{.ServerVersion}}'], env=docker_env, stdout=subprocess.DEVNULL, check=True)
        gpu_apps = subprocess.check_output(['nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader'], text=True).strip()
        assert not gpu_apps, 'Newly allocated node already has a GPU process; audit before deployment'
        command = list(json.loads(SOURCE.read_text())['command'])
        assert command[:2] == ['docker', 'run']
        command.insert(1, '--host=unix:///var/run/docker.sock')
        command[command.index('--name') + 1] = f'zhiyuan-muse-tb-exact-{job}'
        assert '--quantization' in command and command[command.index('--quantization') + 1] == 'modelopt_fp4'
        save(job, 'launching', command=command)
        process = subprocess.Popen(command, env=docker_env)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(360):
            assert process.poll() is None, f'Muse service exited before readiness: {process.returncode}'
            try:
                with opener.open('http://127.0.0.1:31320/v1/models', timeout=5) as response:
                    models = json.load(response).get('data', [])
                if any(item.get('id') == 'muse-spark-open-nvfp4' for item in models):
                    break
            except OSError:
                pass
            time.sleep(10)
        else:
            raise RuntimeError('Muse NVFP4 endpoint did not become ready within one hour')
        ip = socket.gethostbyname(socket.gethostname())
        assert ip.startswith('10.'), f'Unexpected node IP: {ip}'
        endpoint = f'http://{ip}:31320/v1'
        save(job, 'ready', endpoint=endpoint, model='muse-spark-open-nvfp4', pid=process.pid)
        from muse_nvfp4.route_2812 import prepare_routes
        try:
            routes = prepare_routes(endpoint, job, max_batches=2 if job == 2812 else 1)
            save(job, 'ready', endpoint=endpoint, model='muse-spark-open-nvfp4',
                 pid=process.pid, claimed_round1_batches=routes)
        except Exception as exc:
            save(job, 'ready', endpoint=endpoint, model='muse-spark-open-nvfp4',
                 pid=process.pid, route_error=repr(exc))
        result = process.wait()
        save(job, 'exited', returncode=result)
        raise SystemExit(result)


if __name__ == '__main__':
    main()
