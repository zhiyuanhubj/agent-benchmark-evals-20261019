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
counts = {'job_config': 0, 'handoff_receipt': 0, 'ready_proof': 0, 'task_input': 0, 'trial_config': 0, 'trajectory': 0, 'raw_response': 0, 'result': 0}
terminal_results = 0
for job in sorted(RESULTS.glob('muse-nvfp4-tb-v1-exact-r*-completion-2866-b*')):
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
