#!/usr/bin/env python3
"""Match every committed archive manifest to GitHub's asset digest and size."""
import json
from datetime import datetime, timezone
from pathlib import Path
from release_shards import BASE_TAG, release_assets

ROOT = Path(__file__).resolve().parent
releases = release_assets()
remote = {}
for tag, assets in releases:
    for asset in assets:
        assert asset['name'] not in remote, f'Duplicate archive asset across releases: {asset["name"]}'
        remote[asset['name']] = (tag, asset)
rows = []
for path in sorted((ROOT / 'input_output/archive_manifests').glob('*.json')):
    manifest = json.loads(path.read_text())
    entry = remote.get(manifest['archive_name'])
    tag, asset = entry if entry else (None, None)
    rows.append({
        'manifest': str(path.relative_to(ROOT)),
        'asset': manifest['archive_name'],
        'release_tag': tag,
        'sha256_matches': asset is not None and asset.get('digest') == 'sha256:' + manifest['archive_sha256'],
        'bytes_match': asset is not None and asset['size'] == manifest['archive_size_bytes'],
    })
verified = sum(row['sha256_matches'] and row['bytes_match'] for row in rows)
audit = {
    'verified_utc': datetime.now(timezone.utc).isoformat(),
    'release_tag': BASE_TAG,
    'release_tags': [tag for tag, _ in releases],
    'remote_asset_count': len(remote),
    'manifest_count': len(rows),
    'sha256_and_size_match_count': verified,
    'items': rows,
}
path = ROOT / 'evidence/release-assets-verification.json'
path.write_text(json.dumps(audit, indent=2) + '\n')
print(json.dumps({key: audit[key] for key in ('verified_utc', 'remote_asset_count', 'manifest_count', 'sha256_and_size_match_count')}))
assert len(remote) == len(rows) == verified, 'GitHub Release assets do not match the committed manifests'
