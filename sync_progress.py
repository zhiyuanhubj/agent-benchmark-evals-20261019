#!/usr/bin/env python3
"""Refresh qualified benchmark scores and publish a private GitHub snapshot."""
import fcntl
import hashlib
import json
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from release_shards import MAX_ASSETS_PER_RELEASE, REPO, release_assets, tag_for_part

ROOT = Path(__file__).resolve().parent
BASE = Path('/fsx/home/zhiyuan')
PYTHON = str(BASE / 'AgentCompass/.venv/bin/python')
SOURCES = [
    BASE / '.private/beam_20261018/expanded_status.py',
    BASE / '.private/beam_20261018/status.py',
    BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/status.py',
    BASE / '.private/muse_spark_open_20261016/review_bench_20261018/status.py',
    BASE / '.private/muse_bf16_20261018/status.py',
]
LOG = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/github-sync-20261019.jsonl'
LOCK = LOG.with_suffix('.lock')
RAW_ARCHIVE_INTERVAL_SECONDS = 600  # Keep live I/O snapshots within each 15-minute sync cycle.
# These original runs have finished and their controllers are stopped. Scan
# their large legacy trees every six hours; the active review-revision trees
# below keep the ten-minute cadence so new trajectories reach the release promptly.
STATIC_ARCHIVE_INTERVAL_SECONDS = 21600
STATIC_ARCHIVE_GROUPS = {'opus47_legacy', 'opus47_review_inputs',
                         'muse_review_full_io', 'muse_review_verifier',
                         'beam_review_full_io', 'beam_review_verifier'}
ARCHIVE_SCAN_STATE = LOG.with_name('github-archive-scan-state.json')


def run(command, timeout=180):
    try:
        return subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True, timeout=timeout, check=True)
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f'Command failed ({error.returncode}): {command}; '
                           f'stderr tail: {(error.stderr or "")[-4000:]}') from error


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
        if name == 'muse_nvfp4':
            replacement_names = [f'muse-nvfp4-tb-v1-exact-r2-infra-replacement-{task}'
                                 for task in ('password-recovery', 'prove-plus-comm')]
            replacement_names.append('muse-nvfp4-tb-v1-exact-r2-infra-transport-correction-prove-plus-comm')
            replacement_names.append('muse-nvfp4-tb-v1-exact-r2-storage-replacement-pytorch-model-cli')
            replacement_names.append('muse-nvfp4-tb-v1-exact-r2-connection-recovery-20261020')
            replacement_names.append('muse-nvfp4-tb-v1-exact-r2-expiry-correction-2902-20261020')
            replacement_names.extend((
                'muse-nvfp4-tb-v1-exact-r2-fasttext-expiry-2902-20261020',
                'muse-nvfp4-tb-v1-exact-r2-fasttext-tmux-2902-20261020',
                'muse-nvfp4-tb-v1-exact-r3-expired2869-continuation-2900-20261020',
            ))
            for job_name in replacement_names:
                replacement = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4' / job_name
                if replacement.exists():
                    terminal += sum(bool(json.loads(path.read_text()).get('finished_at'))
                                    for path in replacement.glob('*/result.json'))
                    raw_count += sum(1 for _ in replacement.glob('*/agent/raw_responses/*.json'))
            for replacement in (BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4').glob(
                    'muse-nvfp4-tb-v1-exact-r3-infra-replacement-2900-b*'):
                terminal += sum(bool(json.loads(path.read_text()).get('finished_at'))
                                for path in replacement.glob('*/result.json'))
                raw_count += sum(1 for _ in replacement.glob('*/agent/raw_responses/*.json'))
        if name == 'beam_bf16':
            replacement = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/beam_bf16/beam-tb-v1-exact-r2-infra-replacement-git-multibranch'
            if replacement.exists():
                terminal += sum(bool(json.loads(path.read_text()).get('finished_at')) for path in replacement.glob('*/result.json'))
                raw_count += sum(1 for _ in replacement.glob('*/agent/raw_responses/*.json'))
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
        scored_result_newer = False
        if name == 'muse_nvfp4':
            # A result can land after snapshot_live_tb collected its file list
            # but before it wrote the manifest. Compare with the archive's
            # start stamp, and only require results in this score snapshot.
            archive_started = None
            if live_manifests:
                stamp = live_manifests[-1].stem.rsplit('_live_', 1)[1]
                archive_started = datetime.strptime(stamp, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
            scored_cutoff = datetime.fromisoformat(
                scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images'].get(
                    'native_score_snapshot_utc', scores['generated_utc']))
            result_root = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/results/muse_nvfp4'
            scored_result_newer = any(
                archive_started is None or archive_started.timestamp() < path.stat().st_mtime <= scored_cutoff.timestamp()
                for path in result_root.glob('*/*/result.json'))
            r3_state = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r3-infra-replacement-2900'
            if (r3_state / 'plan.json').exists():
                markers = [r3_state / 'plan.json', *r3_state.glob('b*-started.json'),
                           *r3_state.glob('b*-exit.json'),
                           *r3_state.glob('b*-continuation.json'),
                           *r3_state.glob('expired2869-continuation-2900-*.json')]
                ready_2900 = r3_state.parent / 'replica-2900/endpoint-ready.json'
                if ready_2900.exists():
                    markers.append(ready_2900)
                handoff_newer |= latest_filename_counts.get('controller_source', 0) < 1
                handoff_newer |= any(latest_archive_time is None or
                                     datetime.fromtimestamp(marker.stat().st_mtime, timezone.utc) > latest_archive_time
                                     for marker in markers)
                extra_routes = r3_state / 'extra-routes-20261020'
                route_markers = [*extra_routes.glob('b*.json')]
                replica_root = r3_state.parent / 'replicas-extra-20261020'
                for allocation in (2869, 2899):
                    route_markers.extend(path for path in
                                         (replica_root / str(allocation) / 'serve-launch.json',
                                          replica_root / str(allocation) / 'endpoint-ready.json',
                                          replica_root / str(allocation) / 'reasoning-preflight.json')
                                         if path.exists())
                handoff_newer |= any(latest_archive_time is None or
                                     datetime.fromtimestamp(marker.stat().st_mtime, timezone.utc) > latest_archive_time
                                     for marker in route_markers)
            handoff_path = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/reassigned-2867/r1-b06-b07-handoff.json'
            expected_receipts = 0
            for task in ('password-recovery', 'prove-plus-comm'):
                replacement_claim = BASE / f'.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-{task}-infra-replacement-claim.json'
                if replacement_claim.exists():
                    expected_receipts += 1
                    handoff_newer |= (latest_archive_time is None or
                                     datetime.fromtimestamp(replacement_claim.stat().st_mtime, timezone.utc) > latest_archive_time)
            transport_claim = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-prove-plus-comm-transport-correction-claim.json'
            if transport_claim.exists():
                expected_receipts += 1
                handoff_newer |= (latest_archive_time is None or
                                 datetime.fromtimestamp(transport_claim.stat().st_mtime, timezone.utc) > latest_archive_time)
            storage_claim = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-pytorch-model-cli-storage-replacement-claim.json'
            if storage_claim.exists():
                expected_receipts += 1
                handoff_newer |= (latest_archive_time is None or
                                 datetime.fromtimestamp(storage_claim.stat().st_mtime, timezone.utc) > latest_archive_time)
            connection_claim = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-connection-recovery-20261020-claim.json'
            if connection_claim.exists():
                expected_receipts += 1
                handoff_newer |= (latest_archive_time is None or
                                 datetime.fromtimestamp(connection_claim.stat().st_mtime, timezone.utc) > latest_archive_time)
            expiry_claim = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/muse_nvfp4/state/r2-expiry-correction-2902-20261020-claim.json'
            if expiry_claim.exists():
                expected_receipts += 1
                handoff_newer |= (latest_archive_time is None or
                                 datetime.fromtimestamp(expiry_claim.stat().st_mtime, timezone.utc) > latest_archive_time)
                replica_2902 = expiry_claim.parent / 'replicas-extra-20261020/2902'
                for marker in ('handoff-from-expired-2867.json', 'endpoint-ready.json', 'reasoning-preflight.json'):
                    path = replica_2902 / marker
                    if path.exists():
                        handoff_newer |= (latest_archive_time is None or
                                         datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) > latest_archive_time)
            for label in ('fasttext-expiry', 'fasttext-tmux'):
                claim = BASE / ('.private/beam_20261018/tb_v1_exact_images_20261019/'
                                f'muse_nvfp4/state/r2-{label}-2902-20261020-claim.json')
                if claim.exists():
                    expected_receipts += 1
                    handoff_newer |= (latest_archive_time is None or
                                     datetime.fromtimestamp(claim.stat().st_mtime, timezone.utc) > latest_archive_time)
            if handoff_path.exists():
                expected_receipts += 1
                handoff_time = datetime.fromtimestamp(json.loads(handoff_path.read_text())['utc'], timezone.utc)
                handoff_newer |= (latest_archive_time is None or handoff_time > latest_archive_time
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
        if name == 'beam_bf16':
            receipt_dir = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019/beam/state'
            receipts = [receipt_dir / marker for marker in
                        ('r23-2887-handoff.json', 'r2-launch.json', 'r3-launch.json',
                         'r2-exit.json', 'r3-exit.json',
                         'r2-git-multibranch-infra-replacement-claim.json',
                         'r2-git-multibranch-infra-replacement-exit.json')]
            receipts = [marker for marker in receipts if marker.exists()]
            handoff_newer |= latest_filename_counts.get('handoff_receipt', 0) < len(receipts)
            handoff_newer |= any(latest_archive_time is None or
                                 datetime.fromtimestamp(marker.stat().st_mtime, timezone.utc) > latest_archive_time
                                 for marker in receipts)
        raw_snapshot_due = (latest_archive_time is not None and raw_count > latest_filename_counts.get('raw_response', 0)
                            and (datetime.now(timezone.utc) - latest_archive_time).total_seconds() >= RAW_ARCHIVE_INTERVAL_SECONDS)
        if terminal > archived_terminal or handoff_newer or raw_snapshot_due or scored_result_newer:
            run(command, timeout=300)
    static_scans = json.loads(ARCHIVE_SCAN_STATE.read_text()) if ARCHIVE_SCAN_STATE.exists() else {}
    for group in ('opus47_legacy', 'beam_legacy', 'muse_bf16', 'muse_bf16_swr',
                  'opus47_review_inputs', 'opus47_review_full_io',
                  'muse_bf16_review_inputs',
                  'muse_review_full_io', 'beam_review_full_io',
                  'muse_review_verifier', 'beam_review_verifier',
                  'muse_review_revision_inputs', 'beam_review_revision_inputs',
                  'muse_revision_review_full_io', 'beam_revision_review_full_io'):
        if not (manifest_dir / f'{group}.json').exists():
            continue  # A new archive group joins only after its base asset is created.
        previous = sorted([manifest_dir / f'{group}.json', *manifest_dir.glob(f'{group}_delta_*.json')])[-1]
        previous_time = datetime.fromisoformat(json.loads(previous.read_text())['generated_utc'])
        # The Opus provider archive shares the legacy root. While the resumed
        # SWE-Review job is generating new requests, publish its raw streamed
        # replies on the live cadence instead of the completed-run cadence.
        opus_review_live = group == 'opus47_legacy' and any(
            subprocess.run(['systemctl', '--user', 'is-active', '--quiet', unit]).returncode == 0
            for unit in ('opus47-swe-review-glm-r1-2887-retry1-20261020.service',
                         'opus47-swe-review-coder-r1-2887-retry1-20261020.service',
                         'opus47-swe-review-instruct-r1-2887-retry1-20261020.service'))
        static = group in STATIC_ARCHIVE_GROUPS and not opus_review_live
        if static and '--live-only' in sys.argv:
            # Publish fresh live results first; the normal daemon keeps the
            # completed benchmark roots on their independent periodic scan.
            continue
        if group == 'opus47_legacy' and '--live-only' in sys.argv:
            # A verified provider-stream snapshot was prepared just before
            # this fast publish. The normal daemon will capture later events.
            assert previous_time >= datetime.fromisoformat('2026-10-20T22:13:07+00:00')
            snapshot = json.loads(previous.read_text())
            asset = ROOT / '.release_assets' / snapshot['archive_name']
            assert asset.is_file() and asset.stat().st_size == snapshot['archive_size_bytes']
            with asset.open('rb') as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == snapshot['archive_sha256']
            continue
        if static and group in static_scans:
            previous_time = max(previous_time, datetime.fromisoformat(static_scans[group]))
        interval = STATIC_ARCHIVE_INTERVAL_SECONDS if static else RAW_ARCHIVE_INTERVAL_SECONDS
        if (datetime.now(timezone.utc) - previous_time).total_seconds() >= interval or (group == 'muse_bf16' and force_bf16):
            run([PYTHON, str(ROOT / 'archive_delta.py'), group, '--if-changed'], timeout=600)
            if static:
                static_scans[group] = datetime.now(timezone.utc).isoformat()
                temp = ARCHIVE_SCAN_STATE.with_suffix('.tmp')
                temp.write_text(json.dumps(static_scans, indent=2) + '\n')
                temp.replace(ARCHIVE_SCAN_STATE)
    live_manifests = sorted(manifest_dir.glob('*_exact_tb_live_*.json'))
    delta_manifests = sorted(manifest_dir.glob('*_delta_*.json'))
    releases = release_assets()
    remote = {asset['name'] for _, assets in releases for asset in assets}
    assert len(remote) == sum(len(assets) for _, assets in releases), 'Duplicate archive name across releases'
    revision_base_manifests = [manifest_dir / f'{group}.json' for group in
        ('opus47_review_inputs', 'opus47_review_full_io',
         'muse_review_revision_inputs', 'beam_review_revision_inputs',
         'muse_revision_review_full_io', 'beam_revision_review_full_io')]
    revision_base_manifests = [path for path in revision_base_manifests if path.exists()]
    for manifest_path in [*revision_base_manifests, *live_manifests, *delta_manifests]:
        manifest = json.loads(manifest_path.read_text())
        archive_name = manifest['archive_name']
        if archive_name not in remote:
            archive = ROOT / '.release_assets' / archive_name
            assert archive.is_file(), f'Missing local archive for GitHub upload: {archive_name}'
            if len(releases[-1][1]) >= MAX_ASSETS_PER_RELEASE:
                next_tag = tag_for_part(len(releases) + 1)
                run(['gh', 'release', 'create', next_tag, '--repo', REPO, '--target', 'main',
                     '--title', f'Benchmark native I/O archives, part {len(releases) + 1}',
                     '--notes', 'Continuation of the private benchmark input/output archive. '
                     'Match each asset to its SHA-256 manifest in the repository.'], timeout=120)
                releases.append((next_tag, []))
            tag, assets = releases[-1]
            run(['gh', 'release', 'upload', tag, str(archive), '--repo', REPO], timeout=300)
            assets.append({'name': archive_name})
            remote.add(archive_name)
    run([PYTHON, str(ROOT / 'verify_release.py')], timeout=120)
    if (manifest_dir / 'muse_review_revision_inputs.json').exists():
        run([PYTHON, str(ROOT / 'verify_review_revision_archives.py')], timeout=120)


def cycle():
    with LOCK.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for source in SOURCES:
            run([PYTHON, str(source)], timeout=600)
        run([PYTHON, str(ROOT / 'audit_muse_bf16_expiry_recovery.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_swe_review_da.py')], timeout=180)
        run([PYTHON, str(ROOT / 'audit_muse_review_revision_v2.py')], timeout=180)
        run([PYTHON, str(ROOT / 'audit_review_revision_gateway.py')], timeout=180)
        run([PYTHON, str(ROOT / 'audit_swe_review_recovery.py')], timeout=180)
        run([PYTHON, str(ROOT / 'audit_beam_malformed_reviews.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_bf16_swr_alignment.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_bf16_review_progress.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_opus47_review_progress.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_ungraded.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_prove_ungraded.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_prove_transport.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_password_replacement_integrity.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_local2866.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_pytorch_ungraded.py')], timeout=60)
        run([PYTHON, str(ROOT / 'audit_muse_nvfp4_r2_pytorch_replacement.py')], timeout=60)
        force_bf16 = False
        for attempt in range(3):
            if attempt:
                for source in SOURCES:
                    run([PYTHON, str(source)], timeout=600)
                run([PYTHON, str(ROOT / 'audit_muse_bf16_expiry_recovery.py')], timeout=60)
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
            run([PYTHON, str(ROOT / 'audit_swe_review_official_rrr.py')], timeout=180)
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
        for round_number in ('2', '3'):
            run([PYTHON, str(ROOT / 'audit_other_exact_round1.py'), '--model', 'opus47',
                 '--round', round_number], timeout=180)
            other_audit = json.loads((ROOT / f'evidence/opus47_exact_round{round_number}_audit.json').read_text())
            assert not other_audit['errors'], f'Opus exact TB round {round_number} released I/O audit failed'
            other_reported = scores['models']['opus_4_7']['tb2_1_exact_supplied_images']['rounds'][round_number]
            if other_reported['complete']:
                assert other_audit['qualification'] == 'complete_verified', f'Opus exact TB round {round_number} not verified'
                assert (other_audit['graded'], other_audit['success']) == (other_reported['graded'], other_reported['success'])
        for round_number in ('2', '3'):
            beam_reported = scores['models']['beam_bf16']['tb2_1_exact_supplied_images']['rounds'][round_number]
            if not beam_reported['terminal']:
                continue
            run([PYTHON, str(ROOT / 'audit_other_exact_round1.py'), '--model', 'beam_bf16',
                 '--round', round_number], timeout=180)
            beam_audit = json.loads((ROOT / f'evidence/beam_bf16_exact_round{round_number}_audit.json').read_text())
            assert not beam_audit['errors'], f'Beam exact TB round {round_number} released I/O audit failed'
            if beam_reported['complete']:
                assert beam_audit['qualification'] == 'complete_verified', f'Beam exact TB round {round_number} not verified'
                assert (beam_audit['graded'], beam_audit['success']) == (beam_reported['graded'], beam_reported['success'])
        run([PYTHON, str(ROOT / 'screen_exact_tb_integrity.py')], timeout=180)
        screen = json.loads((ROOT / 'evidence/exact_tb_integrity_screen.json').read_text())
        scored_rounds = (
            ('muse_nvfp4_r2', scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['2']['graded']),
            ('muse_nvfp4_r3', scores['models']['muse_nvfp4']['tb2_1_exact_supplied_images']['rounds']['3']['graded']),
            ('beam_bf16_r2', scores['models']['beam_bf16']['tb2_1_exact_supplied_images']['rounds']['2']['graded']),
            ('beam_bf16_r3', scores['models']['beam_bf16']['tb2_1_exact_supplied_images']['rounds']['3']['graded']),
        )
        for model, graded in scored_rounds:
            screened = sum(row['model'] == model for row in screen['records'])
            missing = sum(row['model'] == model for row in screen['missing_trajectories'])
            assert screened + missing >= graded, f'{model} integrity screen missed graded trajectories'
        screened = {(row['model'], row['task']): row for row in screen['records']}
        manual_notes = json.loads((ROOT / 'evidence/exact_tb_integrity_manual_notes.json').read_text())
        for note in manual_notes['notes']:
            row = screened[(note['model'], note['task'])]
            assert row['trajectory_sha256'] == note['trajectory_sha256'], 'Manual trajectory review anchor changed'
        run(['git', 'add', 'README.md', 'REPORT.zh-CN.md', 'results/scores.json', 'evidence',
             'input_output/manifest.json', 'input_output/archive_manifests',
             'audit_swe_review_native_complete_da.py', 'review_native_selection.py',
             'audit_beam_malformed_reviews.py', 'audit_swe_review_da.py',
             'audit_muse_bf16_review_progress.py',
             'audit_muse_bf16_tb_ungraded.py',
             'audit_opus47_review_progress.py',
             'audit_other_exact_round1.py',
             'audit_muse_bf16_expiry_recovery.py', 'publish_muse_bf16_interrupted_io.py',
             'protocol/expanded_status_20261019.py',
             'protocol/muse_bf16_status_20261020.py',
             'protocol/prepare_muse_bf16_direct_resume_20261020.py',
             'protocol/prepare_muse_bf16_deep_endpoint_recovery_20261020.py',
             'protocol/prepare_muse_bf16_deep_client_retry_20261020.py',
             'protocol/prepare_muse_bf16_tb_pre_model_recovery_20261020.py',
             'protocol/muse_bf16_client_dependency.py',
             'protocol/run_muse_bf16_pro_direct_resume_20261020.py',
             'protocol/prune_2919_completed_beam_pro_images_20261020.py',
             'protocol/prune_2922_completed_muse_pro_images_20261020.py',
             'protocol/run_beam_pro_r2_2888_20261020.py',
             'protocol/prepare_opus47_review_resume_20261020.py',
             'beam_exact_round3_2901.py',
             'audit_muse_nvfp4_r2_ungraded.py',
             'prepare_muse_nvfp4_r2_password_replacement.py',
             'prepare_muse_nvfp4_r2_connection_recovery.py',
             'protocol/prepare_muse_nvfp4_r2_expiry_correction_20261020.py',
             'protocol/run_muse_nvfp4_r2_expiry_correction_20261020.py',
             'protocol/prepare_muse_nvfp4_r2_fasttext_expiry_20261020.py',
             'protocol/run_muse_nvfp4_r2_fasttext_expiry_20261020.py',
             'protocol/preinstalled_tmux_isolated_docker.py',
             'protocol/probe_muse_nvfp4_fasttext_tmux_20261020.py',
             'protocol/prepare_muse_nvfp4_r2_fasttext_tmux_20261020.py',
             'protocol/run_muse_nvfp4_r2_fasttext_tmux_20261020.py',
             'audit_muse_nvfp4_r2_prove_ungraded.py',
             'prepare_muse_nvfp4_r2_prove_replacement.py',
             'audit_muse_nvfp4_r2_prove_transport.py',
             'prepare_muse_nvfp4_r2_prove_transport_correction.py',
             'audit_muse_nvfp4_r2_password_replacement_integrity.py',
             'audit_muse_nvfp4_local2866.py',
             'prepare_muse_nvfp4_local2866.py',
             'protocol/muse_nvfp4_local2866',
             'protocol/serve_muse_nvfp4_extra_20261020.py',
             'protocol/prepare_muse_nvfp4_r3_extra_routes_20261020.py',
             'protocol/preflight_muse_nvfp4_extra_20261020.py',
             'protocol/run_muse_nvfp4_r3_extra_routes_20261020.py',
             'protocol/continue_muse_nvfp4_r3_b07_2900_20261020.py',
             'protocol/continue_muse_nvfp4_r3_expired2869_2900_20261020.py',
             'protocol/muse_nvfp4_exact_future_round_controller_20261019.py',
             'audit_muse_nvfp4_r2_pytorch_ungraded.py',
             'audit_muse_nvfp4_r2_pytorch_replacement.py',
             'prepare_muse_nvfp4_r2_pytorch_replacement.py',
             'audit_swe_review_official_rrr.py',
             'audit_muse_review_revision_v2.py', 'audit_review_revision_gateway.py',
             'protocol/beam_review_revision_v2', 'protocol/muse_review_revision_v2',
             'export_snapshot.py', 'snapshot_live_tb.py', 'snapshot_other_exact_tb.py',
             'screen_exact_tb_integrity.py',
             'verify_muse_exact_io.py',
             'verify_muse_bf16_exact_io.py',
             'archive_trials.py', 'archive_delta.py',
             'verify_review_revision_archives.py', 'release_shards.py', 'verify_release.py', 'sync_progress.py'])
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
            'live_only': '--live-only' in sys.argv,
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
