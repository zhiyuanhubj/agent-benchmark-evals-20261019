#!/usr/bin/env python3
"""Archive native I/O files changed since an earlier release snapshot."""
import argparse
import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
ALLOWED = ('opus47_legacy', 'beam_legacy', 'muse_bf16', 'muse_bf16_swr',
           'muse_review_full_io', 'beam_review_full_io',
           'muse_review_verifier', 'beam_review_verifier')
parser = argparse.ArgumentParser()
parser.add_argument('group', choices=ALLOWED)
parser.add_argument('--if-changed', action='store_true', help='Succeed without an archive if no source file changed')
args = parser.parse_args()
group = args.group
spec = importlib.util.spec_from_file_location('archive_trials', ROOT / 'archive_trials.py')
archive_trials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive_trials)
manifest_dir = ROOT / 'input_output/archive_manifests'
previous = sorted([manifest_dir / f'{group}.json', *manifest_dir.glob(f'{group}_delta_*.json')])[-1]
previous_manifest = json.loads(previous.read_text())
cutoff = datetime.fromisoformat(previous_manifest['generated_utc']) - timedelta(minutes=5)
files = sorted(path for path in archive_trials.iter_files(group) if path.stat().st_mtime > cutoff.timestamp())
if not files and args.if_changed:
    print(json.dumps({'group': group, 'skipped': 'no_changed_files'}))
    raise SystemExit(0)
assert files, f'No new native input/output files for {group}'
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
name = f'{group}_delta_{stamp}'
archive = ROOT / '.release_assets' / f'{name}.tar.zst'
temp = archive.with_suffix(archive.suffix + '.tmp')
archive.parent.mkdir(exist_ok=True)
assert not archive.exists()
proc = subprocess.Popen(['zstd', '-q', '-T2', '-3', '-o', str(temp)], stdin=subprocess.PIPE)
counts = {}
source_bytes = 0
try:
    with tarfile.open(fileobj=proc.stdin, mode='w|') as tar:
        for path in files:
            assert path.is_relative_to(BASE)
            data = path.read_bytes()  # Stable snapshot even if an active trial appends later.
            info = tarfile.TarInfo(str(path.relative_to(BASE)))
            info.size = len(data)
            info.mtime = int(path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
            source_bytes += len(data)
            category = ('api_archive.json' if 'api_archive' in path.parts else
                        'raw_response.json' if 'raw_responses' in path.parts else
                        'completion.json' if 'completions' in path.parts else path.name)
            counts[category] = counts.get(category, 0) + 1
    proc.stdin.close()
    assert proc.wait() == 0
    temp.rename(archive)
except BaseException:
    proc.kill()
    temp.unlink(missing_ok=True)
    raise
with archive.open('rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
manifest = {
    'generated_utc': datetime.now(timezone.utc).isoformat(),
    'group': group,
    'scope': 'Native benchmark input/output files with source mtime later than the previous archive time minus five minutes. Overlap is deliberate so files modified during archiving are not omitted. Reconstruct current state by applying this archive after the named previous archive; later paths replace earlier paths.',
    'previous_manifest': str(previous.relative_to(ROOT)),
    'cutoff_utc': cutoff.isoformat(),
    'archive_name': archive.name,
    'archive_size_bytes': archive.stat().st_size,
    'archive_sha256': digest,
    'file_count': len(files),
    'source_bytes': source_bytes,
    'filename_counts': counts,
    'source_roots': [str(path) for path in archive_trials.GROUPS[group]],
}
out = manifest_dir / f'{name}.json'
out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({key: manifest[key] for key in ('group', 'archive_name', 'archive_size_bytes', 'archive_sha256', 'file_count', 'source_bytes', 'filename_counts')}))
