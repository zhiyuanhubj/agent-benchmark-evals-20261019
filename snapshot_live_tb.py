#!/usr/bin/env python3
"""Archive stable input/output JSON from live Muse NVFP4 exact-image TB batches."""
import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
RESULTS = SOURCE / 'results/muse_nvfp4'
CONFIGS = SOURCE / 'muse_nvfp4/configs'
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
name = f'muse_nvfp4_exact_tb_live_{stamp}'
archive = ROOT / '.release_assets' / f'{name}.tar.zst'
temp = archive.with_suffix(archive.suffix + '.tmp')
archive.parent.mkdir(exist_ok=True)
assert not archive.exists()

payloads = {}
counts = {'job_config': 0, 'handoff_receipt': 0, 'ready_proof': 0, 'controller_source': 0, 'task_input': 0, 'trial_config': 0, 'trajectory': 0, 'raw_response': 0, 'result': 0}
terminal_results = 0
replacement_jobs = [RESULTS / f'muse-nvfp4-tb-v1-exact-r2-infra-replacement-{task}'
                    for task in ('password-recovery', 'prove-plus-comm')]
transport_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-infra-transport-correction-prove-plus-comm'
storage_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-storage-replacement-pytorch-model-cli'
connection_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-connection-recovery-20261020'
expiry_correction_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-expiry-correction-2902-20261020'
fasttext_expiry_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-fasttext-expiry-2902-20261020'
fasttext_tmux_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r2-fasttext-tmux-2902-20261020'
expired2869_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r3-expired2869-continuation-2900-20261020'
r4_job = RESULTS / 'muse-nvfp4-tb-v1-exact-r4-2902-20261021'
jobs = list(RESULTS.glob('muse-nvfp4-tb-v1-exact-r*-completion-2866-b*'))
jobs.extend(RESULTS.glob('muse-nvfp4-tb-v1-exact-r3-infra-replacement-2900-b*'))
if expired2869_job.exists():
    jobs.append(expired2869_job)
if r4_job.exists():
    jobs.append(r4_job)
jobs.extend(job for job in replacement_jobs if job.exists())
if transport_job.exists():
    jobs.append(transport_job)
if storage_job.exists():
    jobs.append(storage_job)
if connection_job.exists():
    jobs.append(connection_job)
if expiry_correction_job.exists():
    jobs.append(expiry_correction_job)
for job in (fasttext_expiry_job, fasttext_tmux_job):
    if job.exists():
        jobs.append(job)
for job in sorted(jobs):
    config = CONFIGS / (job.name.replace('muse-nvfp4-tb-v1-exact-', '') + '.json')
    if config.exists():
        payloads[config] = config.read_bytes()
        counts['job_config'] += 1
    if job.name.endswith(('-b06', '-b07')):
        effective = CONFIGS / f'r1-handoff-2867-{job.name[-3:]}.json'
        if effective.exists():
            payloads[effective] = effective.read_bytes()
            counts['job_config'] += 1
    for trial in sorted(job.iterdir()):
        if not trial.is_dir():
            continue
        for category, path in [('trial_config', trial / 'config.json'), ('trajectory', trial / 'agent/trajectory.json'), ('result', trial / 'result.json')]:
            if path.exists() and path.is_file() and not path.is_symlink():
                data = path.read_bytes()
                try:
                    parsed = json.loads(data)
                except json.JSONDecodeError:
                    if category == 'trajectory':
                        continue  # Active trajectories may be rewritten mid-snapshot.
                    raise
                payloads[path] = data
                counts[category] += 1
                if category == 'result' and parsed.get('finished_at'):
                    terminal_results += 1
        for path in sorted((trial / 'agent/raw_responses').glob('*.json')):
            data = path.read_bytes()
            json.loads(data)
            payloads[path] = data
            counts['raw_response'] += 1
        cfg = trial / 'config.json'
        if cfg.exists():
            task = json.loads(cfg.read_text())['task']['path']
            task_file = Path(task) / 'task.toml'
            if task_file.exists() and task_file not in payloads:
                payloads[task_file] = task_file.read_bytes()
                counts['task_input'] += 1
r4_state = SOURCE / 'muse_nvfp4/state/r4-2902-20261021'
r4_claim_path = r4_state / 'claim.json'
if r4_claim_path.exists():
    claim = json.loads(r4_claim_path.read_text())
    assert claim['round'] == 4 and claim['expected'] == 89 and claim['allocation'] == 2902
    config = Path(claim['config'])
    assert hashlib.sha256(config.read_bytes()).hexdigest() == claim['config_sha256']
    required = [r4_claim_path, config, Path(claim['endpoint_ready']),
                Path(claim['reasoning_preflight']), Path(claim['runner'])]
    for suffix in ('started', 'exit'):
        marker = r4_state / f'{suffix}.json'
        if marker.exists():
            required.append(marker)
    for path in required:
        assert path.is_file()
        if path not in payloads:
            payloads[path] = path.read_bytes()
            category = ('job_config' if path == config else
                        'controller_source' if path == Path(claim['runner']) else
                        'ready_proof' if path in (Path(claim['endpoint_ready']), Path(claim['reasoning_preflight'])) else
                        'handoff_receipt')
            counts[category] += 1
r3_state = SOURCE / 'muse_nvfp4/state/r3-infra-replacement-2900'
r3_plan = r3_state / 'plan.json'
if r3_plan.exists():
    plan = json.loads(r3_plan.read_text())
    assert plan['expected_tasks'] == 89 and len(plan['batches']) == 9
    payloads[r3_plan] = r3_plan.read_bytes()
    counts['handoff_receipt'] += 1
    script = SOURCE / 'muse_nvfp4/recover_r3_2900.py'
    payloads[script] = script.read_bytes()
    counts['controller_source'] += 1
    for batch in plan['batches']:
        for item in batch['tasks']:
            original_result = Path(item['original_result'])
            assert hashlib.sha256(original_result.read_bytes()).hexdigest() == item['original_result_sha256']
        effective = Path(batch['effective_config'])
        assert hashlib.sha256(effective.read_bytes()).hexdigest() == batch['effective_config_sha256']
        if effective not in payloads:
            payloads[effective] = effective.read_bytes()
            counts['job_config'] += 1
        for suffix in ('started', 'exit'):
            marker = r3_state / f'b{batch["index"]:02}-{suffix}.json'
            if marker.exists():
                payloads[marker] = marker.read_bytes()
                counts['handoff_receipt'] += 1
    ready = r3_state.parent / 'replica-2900/endpoint-ready.json'
    if ready.exists():
        payloads[ready] = ready.read_bytes()
        counts['ready_proof'] += 1
    routes = r3_state / 'extra-routes-20261020'
    for receipt_path in sorted(routes.glob('b[0-9][0-9].json')):
        receipt = json.loads(receipt_path.read_text())
        batch = plan['batches'][receipt['batch']]
        assert receipt['job_name'] == batch['job_name']
        assert receipt['original_effective_config_sha256'] == batch['effective_config_sha256']
        assert hashlib.sha256(Path(receipt['original_plan']).read_bytes()).hexdigest() == receipt['original_plan_sha256']
        routed = Path(receipt['routed_config'])
        assert hashlib.sha256(routed.read_bytes()).hexdigest() == receipt['routed_config_sha256']
        effective = json.loads(Path(batch['effective_config']).read_text())
        effective['agents'][0]['kwargs']['api_base'] = receipt['endpoint']
        assert json.loads(routed.read_text()) == effective
        assert not (r3_state / f'b{receipt["batch"]:02}-started.json').exists()
        payloads[receipt_path] = receipt_path.read_bytes()
        payloads[routed] = routed.read_bytes()
        counts['handoff_receipt'] += 1
        counts['job_config'] += 1
        for suffix in ('started', 'exit'):
            marker = routes / f'b{receipt["batch"]:02}-{suffix}.json'
            if marker.exists():
                payloads[marker] = marker.read_bytes()
                counts['handoff_receipt'] += 1
    if routes.exists():
        for script_name in ('serve_muse_nvfp4_extra_20261020.py',
                            'prepare_muse_nvfp4_r3_extra_routes_20261020.py',
                            'preflight_muse_nvfp4_extra_20261020.py',
                            'run_muse_nvfp4_r3_extra_routes_20261020.py'):
            script_path = ROOT / 'protocol' / script_name
            if script_path.exists():
                payloads[script_path] = script_path.read_bytes()
                counts['controller_source'] += 1
        replica_root = SOURCE / 'muse_nvfp4/state/replicas-extra-20261020'
        for allocation in (2869, 2899):
            proof = replica_root / str(allocation) / 'endpoint-ready.json'
            if proof.exists():
                payloads[proof] = proof.read_bytes()
                counts['ready_proof'] += 1
            launch = replica_root / str(allocation) / 'serve-launch.json'
            if launch.exists():
                payloads[launch] = launch.read_bytes()
                counts['handoff_receipt'] += 1
            preflight = replica_root / str(allocation) / 'reasoning-preflight.json'
            if preflight.exists():
                check = json.loads(preflight.read_text())
                assert check['allocation'] == allocation and check['nonempty_reasoning_content']
                assert check['response']['choices'][0]['message']['reasoning_content'].strip()
                payloads[preflight] = preflight.read_bytes()
                counts['ready_proof'] += 1
    continuation_path = r3_state / 'b07-2900-continuation.json'
    if continuation_path.exists():
        continuation = json.loads(continuation_path.read_text())
        assert continuation['batch'] == 7 and continuation['allocation'] == 2900
        assert continuation['old_allocation'] == 2869 and continuation['old_route_started'] is False
        assert hashlib.sha256(Path(continuation['preserved_old_route']).read_bytes()).hexdigest() == continuation['preserved_old_route_sha256']
        config = Path(continuation['effective_config'])
        assert hashlib.sha256(config.read_bytes()).hexdigest() == continuation['effective_config_sha256']
        assert json.loads(config.read_text()) == json.loads(Path(plan['batches'][7]['effective_config']).read_text())
        payloads[continuation_path] = continuation_path.read_bytes()
        payloads[config] = config.read_bytes()
        counts['handoff_receipt'] += 1
        counts['job_config'] += 1
        for suffix in ('started', 'exit'):
            marker = r3_state / f'b07-2900-{suffix}.json'
            if marker.exists():
                payloads[marker] = marker.read_bytes()
                counts['handoff_receipt'] += 1
        script = ROOT / 'protocol/continue_muse_nvfp4_r3_b07_2900_20261020.py'
        payloads[script] = script.read_bytes()
        counts['controller_source'] += 1
    expired_claim_path = r3_state / 'expired2869-continuation-2900-claim.json'
    if expired_claim_path.exists():
        expired_claim = json.loads(expired_claim_path.read_text())
        assert expired_claim['original_allocation_sacct'][1] == 'TIMEOUT'
        assert expired_claim['model_allocation'] == 2900
        assert len(expired_claim['tasks']) == 11
        assert sum(bool(row['source_partial_raw']) for row in expired_claim['tasks']) == 4
        config = Path(expired_claim['config'])
        assert hashlib.sha256(config.read_bytes()).hexdigest() == expired_claim['config_sha256']
        assert hashlib.sha256(Path(expired_claim['source_plan']).read_bytes()).hexdigest() == expired_claim['source_plan_sha256']
        payloads[expired_claim_path] = expired_claim_path.read_bytes()
        counts['handoff_receipt'] += 1
        if config not in payloads:
            payloads[config] = config.read_bytes()
            counts['job_config'] += 1
        for row in expired_claim['tasks']:
            assert hashlib.sha256(Path(row['original_failure_result']).read_bytes()).hexdigest() == row['original_failure_result_sha256']
            for raw in row['source_partial_raw']:
                path = Path(raw['path'])
                assert hashlib.sha256(path.read_bytes()).hexdigest() == raw['sha256']
            if row['source_partial_trajectory']:
                path = Path(row['source_partial_trajectory'])
                assert hashlib.sha256(path.read_bytes()).hexdigest() == row['source_partial_trajectory_sha256']
        for suffix in ('start', 'exit'):
            marker = r3_state / f'expired2869-continuation-2900-{suffix}.json'
            if marker.exists():
                payloads[marker] = marker.read_bytes()
                counts['handoff_receipt'] += 1
        script = ROOT / 'protocol/continue_muse_nvfp4_r3_expired2869_2900_20261020.py'
        payloads[script] = script.read_bytes()
        counts['controller_source'] += 1
handoff = SOURCE / 'muse_nvfp4/state/reassigned-2867/r1-b06-b07-handoff.json'
if handoff.exists():
    payloads[handoff] = handoff.read_bytes()
    counts['handoff_receipt'] += 1
    for row in json.loads(payloads[handoff])['batches']:
        effective = Path(row['effective_config'])
        if effective not in payloads:
            payloads[effective] = effective.read_bytes()
            counts['job_config'] += 1
for batch in ('b03', 'b05'):
    receipt_path = SOURCE / f'muse_nvfp4/state/extra_gpu/r1-{batch}-extra-route.json'
    if not receipt_path.exists():
        continue
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt['batch'] == batch and receipt['allocation'] in (2812, 2923, 2924, 2927, 2928)
    ready_path = SOURCE / f'muse_nvfp4/state/extra_gpu/{receipt["allocation"]}-ready.json'
    ready = json.loads(ready_path.read_text())
    assert ready['phase'] == 'ready' and ready['endpoint'] == receipt['endpoint']
    payloads[receipt_path] = receipt_bytes
    counts['handoff_receipt'] += 1
    if ready_path not in payloads:
        payloads[ready_path] = ready_path.read_bytes()
        counts['ready_proof'] += 1
    for config_path in (Path(receipt['original_config']), Path(receipt['effective_config'])):
        assert config_path.is_file()
        if config_path not in payloads:
            payloads[config_path] = config_path.read_bytes()
            counts['job_config'] += 1
for receipt_path in sorted((SOURCE / 'muse_nvfp4/state/future-routes').glob('r[23]-completion-2866-b*-route.json')):
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    assert receipt['round'] in (2, 3) and receipt['allocation'] in (2812, 2866, 2867, 2923, 2924, 2927, 2928)
    original, effective = Path(receipt['original_config']), Path(receipt['effective_config'])
    assert original.is_file() and effective.is_file()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == receipt['original_sha256']
    assert hashlib.sha256(effective.read_bytes()).hexdigest() == receipt['effective_sha256']
    expected = json.loads(original.read_text())
    expected['agents'][0]['kwargs']['api_base'] = receipt['endpoint']
    assert json.loads(effective.read_text()) == expected
    ready_path = (SOURCE / 'muse_nvfp4/state/reassigned-2867/endpoint-ready.json'
                  if receipt['allocation'] == 2867 else
                  SOURCE / f'muse_nvfp4/state/extra_gpu/{receipt["allocation"]}-ready.json')
    ready = json.loads(ready_path.read_text())
    if receipt['allocation'] == 2867:
        assert ready['allocation'] == 2867 and ready['model'] == 'muse-spark-open-nvfp4'
        assert ready['api_base'] == receipt['endpoint']
    else:
        assert ready['phase'] == 'ready' and ready['endpoint'] == receipt['endpoint']
        if receipt['allocation'] == 2812:
            assert ready['claimed_round1_batches'] == ['b05']
            b05_exit = json.loads((SOURCE / 'muse_nvfp4/state/extra_gpu/r1-b05-early-exit.json').read_text())
            assert b05_exit['returncode'] == 0 and b05_exit['missing_terminal_tasks'] == []
    related = [receipt_path, SOURCE / f'muse_nvfp4/state/{original.stem}-extra-owner.json',
               SOURCE / f'muse_nvfp4/state/{original.stem}-extra-exit.json']
    for path in related:
        if path.exists() and path not in payloads:
            payloads[path] = path.read_bytes()
            counts['handoff_receipt'] += 1
    if ready_path not in payloads:
        payloads[ready_path] = ready_path.read_bytes()
        counts['ready_proof'] += 1
    for config_path in (original, effective):
        if config_path not in payloads:
            payloads[config_path] = config_path.read_bytes()
            counts['job_config'] += 1
for marker_name in ('r1-b05-early-owner.json', 'r1-b05-early-exit.json', 'r1-b05-normal-started.json'):
    marker = SOURCE / 'muse_nvfp4/state/extra_gpu' / marker_name
    if marker.exists():
        payloads[marker] = marker.read_bytes()
        counts['handoff_receipt'] += 1
for task, replacement_job in zip(('password-recovery', 'prove-plus-comm'), replacement_jobs):
    replacement_claim = SOURCE / f'muse_nvfp4/state/r2-{task}-infra-replacement-claim.json'
    if replacement_claim.exists():
        claim = json.loads(replacement_claim.read_text())
        assert claim['replacement_job_name'] == replacement_job.name
        config = Path(claim['replacement_job_config'])
        assert hashlib.sha256(config.read_bytes()).hexdigest() == claim['replacement_job_config_sha256']
        assert hashlib.sha256(Path(claim['original_result_path']).read_bytes()).hexdigest() == claim['original_result_sha256']
        payloads[replacement_claim] = replacement_claim.read_bytes()
        counts['handoff_receipt'] += 1
        if config not in payloads:
            payloads[config] = config.read_bytes()
            counts['job_config'] += 1
transport_claim = SOURCE / 'muse_nvfp4/state/r2-prove-plus-comm-transport-correction-claim.json'
if transport_claim.exists():
    claim = json.loads(transport_claim.read_text())
    assert claim['replacement_job_name'] == transport_job.name
    config = Path(claim['replacement_job_config'])
    failed_evidence = Path(claim['failed_transport_evidence'])
    assert hashlib.sha256(config.read_bytes()).hexdigest() == claim['replacement_job_config_sha256']
    assert hashlib.sha256(failed_evidence.read_bytes()).hexdigest() == claim['failed_transport_evidence_sha256']
    payloads[transport_claim] = transport_claim.read_bytes()
    counts['handoff_receipt'] += 1
    if config not in payloads:
        payloads[config] = config.read_bytes()
        counts['job_config'] += 1
storage_claim = SOURCE / 'muse_nvfp4/state/r2-pytorch-model-cli-storage-replacement-claim.json'
if storage_claim.exists():
    claim = json.loads(storage_claim.read_text())
    assert claim['replacement_job_name'] == storage_job.name
    config = Path(claim['replacement_job_config'])
    original = Path(claim['original_result_path'])
    assert hashlib.sha256(config.read_bytes()).hexdigest() == claim['replacement_job_config_sha256']
    assert hashlib.sha256(original.read_bytes()).hexdigest() == claim['original_result_sha256']
    payloads[storage_claim] = storage_claim.read_bytes()
    counts['handoff_receipt'] += 1
    if config not in payloads:
        payloads[config] = config.read_bytes()
        counts['job_config'] += 1
connection_claim = SOURCE / 'muse_nvfp4/state/r2-connection-recovery-20261020-claim.json'
if connection_claim.exists():
    claim = json.loads(connection_claim.read_text())
    assert claim['job_name'] == connection_job.name
    assert len(claim['origins']) == 10 and len({row['task'] for row in claim['origins']}) == 10
    config = Path(claim['config'])
    assert hashlib.sha256(config.read_bytes()).hexdigest() == claim['config_sha256']
    for origin in claim['origins']:
        original = Path(origin['original_result'])
        assert hashlib.sha256(original.read_bytes()).hexdigest() == origin['original_result_sha256']
    payloads[connection_claim] = connection_claim.read_bytes()
    counts['handoff_receipt'] += 1
    if config not in payloads:
        payloads[config] = config.read_bytes()
        counts['job_config'] += 1
    source_script = ROOT / 'prepare_muse_nvfp4_r2_connection_recovery.py'
    payloads[source_script] = source_script.read_bytes()
    counts['controller_source'] += 1
expiry_claim = SOURCE / 'muse_nvfp4/state/r2-expiry-correction-2902-20261020-claim.json'
if expiry_claim.exists():
    claim = json.loads(expiry_claim.read_text())
    assert claim['job_name'] == expiry_correction_job.name
    assert claim['new_allocation'] == 2902 and claim['old_allocation'] == 2867
    assert claim['no_best_of_selection'] and claim['no_model_retry']
    for key in ('config', 'source_config', 'source_claim', 'new_endpoint_ready',
                'new_reasoning_preflight', 'image_proof'):
        source = Path(claim[key])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == claim[key + '_sha256']
        if source not in payloads:
            payloads[source] = source.read_bytes()
            counts['job_config' if key.endswith('config') else 'ready_proof' if key in ('new_endpoint_ready', 'new_reasoning_preflight') else 'handoff_receipt'] += 1
    for row in claim['tasks']:
        for key in ('source_original_result', 'previous_recovery_result'):
            if row.get(key):
                source = Path(row[key])
                assert hashlib.sha256(source.read_bytes()).hexdigest() == row[key + '_sha256']
    payloads[expiry_claim] = expiry_claim.read_bytes()
    counts['handoff_receipt'] += 1
    handoff = SOURCE / 'muse_nvfp4/state/replicas-extra-20261020/2902/handoff-from-expired-2867.json'
    if handoff.exists():
        payloads[handoff] = handoff.read_bytes()
        counts['handoff_receipt'] += 1
    source_script = ROOT / 'protocol/prepare_muse_nvfp4_r2_expiry_correction_20261020.py'
    payloads[source_script] = source_script.read_bytes()
    counts['controller_source'] += 1
    controller_script = ROOT / 'protocol/run_muse_nvfp4_r2_expiry_correction_20261020.py'
    payloads[controller_script] = controller_script.read_bytes()
    counts['controller_source'] += 1
    for suffix in ('start', 'exit'):
        marker = expiry_claim.with_name(f'r2-expiry-correction-2902-20261020-{suffix}.json')
        if marker.exists():
            payloads[marker] = marker.read_bytes()
            counts['handoff_receipt'] += 1
for label, job in (('fasttext-expiry', fasttext_expiry_job),
                   ('fasttext-tmux', fasttext_tmux_job)):
    claim_path = SOURCE / f'muse_nvfp4/state/r2-{label}-2902-20261020-claim.json'
    if not claim_path.exists():
        continue
    claim = json.loads(claim_path.read_text())
    assert claim['job_name'] == job.name and claim['task'] == 'train-fasttext'
    assert claim['no_model_retry'] and claim['no_best_of_selection']
    for key in ('config', 'source_config', 'source_result'):
        source = Path(claim[key])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == claim[key + '_sha256']
        if source not in payloads:
            payloads[source] = source.read_bytes()
            counts['job_config' if key.endswith('config') else 'result'] += 1
    for key in (('route', 'new_endpoint_ready', 'new_reasoning_preflight', 'image_proof')
                if label == 'fasttext-expiry' else
                ('source_claim', 'preflight', 'harness_tool_class')):
        source = Path(claim[key])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == claim[key + '_sha256']
        if source not in payloads:
            payloads[source] = source.read_bytes()
            counts['ready_proof' if key in ('new_endpoint_ready', 'new_reasoning_preflight', 'preflight')
                   else 'controller_source' if key == 'harness_tool_class' else 'handoff_receipt'] += 1
    payloads[claim_path] = claim_path.read_bytes()
    counts['handoff_receipt'] += 1
    for source in ((ROOT / f'protocol/prepare_muse_nvfp4_r2_{label.replace("-", "_")}_20261020.py'),
                   (ROOT / f'protocol/run_muse_nvfp4_r2_{label.replace("-", "_")}_20261020.py')):
        assert source.is_file()
        payloads[source] = source.read_bytes()
        counts['controller_source'] += 1
    if label == 'fasttext-tmux':
        for source in (ROOT / 'protocol/preinstalled_tmux_isolated_docker.py',
                       ROOT / 'protocol/probe_muse_nvfp4_fasttext_tmux_20261020.py'):
            assert source.is_file()
            payloads[source] = source.read_bytes()
            counts['controller_source'] += 1
    for suffix in ('start', 'exit'):
        marker = claim_path.with_name(f'r2-{label}-2902-20261020-{suffix}.json')
        if marker.exists():
            payloads[marker] = marker.read_bytes()
            counts['handoff_receipt'] += 1
assert counts['raw_response'] > 0 and counts['task_input'] > 0
proc = subprocess.Popen(['zstd', '-q', '-T2', '-3', '-o', str(temp)], stdin=subprocess.PIPE)
try:
    with tarfile.open(fileobj=proc.stdin, mode='w|') as tar:
        for path, data in sorted(payloads.items()):
            assert path.is_relative_to(BASE)
            info = tarfile.TarInfo(str(path.relative_to(BASE)))
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
    proc.stdin.close()
    assert proc.wait() == 0
    temp.rename(archive)
except BaseException:
    proc.kill()
    temp.unlink(missing_ok=True)
    raise
manifest = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'scope': 'Immutable JSON snapshots of live Muse NVFP4 exact-image TB2.1 recovery. Includes launched task descriptions, original and replica-effective configs, handoff receipts, raw model responses with thinking and current trajectories. Running trials are not scored until result.json is terminal.',
    'archive_name': archive.name,
    'archive_size_bytes': archive.stat().st_size,
    'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'file_count': len(payloads),
    'filename_counts': counts,
    'terminal_result_count': terminal_results,
    'source': str(RESULTS),
}
out = ROOT / 'input_output/archive_manifests' / f'{name}.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(manifest, ensure_ascii=False))
