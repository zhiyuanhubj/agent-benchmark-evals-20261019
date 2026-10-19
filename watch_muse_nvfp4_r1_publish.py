#!/usr/bin/env python3
"""Publish the exact-image Muse NVFP4 first round as soon as its last batch ends."""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BATCH = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4/muse-nvfp4-tb-v1-exact-r1-completion-2866-b03')
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def log(message):
    print(f'{datetime.now(timezone.utc).isoformat()} {message}', flush=True)


def native_batch_complete():
    results = list(BATCH.glob('*/result.json'))
    if len(results) != 10:
        return False
    # Harbor may create a result file before its JSON write has completed.
    return all(isinstance(json.loads(path.read_text()), dict) for path in results)


def published_complete():
    scores = json.loads((ROOT / 'results/scores.json').read_text())
    round_one = scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['1']
    audit = json.loads((ROOT / 'evidence/muse_nvfp4_exact_round1_audit.json').read_text())
    coverage = json.loads((ROOT / 'evidence/muse_nvfp4_exact_io_coverage.json').read_text())
    release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
    if (round_one['expected'], round_one['graded']) != (89, 89) or not round_one['complete']:
        return False
    if audit['errors'] or audit['qualification'] != 'complete_verified':
        return False
    if (audit['graded_task_count'], audit['success_count']) != (89, round_one['success']):
        return False
    if coverage['errors'] or coverage['qualification'] != 'complete_verified':
        return False
    if release['errors'] or release['manifest_count'] != release['sha256_and_size_match_count']:
        return False
    local = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    remote = subprocess.check_output(['git', 'ls-remote', 'origin', 'HEAD'], cwd=ROOT, text=True, timeout=30).split()[0]
    if local != remote:
        return False
    log(f'complete: {round_one["success"]}/89, commit {local}, {release["manifest_count"]} release assets verified')
    return True


def main():
    log('watching the final exact-image Muse NVFP4 round-one batch')
    while True:
        try:
            if not native_batch_complete():
                time.sleep(30)
                continue
            if published_complete():
                return
            log('all 10 final-batch native results exist; starting audited GitHub sync')
            subprocess.run([PYTHON, str(ROOT / 'sync_progress.py'), '--once'],
                           cwd=ROOT, check=True, timeout=1800)
            if published_complete():
                return
            log('sync finished, but full-round publication is not yet verified; retrying')
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            log(f'waiting to retry: {type(exc).__name__}: {exc}')
        time.sleep(60)


if __name__ == '__main__':
    main()
