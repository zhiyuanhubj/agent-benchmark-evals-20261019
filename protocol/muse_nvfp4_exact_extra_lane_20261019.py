"""Run preclaimed, disjoint exact-image TB round-1 batches on model node 2866."""
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
ASSIGNMENTS = {2: (2, 3), 3: (4, 5)}


def save(path, value):
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def terminal_coverage(item):
    expected = set(item['tasks'])
    found = set()
    directory = ROOT / 'results/muse_nvfp4' / item['job_name']
    for path in directory.glob('*/result.json'):
        result = json.loads(path.read_text())
        if result.get('finished_at'):
            name = Path(result['config']['task']['path']).name
            assert name in expected and name not in found
            found.add(name)
    return found == expected, expected - found


def main():
    lane = int(sys.argv[1])
    assert lane in ASSIGNMENTS and os.environ.get('SLURM_JOB_ID') == '2922'
    with (STATE / f'extra-lane{lane}-2866-controller.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = json.loads((STATE / 'completion-2866-plan.json').read_text())
        names = {f'muse-nvfp4-tb-v1-exact-r1-completion-2866-b{idx:02d}' for idx in ASSIGNMENTS[lane]}
        items = [row for row in plan['configurations'] if row['job_name'] in names]
        assert len(items) == 2 and sum(len(item['tasks']) for item in items) == 20
        for item in items:
            config = Path(item['path'])
            assert hashlib.sha256(config.read_bytes()).hexdigest() == item['sha256']
            assert not (STATE / (item['job_name'] + '-launch.json')).exists(), 'Original controller already claimed batch'
            assert not (ROOT / 'results/muse_nvfp4' / item['job_name']).exists(), 'Batch already has results'
            assert not (STATE / (config.stem + '-extra-owner.json')).exists(), 'Extra lane already claimed batch'
        for item in items:
            config = Path(item['path'])
            save(STATE / (config.stem + '-extra-owner.json'), {
                'utc': time.time(), 'lane': lane, 'job_name': item['job_name'],
                'config_sha256': item['sha256'], 'tasks': item['tasks'],
            })
        env = os.environ.copy()
        env.update(MUSE_TB_EXTRA_LANE=str(lane), OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home', UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
        for item in items:
            config = Path(item['path'])
            log = STATE / (item['job_name'] + f'-extra-lane{lane}.log')
            with log.open('a') as stream:
                result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), str(config)], env=env, stdout=stream, stderr=subprocess.STDOUT)
            complete, missing = terminal_coverage(item) if result.returncode == 0 else (False, item['tasks'])
            code = result.returncode if result.returncode else (0 if complete else 1)
            save(STATE / (config.stem + '-extra-exit.json'), {
                'utc': time.time(), 'lane': lane, 'job_name': item['job_name'],
                'returncode': code, 'config_sha256': item['sha256'], 'missing_terminal_tasks': list(missing),
            })
            assert code == 0, 'Extra lane failed or left unfinished tasks; preserve outputs and audit'


if __name__ == '__main__':
    main()
