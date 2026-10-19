#!/usr/bin/env python3
"""Match every committed archive manifest to GitHub's asset digest and size."""
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = 'zhiyuanhubj/agent-benchmark-evals-20261019'
TAG = '2026-10-19-snapshot'
release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{REPO}/releases/tags/{TAG}'], text=True))
remote = {asset['name']: asset for asset in release['assets']}
rows = []
for path in sorted((ROOT / 'input_output/archive_manifests').glob('*.json')):
    manifest = json.loads(path.read_text())
    asset = remote.get(manifest['archive_name'])
    rows.append({
        'manifest': str(path.relative_to(ROOT)),
        'asset': manifest['archive_name'],
        'sha256_matches': asset is not None and asset.get('digest') == 'sha256:' + manifest['archive_sha256'],
        'bytes_match': asset is not None and asset['size'] == manifest['archive_size_bytes'],
    })
verified = sum(row['sha256_matches'] and row['bytes_match'] for row in rows)
audit = {
    'verified_utc': datetime.now(timezone.utc).isoformat(),
    'release_tag': TAG,
    'remote_asset_count': len(remote),
    'manifest_count': len(rows),
    'sha256_and_size_match_count': verified,
    'items': rows,
}
path = ROOT / 'evidence/release-assets-verification.json'
path.write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps({key: audit[key] for key in ('verified_utc', 'remote_asset_count', 'manifest_count', 'sha256_and_size_match_count')}))
assert len(remote) == len(rows) == verified, 'GitHub Release assets do not match the committed manifests'
