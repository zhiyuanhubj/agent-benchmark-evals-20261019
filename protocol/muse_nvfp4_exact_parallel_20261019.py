"""Run disjoint exact-image TB round-1 batches alongside the existing controller.

The existing controller reads parallel-owner markers in harbor_entry.py. It waits
for this lane and verifies every terminal task before advancing, so no graded
task is replayed or silently skipped.
"""
import fcntl
import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def write_json(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def heartbeat(path, stop):
    while not stop.is_set():
        path.touch()
        stop.wait(30)


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2922'
    lock = (STATE / 'parallel-2866-controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
    items = [row for row in plan['configurations'] if row['round'] == 1 and row['job_name'][-3:] in {f'b{i:02d}' for i in range(1, 8)}]
    assert len(items) == 7 and sum(map(lambda row: len(row['tasks']), items)) == 68
    for item in items:
        config = Path(item['path'])
        assert hashlib.sha256(config.read_bytes()).hexdigest() == item['sha256']
        assert not (STATE / (item['job_name'] + '-launch.json')).exists(), 'Original controller already owns batch'
        assert not (ROOT / 'results/muse_nvfp4' / item['job_name']).exists(), 'Batch already has results'
        marker = STATE / (config.stem + '-parallel-owner.json')
        assert not marker.exists(), 'Parallel ownership already claimed'
    for item in items:
        config = Path(item['path'])
        write_json(STATE / (config.stem + '-parallel-owner.json'), {
            'utc': time.time(), 'owner': 'parallel_muse_nvfp4_2866.py',
            'slurm_job_id': 2922, 'config_sha256': item['sha256'],
            'tasks': item['tasks'],
        })
        (STATE / (config.stem + '-parallel-heartbeat')).touch()
    env = os.environ.copy()
    env.update(MUSE_TB_PARALLEL_OWNER='1', OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home', UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
    for item in items:
        config = Path(item['path'])
        stop = threading.Event()
        thread = threading.Thread(target=heartbeat, args=(STATE / (config.stem + '-parallel-heartbeat'), stop), daemon=True)
        thread.start()
        log = STATE / (item['job_name'] + '-parallel.log')
        try:
            with log.open('a') as stream:
                result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(config)], env=env, stdout=stream, stderr=subprocess.STDOUT)
            write_json(STATE / (config.stem + '-parallel-exit.json'), {
                'utc': time.time(), 'returncode': result.returncode,
                'config_sha256': item['sha256'], 'job_name': item['job_name'],
            })
            assert result.returncode == 0, 'Parallel batch failed; preserve outputs and audit before relaunch'
        finally:
            stop.set()
            thread.join()
    write_json(STATE / 'parallel-2866-round1-finished.json', {'utc': time.time(), 'batches': [item['job_name'] for item in items]})


if __name__ == '__main__':
    main()
