#!/usr/bin/env python3
"""Publish aggregated progress only; credentials and prompt/response bodies stay private."""
import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('--repo', type=Path, required=True)
    a = p.parse_args()
    lock = (a.state / 'publish.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    def git(*args):
        return subprocess.run(['git', '-C', str(a.repo), *args], check=True, capture_output=True, text=True)
    git('sparse-checkout', 'set', '--no-cone', '/evidence/muse_controlled_perf_20261028/')
    git('pull', '--rebase', 'origin', 'main')
    env = dict(os.environ, PYTHONPATH=str(a.state / 'plot_deps'))
    subprocess.run([sys.executable, str(a.state / 'report.py'), '--state', str(a.state)], env=env, check=True)
    subprocess.run([sys.executable, str(a.state / 'plot.py'), '--state', str(a.state)], env=env, check=True)
    dest = a.repo / 'evidence/muse_controlled_perf_20261028'
    dest.mkdir(parents=True, exist_ok=True)
    old = json.loads((dest / 'progress.json').read_text()) if (dest / 'progress.json').exists() else {}
    receipts = old.get('raw_archives', {})
    rounds = []
    for path in sorted(a.state.glob('*/cache-*/*/c*/summary.json')):
        row = json.loads(path.read_text())
        row['artifact'] = str(path.relative_to(a.state))
        rounds.append(row)
        raw = path.parent / 'requests.jsonl.gz'
        name = str(raw.relative_to(a.state))
        if name not in receipts:
            with raw.open('rb') as f:
                sha = hashlib.file_digest(f, 'sha256').hexdigest()
            receipts[name] = {'bytes': raw.stat().st_size, 'sha256': sha, 'location': str(raw)}
    plan = json.loads((a.state / 'PLAN.json').read_text())
    jobs = subprocess.run(['squeue', '-h', '-j', ','.join(map(str, plan['jobs'].values())),
                           '-o', '%i|%T|%D|%R'], capture_output=True, text=True)
    states = {d: json.loads((a.state / d / 'status.json').read_text())
              for d in ('nvfp4', 'bf16') if (a.state / d / 'status.json').exists()}
    progress = {'updated_unix': time.time(), 'jobs': jobs.stdout.splitlines(), 'job_query_returncode': jobs.returncode,
                'states': states, 'rounds': rounds, 'raw_archives': receipts,
                'controlled_rounds_completed': len(rounds), 'valid_rounds': sum(r['valid_curve_point'] for r in rounds),
                'state_directory': str(a.state), 'private_prompt_and_response_bodies_uploaded': False}
    acceptance = json.loads((a.state / 'report/acceptance.json').read_text())
    progress['full_protocol_complete'] = acceptance['complete']
    progress['complete_protocol_points'] = sum(r['status'] == 'complete' for r in acceptance['targets'])
    progress['currently_enumerated_target_points'] = len(acceptance['targets'])
    (dest / 'progress.json').write_text(json.dumps(progress, indent=2) + '\n')
    for name in ('all_rounds.csv', 'detailed_rounds.csv', 'detailed_points.csv', 'acceptance_matrix.csv',
                 'acceptance.json', 'reproducibility.json', 'REPORT.zh-CN.md', 'synthetic.png', 'synthetic.pdf', 'coding.png', 'coding.pdf', 'status.json'):
        src = a.state / 'report' / name
        if src.exists():
            shutil.copyfile(src, dest / name)
    git('add', '--sparse', '--', 'evidence/muse_controlled_perf_20261028')
    unchanged = subprocess.run(['git', '-C', str(a.repo), 'diff', '--cached', '--quiet']).returncode
    if unchanged == 0:
        print('No new progress artifacts to commit', flush=True)
        return
    assert unchanged == 1, 'Could not inspect staged progress artifacts'
    git('-c', 'user.name=Zhiyuan Hu', '-c', 'user.email=29817400+zhiyuanhubj@users.noreply.github.com',
        'commit', '-m', 'Update controlled Muse performance experiment progress')
    result = git('push', 'origin', 'HEAD:main')
    print(result.stderr, flush=True)


if __name__ == '__main__':
    main()
