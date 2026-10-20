#!/usr/bin/env python3
"""Stage the original BF16 I/O preserved before Harbor resumed interrupted trials."""
import collections
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECOVERY = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/recovery_20261020')
source = json.loads((RECOVERY / 'interrupted-original-dirs-manifest.json').read_text())
assert source['cause'].startswith('Slurm allocation 2865 expired')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


for group in ('tb', 'deep'):
    record = source['jobs'][group]
    original = Path(record['archive'])
    assert original.parent == RECOVERY and original.is_file()
    assert original.stat().st_size == record['archive_bytes']
    assert sha(original) == record['archive_sha256']
    with tarfile.open(original, 'r:gz') as tar:
        members = tar.getmembers()
        assert len(members) == record['archive_members']
        assert all(not member.issym() and not member.islnk() and
                   member.name.startswith(group + '/') and '..' not in Path(member.name).parts
                   for member in members)
        assert not any('/verifier/' in member.name and member.isfile() for member in members)
        files = [member for member in members if member.isfile()]
        if group == 'tb':
            assert any('/agent/raw_responses/' in member.name for member in files)
        assert any('trajectory.json' in member.name for member in files)
    name = f'muse_bf16_interrupted_{group}_original_20261020.tar.gz'
    asset = ROOT / '.release_assets' / name
    if asset.exists():
        assert sha(asset) == record['archive_sha256']
    else:
        shutil.copy2(original, asset)
    manifest = {
        'generated_utc': source['utc'],
        'group': f'muse_bf16_interrupted_{group}',
        'archive_name': name,
        'archive_size_bytes': asset.stat().st_size,
        'archive_sha256': sha(asset),
        'file_count': len(files),
        'archive_members': len(members),
        'filename_counts': dict(collections.Counter(Path(member.name).name for member in files)),
        'source_roots': [str(original)],
        'scope': ('Original resultless native trial directories saved before Harbor same-job resume. '
                  'Contains model-visible config, raw responses, thinking/trajectories and tool transcripts; '
                  'empty verifier directories contain no hidden verifier files. These originals are ungraded '
                  'infrastructure interruptions and cannot count as failures or additional scored attempts.'),
        'provenance': 'evidence/muse_bf16_2865_expiry_recovery.json',
    }
    path = ROOT / 'input_output/archive_manifests' / f'muse_bf16_interrupted_{group}_delta_20261020T072043Z.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'archive': name, 'file_count': len(files),
                      'bytes': asset.stat().st_size, 'sha256': manifest['archive_sha256']}))
