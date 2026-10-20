#!/usr/bin/env python3
"""Continue BF16 Pro round one on 2886 for IDs lacking a native result."""

import fcntl
import hashlib
import json
import os
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE / '.private/muse_bf16_20261018'
WORK = ROOT / 'legacy_bench'
STATE = ROOT / 'recovery_20261020'
ORIGINAL = 'muse-bf16-pro-full-r1'
DERIVED = 'muse-bf16-pro-full-r1-resume-20261020'
DIRECT = 'muse-bf16-pro-r1-direct-2886-20261020'
OLD = 'http://10.1.77.106:31324/v1'
NEW = 'http://10.1.13.41:31324/v1'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_option(command, flag, value):
    command[command.index(flag) + 1] = value


def main():
    assert os.environ.get('SLURM_JOB_ID') == '2919'
    with (STATE / 'pro-direct-2886.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim_path = STATE / 'pro-direct-2886-claim.json'
        assert not claim_path.exists()
        stop = json.loads((STATE / 'bridge-2869-expiry-stop-plan.json').read_text())
        assert stop['old_endpoint'] == OLD and stop['verified_live_model_endpoint'] == NEW
        assert '2869|TIMEOUT|' in subprocess.run(
            ['sacct', '-n', '-P', '-j', '2869', '--format=JobIDRaw,State,End'],
            check=True, capture_output=True, text=True).stdout
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(NEW + '/models', timeout=10) as response:
            assert any(item['id'] == 'muse-spark-open-bf16' for item in json.load(response)['data'])
        source_path = WORK / 'state/pro-r1-launch.json'
        source = json.loads(source_path.read_text())
        assert source['api_base'] == OLD
        command = list(source['command'])
        assert command[command.index('--run-id') + 1] == ORIGINAL
        assert command[command.index('--k') + 1] == '1'
        assert command[command.index('--attempt-strategy') + 1] == 'pass'
        assert '--reuse' not in command
        ids = json.loads(command[command.index('--benchmark-params') + 1])['sample_ids']
        assert len(ids) == len(set(ids)) == 731
        run_root = (WORK / 'pro-results/muse_bf16_full/'
                    'muse-spark-open-bf16_swebench_pro_verified_mini_swe_agent')
        previous = run_root / DERIVED
        assert previous.is_dir() and not (run_root / DIRECT).exists()
        completed, active = {}, {}
        for task_file in (previous / 'details').glob('*/task.json'):
            task = json.loads(task_file.read_text())['task_id']
            assert task in ids and task not in completed and task not in active
            native = task_file.parent / 'attempt-1/result.json'
            if native.exists():
                completed[task] = {'path': str(native), 'sha256': digest(native)}
            else:
                active[task] = {'path': str(task_file.parent),
                                'native_result_exists': False}
        assert len(completed) == 171 and len(active) == 4
        pending = [task for task in ids if task not in completed]
        assert len(pending) == 560 and set(active) <= set(pending)
        set_option(command, '--run-id', DIRECT)
        set_option(command, '--model-base-url', NEW)
        set_option(command, '--benchmark-params',
                   json.dumps({'sample_ids': pending}, separators=(',', ':')))
        set_option(command, '--task-concurrency', '2')
        claim = {
            'utc': datetime.now(timezone.utc).isoformat(),
            'reason': 'Original endpoint bridge allocation 2869 timed out. Continue only tasks without a native result.',
            'precision': 'BF16', 'model_allocation': 2886, 'cpu_allocation': 2919,
            'source_run_id': DERIVED, 'direct_run_id': DIRECT,
            'source_launch_sha256': digest(source_path),
            'source_progress_sha256': digest(previous / 'progress.json'),
            'old_endpoint': OLD, 'verified_direct_endpoint': NEW,
            'all_tasks': 731, 'previous_native_result_count': len(completed),
            'direct_task_count': len(pending), 'direct_task_ids': pending,
            'previous_native_results': completed, 'interrupted_task_ids': sorted(active),
            'command': command,
            'policy': 'One first-round draw per task ID. Prior native results and raw trajectories remain separate; score only after task-level reconciliation.',
        }
        claim_path.write_text(json.dumps(claim, indent=2) + '\n')
        env = os.environ.copy()
        env.update(OPENAI_API_KEY='EMPTY', MIX_SERVER_IP='10.1.13.41',
                   HF_HOME='/fsx/home/zhiyuan/bench/hf_home',
                   UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache',
                   TMPDIR='/opt/sagemaker/tmp/zhiyuan-muse-bf16-pro-direct-20261020')
        Path(env['TMPDIR']).mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=str(BASE / 'AgentCompass'), env=env)
        (STATE / 'pro-direct-2886-exit.json').write_text(json.dumps({
            'utc': datetime.now(timezone.utc).isoformat(),
            'returncode': result.returncode,
        }, indent=2) + '\n')
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
