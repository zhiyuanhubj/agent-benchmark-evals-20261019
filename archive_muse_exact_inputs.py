#!/usr/bin/env python3
"""Archive all public Muse NVFP4 exact-image TB2.1 round-one task inputs."""

import hashlib
import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
SOURCE = BASE / '.private/beam_20261018/tb_v1_exact_images_20261019'
ROOT = Path(__file__).resolve().parent
name = 'muse_nvfp4_exact_tb_round1_inputs_20261019'
archive = ROOT / '.release_assets' / f'{name}.tar.zst'
manifest = ROOT / 'input_output/archive_manifests' / f'{name}.json'
assert not archive.exists() and not manifest.exists()

files = [SOURCE / 'image-identity-plan.json']
tasks = set()
for shard in (1, 2, 3):
    config_path = SOURCE / f'muse_nvfp4/configs/r1-shard{shard}.json'
    files.append(config_path)
    for item in json.loads(config_path.read_text())['tasks']:
        task_file = Path(item['path']) / 'task.toml'
        assert task_file.is_file() and task_file not in tasks
        tasks.add(task_file)
assert len(tasks) == 89
files.extend(sorted(tasks))

temp = archive.with_suffix('.tar.zst.tmp')
proc = subprocess.Popen(['zstd', '-q', '-T2', '-3', '-o', str(temp)], stdin=subprocess.PIPE)
try:
    with tarfile.open(fileobj=proc.stdin, mode='w|') as tar:
        for path in sorted(files):
            assert path.is_relative_to(BASE) and path.is_file() and not path.is_symlink()
            data = path.read_bytes()
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
with archive.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
record = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'archive_name': archive.name,
    'archive_size_bytes': archive.stat().st_size,
    'archive_sha256': digest,
    'scope': 'All 89 public task.toml inputs for Muse NVFP4 exact supplied-image TB2.1 round one, the three original task-partition configs, and image identity/digest plan. No verifier, solution, credential, or model weight.',
    'file_count': len(files),
    'filename_counts': {'task.toml': 89, 'job_config': 3, 'image_identity_plan': 1},
    'source': str(SOURCE),
}
manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(record, ensure_ascii=False))
