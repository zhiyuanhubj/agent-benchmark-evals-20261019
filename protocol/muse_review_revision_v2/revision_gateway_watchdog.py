"""Stop a revision lane if the model bridge fails before four first responses.

This watcher never retries a task or changes a score. It preserves the native
outputs and records the interruption for explicit infrastructure recovery.
"""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
LANES = (
    ('muse-coder', 'swe-review-bridge-recovery-muse-coder-20261020', Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_coder_30b_500/gateway-recovery-20261020/queue')),
    ('muse-instruct', 'swe-review-bridge-recovery-muse-instruct-20261020', Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue')),
    ('beam-instruct', 'swe-review-bridge-recovery-beam-instruct-20261020', Path('/fsx/home/zhiyuan/.private/beam_20261018/review_bench/revision/generation/qwen3_30b_instruct2507_500/gateway-recovery-20261020/queue')),
)

lock = (ROOT / 'revision-gateway-watchdog.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(utc=time.time(), **value), indent=2) + '\n')
    temp.replace(path)


while True:
    observed = {}
    for label, unit, queue in LANES:
        status = subprocess.check_output(['systemctl', '--user', 'show', unit + '.service',
                                          '-p', 'ActiveState', '-p', 'MainPID', '-p', 'Result'], text=True)
        active = 'ActiveState=active' in status
        failed = []
        for path in (queue / 'results').rglob('result.json') if (queue / 'results').exists() else ():
            try:
                result = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            exception = result.get('exception_info') or {}
            if result.get('task_name') and result.get('finished_at') and \
                    exception.get('exception_message') == 'Model unavailable before first response':
                failed.append(str(path))
        exit_path = queue / 'queue-exit.json'
        terminal = exit_path.exists()
        if active and len(failed) >= 4:
            subprocess.run(['systemctl', '--user', 'stop', unit + '.service'], check=True)
            alert = dict(lane=label, unit=unit, reason='At least four native trials could not reach the model before any response',
                         failed_native_result_files=failed, queue=str(queue),
                         treatment='Infrastructure interruption; no automatic model retry or score conversion')
            save(ROOT / ('revision-gateway-alert-' + label + '.json'), alert)
            active = False
        observed[label] = dict(unit=unit, active=active, terminal=terminal,
                               pre_model_connection_failures=len(failed),
                               needs_review=not active and not terminal)
    save(ROOT / 'revision-gateway-watchdog-current.json', dict(lanes=observed))
    if '--once' in sys.argv:
        break
    time.sleep(30)
