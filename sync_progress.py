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


def sync_native_archives(scores, force_bf16=False):
    recovery = scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['recovery']
    manifest_dir = ROOT / 'input_output/archive_manifests'
    opus_rounds = scores['models']['opus_4_7']['tb2_1_exact_supplied_images']['rounds'].values()
    beam_rounds = scores['models']['beam_bf16']['tb2_1_exact_supplied_images']['rounds'].values()
    profiles = [
        ('muse_nvfp4', sum(recovery['new_terminal_by_round'].values()), recovery['new_raw_model_responses'], [PYTHON, str(ROOT / 'snapshot_live_tb.py')]),
        ('opus47', sum(value['terminal'] for value in opus_rounds), sum(value['archived_actual_model_responses'] for value in opus_rounds), [PYTHON, str(ROOT / 'snapshot_other_exact_tb.py'), 'opus47']),
        ('beam_bf16', sum(value['terminal'] for value in beam_rounds), sum(value['archived_actual_model_responses'] for value in beam_rounds), [PYTHON, str(ROOT / 'snapshot_other_exact_tb.py'), 'beam_bf16']),
    ]
    for name, terminal, raw_count, command in profiles:
        live_manifests = sorted(manifest_dir.glob(f'{name}_exact_tb_live_*.json'))
        archived_terminal = 0
        latest_archive_time = None
        latest_filename_counts = {}
        if live_manifests:
            latest = json.loads(live_manifests[-1].read_text())
            archived_terminal = latest.get('terminal_result_count', latest['filename_counts']['result'])
            latest_archive_time = datetime.fromisoformat(latest['generated_utc'])
            latest_filename_counts = latest['filename_counts']
        handoff_newer = False
        if name == 'muse_nvfp4':
            handoff_path = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867/r1-b06-b07-handoff.json'
            expected_receipts = 0
            if handoff_path.exists():
                expected_receipts += 1
                handoff_time = datetime.fromtimestamp(json.loads(handoff_path.read_text())['utc'], timezone.utc)
                handoff_newer = (latest_archive_time is None or handoff_time > latest_archive_time
                                 or latest_filename_counts.get('handoff_receipt', 0) < expected_receipts)
            route_allocations = set()
            for batch in ('b03', 'b05'):
                route = BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu/r1-{batch}-extra-route.json'
                if route.exists():
                    expected_receipts += 1
                    route_value = json.loads(route.read_text())
                    route_allocations.add(route_value['allocation'])
                    route_time = datetime.fromtimestamp(route_value['utc'], timezone.utc)
                    handoff_newer |= latest_archive_time is None or route_time > latest_archive_time
            future_routes = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/future-routes'
            for route in future_routes.glob('r[23]-completion-2866-b*-route.json'):
                value = json.loads(route.read_text())
                route_allocations.add(value['allocation'])
                original_stem = Path(value['original_config']).stem
                related = [route,
                           BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/{original_stem}-extra-owner.json',
                           BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/{original_stem}-extra-exit.json']
                for marker in related:
                    if marker.exists():
                        expected_receipts += 1
                        marker_time = datetime.fromtimestamp(json.loads(marker.read_text())['utc'], timezone.utc)
                        handoff_newer |= latest_archive_time is None or marker_time > latest_archive_time
            for name in ('r1-b05-early-owner.json', 'r1-b05-early-exit.json', 'r1-b05-normal-started.json'):
                marker = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/extra_gpu' / name
                if marker.exists():
                    expected_receipts += 1
                    marker_time = datetime.fromtimestamp(json.loads(marker.read_text())['utc'], timezone.utc)
                    handoff_newer |= latest_archive_time is None or marker_time > latest_archive_time
            handoff_newer |= latest_filename_counts.get('handoff_receipt', 0) < expected_receipts
            handoff_newer |= latest_filename_counts.get('ready_proof', 0) < len(route_allocations)
        raw_snapshot_due = (latest_archive_time is not None and raw_count > latest_filename_counts.get('raw_response', 0)
                            and (datetime.now(timezone.utc) - latest_archive_time).total_seconds() >= 900)
        if terminal > archived_terminal or handoff_newer or raw_snapshot_due:
            run(command, timeout=300)
    for group in ('opus47_legacy', 'beam_legacy', 'muse_bf16'):
        previous = sorted([manifest_dir / f'{group}.json', *manifest_dir.glob(f'{group}_delta_*.json')])[-1]
        previous_time = datetime.fromisoformat(json.loads(previous.read_text())['generated_utc'])
        if (datetime.now(timezone.utc) - previous_time).total_seconds() >= 900 or (group == 'muse_bf16' and force_bf16):
            run([PYTHON, str(ROOT / 'archive_delta.py'), group, '--if-changed'], timeout=600)
    live_manifests = sorted(manifest_dir.glob('*_exact_tb_live_*.json'))
    delta_manifests = sorted(manifest_dir.glob('*_delta_*.json'))
    release = json.loads(subprocess.check_output([
        'gh', 'api', 'repos/zhiyuanhubj/agent-benchmark-evals-20261019/releases/tags/2026-10-19-snapshot'
    ], cwd=ROOT, text=True, timeout=60))
    remote = {asset['name'] for asset in release['assets']}
    for manifest_path in [*live_manifests, *delta_manifests]:
        manifest = json.loads(manifest_path.read_text())
        archive_name = manifest['archive_name']
        if archive_name not in remote:
            archive = ROOT / '.release_assets' / archive_name
            assert archive.is_file(), f'Missing local archive for GitHub upload: {archive_name}'
            run(['gh', 'release', 'upload', '2026-10-19-snapshot', str(archive), '--repo', 'zhiyuanhubj/agent-benchmark-evals-20261019'], timeout=300)
    run([PYTHON, str(ROOT / 'verify_release.py')], timeout=120)


def cycle():
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for source in SOURCES:
            run([PYTHON, str(source)])
        force_bf16 = False
        for attempt in range(3):
            if attempt:
                for source in SOURCES:
                    run([PYTHON, str(source)])
            run([PYTHON, str(ROOT / 'export_snapshot.py')])
            scores = json.loads((ROOT / 'results/scores.json').read_text())
            run([PYTHON, str(ROOT / 'audit_muse_exact_round1.py')], timeout=180)
            audit = json.loads((ROOT / 'evidence/muse_nvfp4_exact_round1_audit.json').read_text())
            reported = scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['1']
            assert not audit['errors'], 'Muse NVFP4 exact TB task audit failed'
            if (audit['graded_task_count'], audit['success_count']) != (reported['graded'], reported['success']):
                continue  # A trial finished between the score snapshot and task audit.
            sync_native_archives(scores, force_bf16=force_bf16)
            force_bf16 = False
            run([PYTHON, str(ROOT / 'verify_muse_exact_io.py')], timeout=180)
            io_coverage = json.loads((ROOT / 'evidence/muse_nvfp4_exact_io_coverage.json').read_text())
            if io_coverage['errors']:
                continue  # A trial finished after archive creation; capture it on the next pass.
            bf16_check = subprocess.run([PYTHON, str(ROOT / 'verify_muse_bf16_exact_io.py')], cwd=ROOT,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=180)
            bf16_coverage = json.loads((ROOT / 'evidence/muse_bf16_exact_io_coverage.json').read_text())
            if bf16_check.returncode or bf16_coverage['errors']:
                force_bf16 = True
                continue
            run([PYTHON, str(ROOT / 'export_snapshot.py')])
            scores = json.loads((ROOT / 'results/scores.json').read_text())
            run([PYTHON, str(ROOT / 'audit_muse_exact_round1.py')], timeout=180)
            audit = json.loads((ROOT / 'evidence/muse_nvfp4_exact_round1_audit.json').read_text())
            reported = scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['1']
            assert not audit['errors'], 'Muse NVFP4 exact TB task audit failed'
            run([PYTHON, str(ROOT / 'verify_muse_exact_io.py')], timeout=180)
            io_coverage = json.loads((ROOT / 'evidence/muse_nvfp4_exact_io_coverage.json').read_text())
            if (audit['graded_task_count'], audit['success_count']) != (reported['graded'], reported['success']) or io_coverage['errors']:
                continue
            bf16_check = subprocess.run([PYTHON, str(ROOT / 'verify_muse_bf16_exact_io.py')], cwd=ROOT,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=180)
            bf16_coverage = json.loads((ROOT / 'evidence/muse_bf16_exact_io_coverage.json').read_text())
            if bf16_check.returncode or bf16_coverage['errors']:
                force_bf16 = True
                continue
            if reported['complete']:
                assert audit['qualification'] == 'complete_verified', 'Muse NVFP4 exact TB first-round audit failed'
                assert io_coverage['qualification'] == 'complete_verified', 'Muse NVFP4 exact TB release coverage incomplete'
            break
        else:
            raise RuntimeError('Exact TB result or released I/O changed during three snapshot attempts; retry next cycle')
        run([PYTHON, str(ROOT / 'audit_other_exact_round1.py')], timeout=180)
        for model in ('opus47', 'beam_bf16'):
            other_audit = json.loads((ROOT / f'evidence/{model}_exact_round1_audit.json').read_text())
            assert not other_audit['errors'], f'{model} exact TB released I/O audit failed'
            other_reported = scores['models']['opus_4_7' if model == 'opus47' else 'beam_bf16']['tb2_1_exact_supplied_images']['rounds']['1']
            if other_reported['complete']:
                assert other_audit['qualification'] == 'complete_verified', f'{model} exact TB first round not verified'
                assert (other_audit['graded'], other_audit['success']) == (other_reported['graded'], other_reported['success'])
        run([PYTHON, str(ROOT / 'screen_exact_tb_integrity.py')], timeout=180)
        screen = json.loads((ROOT / 'evidence/exact_tb_integrity_screen.json').read_text())
        screened = {(row['model'], row['task']): row for row in screen['records']}
        manual_notes = json.loads((ROOT / 'evidence/exact_tb_integrity_manual_notes.json').read_text())
        for note in manual_notes['notes']:
            row = screened[(note['model'], note['task'])]
            assert row['trajectory_sha256'] == note['trajectory_sha256'], 'Manual trajectory review anchor changed'
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
