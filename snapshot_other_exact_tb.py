#!/usr/bin/env python3
"""Archive current native Beam or Opus exact-image TB2.1 input/output."""
import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
MODELS = {
    'opus47': {'results': 'opus47', 'configs': 'opus47', 'job_pattern': 'opus47-tb-v1-exact-r*'},
    'beam_bf16': {'results': 'beam_bf16', 'configs': 'beam', 'job_pattern': 'beam-tb-v1-exact-r*'},
}
parser = argparse.ArgumentParser()
parser.add_argument('model', choices=MODELS)
model = parser.parse_args().model
profile = MODELS[model]
result_root = SOURCE / 'results' / profile['results']
config_root = SOURCE / profile['configs'] / 'configs'
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
name = f'{model}_exact_tb_live_{stamp}'
archive = ROOT / '.release_assets' / f'{name}.tar.zst'
temp = archive.with_suffix(archive.suffix + '.tmp')
archive.parent.mkdir(exist_ok=True)
assert not archive.exists()

payloads = {}
counts = {'job_config': 0, 'task_input': 0, 'trial_config': 0, 'trajectory': 0, 'raw_response': 0, 'result': 0}
terminal_results = 0
for job in sorted(result_root.glob(profile['job_pattern'])):
    if not job.is_dir():
        continue
    match = re.search(r'-r([123])$', job.name)
    assert match, f'Unexpected job name: {job.name}'
    job_config = config_root / f'r{match.group(1)}.json'
    if job_config.exists():
        payloads[job_config] = job_config.read_bytes()
        counts['job_config'] += 1
    for trial in sorted(job.iterdir()):
        if not trial.is_dir():
            continue
        for category, path in [('trial_config', trial / 'config.json'), ('trajectory', trial / 'agent/trajectory.json'), ('result', trial / 'result.json')]:
            if not path.exists() or not path.is_file() or path.is_symlink():
                continue
            data = path.read_bytes()
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                if category == 'trajectory':
                    continue
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
        trial_config = trial / 'config.json'
        if trial_config.exists():
            task = Path(json.loads(trial_config.read_text())['task']['path'])
            task_file = task / 'task.toml'
            if task_file.exists() and task_file not in payloads:
                payloads[task_file] = task_file.read_bytes()
                counts['task_input'] += 1
assert counts['result'] > 0 and counts['raw_response'] > 0
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
    'model': model,
    'scope': 'Timestamped native exact-image TB2.1 task/config inputs, raw model responses, trajectories, and terminal or in-progress result files. Only finished graded results count as benchmark scores.',
    'archive_name': archive.name,
    'archive_size_bytes': archive.stat().st_size,
    'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
    'file_count': len(payloads),
    'filename_counts': counts,
    'terminal_result_count': terminal_results,
    'source': str(result_root),
}
out = ROOT / 'input_output/archive_manifests' / f'{name}.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(manifest, ensure_ascii=False))
