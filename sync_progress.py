#!/usr/bin/env python3
"""Refresh qualified benchmark scores and publish a private GitHub snapshot."""
import fcntl
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
SOURCES = [
    BASE / '.private/beam_20261018/expanded_status.py',
    BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/status.py',
    BASE / '.private/muse_spark_open_20261016/review_bench_20261018/status.py',
    BASE / '.private/muse_bf16_20261018/status.py',
]
LOG = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/github-sync-20261019.jsonl'
LOCK = LOG.with_suffix('.lock')


def run(command, timeout=180):
    return subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=timeout, check=True)


def sync_native_archives(scores):
    recovery = scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']
    terminal = sum(recovery['new_terminal_by_round'].values())
    manifest_dir = ROOT / 'input_output/archive_manifests'
    live_manifests = sorted(manifest_dir.glob('muse_nvfp4_exact_tb_live_*.json'))
    archived_terminal = 0
    if live_manifests:
        latest = json.loads(live_manifests[-1].read_text())
        archived_terminal = latest.get('terminal_result_count', latest['filename_counts']['result'])
    if terminal > archived_terminal:
        run([PYTHON, str(ROOT / 'snapshot_live_tb.py')], timeout=180)
        live_manifests = sorted(manifest_dir.glob('muse_nvfp4_exact_tb_live_*.json'))
    release = json.loads(subprocess.check_output([
        'gh', 'api', 'repos/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tags/2026-10-19-snapshot'
    ], cwd=ROOT, text=True, timeout=60))
    remote = {asset['name'] for asset in release['assets']}
    for manifest_path in live_manifests:
        manifest = json.loads(manifest_path.read_text())
        archive_name = manifest['archive_name']
        if archive_name not in remote:
            archive = ROOT / '.release_assets' / archive_name
            assert archive.is_file(), f'Missing local archive for GitHub upload: {archive_name}'
            run(['gh', 'release', 'upload', '2026-10-19-snapshot', str(archive), '--repo', 'zhiyuanhubj/agent-benchmark-evals-20261019'], timeout=300)
    run([PYTHON, str(ROOT / 'verify_release.py')], timeout=120)


def cycle():
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for source in SOURCES:
            run([PYTHON, str(source)])
        run([PYTHON, str(ROOT / 'export_snapshot.py')])
        scores = json.loads((ROOT / 'results/scores.json').read_text())
        sync_native_archives(scores)
        run([PYTHON, str(ROOT / 'export_snapshot.py')])
        run(['git', 'add', 'README.md', 'REPORT.zh-CN.md', 'results/scores.json', 'evidence', 'input_output/manifest.json', 'input_output/archive_manifests'])
        changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT)
        if changed.returncode == 1:
            run(['git', 'commit', '-m', 'Refresh live benchmark results'])
            run(['git', 'push', 'origin', 'main'])
        elif changed.returncode != 0:
            raise RuntimeError(f'git diff --cached returned {changed.returncode}')
        status = json.loads((ROOT / 'results/scores.json').read_text())
        return {
            'utc': datetime.now(timezone.utc).isoformat(),
            'git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'muse_nvfp4_exact_tb_round1': status['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['1'],
        }


def main():
    while True:
        started = time.monotonic()
        try:
            row = cycle()
        except Exception as exc:
            row = {'utc': datetime.now(timezone.utc).isoformat(), 'error': str(exc), 'traceback': traceback.format_exc()}
        with LOG.open('a') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if '--once' in sys.argv:
            if 'error' in row:
                raise SystemExit(1)
            return
        time.sleep(max(30, 900 - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
