"""Claim dedicated queued GPU allocations immediately when Slurm grants them."""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / 'muse_nvfp4/state/extra_gpu'
SCORES = Path('/fsx/home/zhiyuan/agent-benchmark-evals-20261019/results/scores.json')
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
JOBS = (2923, 2924, 2927, 2928)
EARLY95 = Path('/fsx/home/zhiyuan/.private/nemotron35super/runs/opus48_mix3_20261014/early95_remaining_after_muse_swr_20261018')
EARLY95_UNIT = 'mix3-early95-existing-rounds-after-muse-swr-20261018.service'


def log(**fields):
    row = {'utc': datetime.now(timezone.utc).isoformat(), **fields}
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'watcher.jsonl').open('a') as stream:
        stream.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


def rounds_finished():
    value = json.loads(SCORES.read_text())
    rounds = value['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']
    return all(round_data.get('complete') is True for round_data in rounds.values())


def round_one_finished():
    value = json.loads(SCORES.read_text())
    return value['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['1'].get('complete') is True


def early95_released():
    state = EARLY95 / 'state/current.json'
    if not state.exists():
        return False
    status = json.loads(state.read_text())
    if status.get('phase') != 'declared_backlog_finished' or status.get('returncodes') != [0, 0, 0]:
        return False
    for index in range(3):
        outcome = EARLY95 / f'state/job-{index}-exit.json'
        if not outcome.exists() or json.loads(outcome.read_text()).get('returncode') != 0:
            return False
    last_trial = EARLY95 / 'results/early95-tb-r3-never-started-20261018/train-fasttext__y5h5Rq5/result.json'
    if not last_trial.exists() or not json.loads(last_trial.read_text()).get('finished_at'):
        return False
    pid = subprocess.check_output(['systemctl', '--user', 'show', EARLY95_UNIT, '-p', 'MainPID', '--value'], text=True).strip()
    return pid in ('', '0')


def untouched_round1_batch():
    for batch in ('b03', 'b05'):
        job = f'muse-nvfp4-tb-v1-exact-r1-completion-2866-{batch}'
        if ((ROOT / 'results/muse_nvfp4' / job).exists()
                or (STATE / f'r1-{batch}-local-started.json').exists()):
            continue
        return True
    return False


def gpu_released(job):
    probe = subprocess.run([
        '/usr/local/bin/srun', f'--jobid={job}', '--overlap', '-N1', '-n1', '-c1', '--immediate=5',
        'nvidia-smi', '--query-compute-apps=pid', '--format=csv,noheader',
    ], capture_output=True, text=True, timeout=20)
    return probe.returncode == 0 and not probe.stdout.strip()


def launch(job, node):
    claim = STATE / f'{job}-launch-claim.json'
    if claim.exists():
        return
    unit = f'muse-nvfp4-exact-extra-{job}-20261019'
    log_file = STATE / f'{job}-server.log'
    claim.write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'job': job, 'unit': unit, 'node': node}, indent=2) + '\n')
    command = [
        'systemd-run', '--user', f'--unit={unit}',
        f'--property=StandardOutput=append:{log_file}',
        f'--property=StandardError=append:{log_file}',
        '/usr/local/bin/srun', f'--jobid={job}', '--overlap', '-N1', '-n1', '-c32', '--immediate=10',
        PYTHON, str(ROOT / 'extra_gpu_serve.py'), str(job),
    ]
    launched = subprocess.run(command, capture_output=True, text=True)
    log(phase='launch_attempt', job=job, node=node, unit=unit, returncode=launched.returncode, message=(launched.stdout + launched.stderr)[-1000:])


def cycle():
    result = subprocess.run(['squeue', '-h', '-j', ','.join(map(str, JOBS)), '-o', '%i|%T|%N'], capture_output=True, text=True, check=True)
    rows = {}
    for line in result.stdout.splitlines():
        job, state, nodes = line.split('|', 2)
        rows[int(job)] = {'state': state, 'nodes': nodes}
    if rounds_finished():
        log(phase='all_three_rounds_complete', allocations=rows)
        return
    for job in JOBS:
        if rows.get(job, {}).get('state') != 'RUNNING':
            continue
        launch(job, rows[job]['nodes'])
    if not round_one_finished() and untouched_round1_batch() and early95_released():
        allocation = subprocess.run(['squeue', '-h', '-j', '2812', '-o', '%T|%N'], capture_output=True, text=True, check=True).stdout.strip()
        if allocation.startswith('RUNNING|'):
            if gpu_released(2812):
                launch(2812, allocation.split('|', 1)[1])
            else:
                log(phase='wait_2812_gpu_cleanup')
    log(phase='poll', allocations=rows)


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            cycle()
        except Exception as exc:
            log(phase='watcher_error', error=repr(exc))
        time.sleep(60)


if __name__ == '__main__':
    main()
