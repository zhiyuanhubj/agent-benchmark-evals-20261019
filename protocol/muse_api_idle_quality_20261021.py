#!/usr/bin/env python3
"""Run a bounded, separately labelled quality probe only on an idle BF16 API."""
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path('/fsx/home/zhiyuan/.private/muse_openai_api_20261021')
STATE = ROOT / 'background-current.json'
RELAY = 'http://127.0.0.1:8119'


def save(**fields):
    value = {'utc': datetime.now(timezone.utc).isoformat(), **fields}
    temp = STATE.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2)+'\n')
    temp.replace(STATE)


def utilization():
    query = subprocess.run(['srun', '--jobid=2886', '--overlap', '--gres=none',
        '--nodelist=ip-10-1-13-41', '-N1', '-n1', '-c1', '--immediate=10',
        'nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
        capture_output=True, text=True, timeout=25)
    query.check_returncode()
    values = [int(line) for line in query.stdout.splitlines() if line.strip().isdigit()]
    assert len(values) == 8
    return sum(values)/len(values)


def append_result(value):
    # Private bounded segments; retain previous segments and never log API keys.
    directory = ROOT / 'background-quality'
    directory.mkdir(mode=0o700, exist_ok=True)
    day = datetime.now(timezone.utc).strftime('%Y%m%d')
    for part in range(10000):
        path = directory / f'{day}-{part:04d}.jsonl'
        if not path.exists() or path.stat().st_size < 10 * 2**20:
            with path.open('a') as stream:
                stream.write(json.dumps(value, ensure_ascii=False)+'\n')
            path.chmod(0o600)
            return
    raise RuntimeError('Quality probe storage bound reached')


def main():
    os.umask(0o077)
    admin = {'Authorization': 'Bearer '+(ROOT/'primary.key').read_text().strip()}
    background = {'Authorization': 'Bearer '+(ROOT/'background-quality.key').read_text().strip()}
    with httpx.Client(timeout=httpx.Timeout(60, connect=10), trust_env=False) as client:
        while True:
            try:
                status = client.get(RELAY+'/admin/usage', headers=admin)
                status.raise_for_status()
                activity = status.json()
                if activity['real_active'] or activity['idle_seconds'] < 120:
                    save(phase='yielding_to_real_clients', real_active=activity['real_active'],
                         idle_seconds=round(activity['idle_seconds'], 1))
                else:
                    gpu = utilization()
                    if gpu >= 10:
                        save(phase='yielding_to_existing_gpu_work', leader_gpu_utilization=gpu)
                    else:
                        number = int(time.time()) % 997
                        prompt = f'Compute ({number}+17)*23. Reply with only the final integer.'
                        started = time.time()
                        response = client.post(RELAY+'/v1/chat/completions', headers=background,
                            json={'model': 'muse-spark-open-bf16',
                                  'messages': [{'role': 'user', 'content': prompt}],
                                  'temperature': 0, 'max_tokens': 256, 'stream': False})
                        try:
                            payload = response.json()
                        except ValueError:
                            payload = {'invalid_json': True}
                        append_result({'utc': datetime.now(timezone.utc).isoformat(),
                            'kind': 'nonbenchmark_background_quality_probe', 'prompt': prompt,
                            'expected': (number+17)*23, 'http_status': response.status_code,
                            'elapsed_seconds': time.time()-started, 'response': payload})
                        save(phase='probe_finished' if response.status_code==200 else 'probe_deferred_or_failed',
                             http_status=response.status_code, elapsed_seconds=round(time.time()-started, 3),
                             leader_gpu_utilization_before=gpu)
            except Exception as error:
                save(phase='guard_unavailable_no_probe_sent', error_type=type(error).__name__)
            time.sleep(30)


if __name__ == '__main__':
    main()
