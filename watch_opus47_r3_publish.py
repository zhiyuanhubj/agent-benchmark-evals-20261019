#!/usr/bin/env python3
"""Refresh Opus 4.7 round-three thinking evidence and publish its full score."""

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
TRIALS = Path('/fsx/home/zhiyuan/.private/beam_20261018/tb_v1_exact_images_20261019/results/opus47/opus47-tb-v1-exact-r3')
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'


def log(message):
    print(f'{datetime.now(timezone.utc).isoformat()} {message}', flush=True)


def native_round_complete():
    results = list(TRIALS.glob('*/result.json'))
    return len(results) == 89 and all(isinstance(json.loads(path.read_text()), dict) for path in results)


def published_complete():
    score = json.loads((ROOT / 'results/scores.json').read_text())
    round_three = score['models']['opus_4_7']['tb2_1_exact_supplied_images']['rounds']['3']
    audit = json.loads((ROOT / 'evidence/opus47_r3_thinking_transport_audit.json').read_text())
    release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
    if (round_three['expected'], round_three['graded']) != (89, 89) or not round_three['complete']:
        return False
    if audit['counts']['scored_tasks'] != 89 or audit['counts']['raw_responses'] != sum(
            audit['counts'][key] for key in ('with_thinking_text',
                                              'without_text_zero_reasoning_tokens',
                                              'without_text_positive_reasoning_tokens',
                                              'without_text_unknown_reasoning_tokens')):
        return False
    if release['errors'] or release['manifest_count'] != release['sha256_and_size_match_count']:
        return False
    local = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    remote = subprocess.check_output(['git', 'ls-remote', 'origin', 'HEAD'], cwd=ROOT, text=True, timeout=30).split()[0]
    if local != remote:
        return False
    log(f'complete: {round_three["success"]}/89, thinking cases {len(audit["cases"])}, commit {local}')
    return True


def main():
    log('watching the final exact-image Opus 4.7 round-three task')
    while True:
        try:
            if not native_round_complete():
                time.sleep(30)
                continue
            if published_complete():
                return
            log('all 89 native results exist; refreshing thinking audit and GitHub snapshot')
            subprocess.run([PYTHON, str(ROOT / 'audit_opus47_thinking_transport.py')],
                           cwd=ROOT, check=True, timeout=300)
            subprocess.run([PYTHON, str(ROOT / 'sync_progress.py'), '--once'],
                           cwd=ROOT, check=True, timeout=1800)
            if published_complete():
                return
            log('sync finished, but publication is not yet verified; retrying')
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            log(f'waiting to retry: {type(exc).__name__}: {exc}')
        time.sleep(60)


if __name__ == '__main__':
    main()
