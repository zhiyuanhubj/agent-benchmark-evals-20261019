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
        claim = STATE / f'{job}-launch-claim.json'
        if claim.exists():
            continue
        unit = f'muse-nvfp4-exact-extra-{job}-20261019'
        log_file = STATE / f'{job}-server.log'
        claim.write_text(json.dumps({'utc': datetime.now(timezone.utc).isoformat(), 'job': job, 'unit': unit, 'node': rows[job]['nodes']}, indent=2) + '\n')
        command = [
            'systemd-run', '--user', f'--unit={unit}',
            f'--property=StandardOutput=append:{log_file}',
            f'--property=StandardError=append:{log_file}',
            '/usr/local/bin/srun', f'--jobid={job}', '--overlap', '-N1', '-n1', '-c32', '--immediate=10',
            PYTHON, str(ROOT / 'extra_gpu_serve.py'), str(job),
        ]
        launched = subprocess.run(command, capture_output=True, text=True)
        log(phase='launch_attempt', job=job, node=rows[job]['nodes'], unit=unit, returncode=launched.returncode, message=(launched.stdout + launched.stderr)[-1000:])
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
