#!/usr/bin/env python3
"""Anchor Opus 4.7 provider transport retries to the published raw I/O asset."""

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = Path('/fsx/home/zhiyuan/bench/opus47_full_20261018/api_archive/claude')
ARCHIVE_NAME = 'opus47_legacy_delta_20261020T234726Z.tar.zst'
ARCHIVE = ROOT / '.release_assets' / ARCHIVE_NAME
MANIFEST = ROOT / 'input_output/archive_manifests/opus47_legacy_delta_20261020T234726Z.json'
VERIFICATION = ROOT / 'evidence/release-assets-verification.json'
OUTPUT = ROOT / 'evidence/opus47_review_provider_http_retry_audit.json'
PAIRS = (
    ('6054c1c9035d4dbf8db106fa18113008.json', '28099b8220b04e65a61f4565c4de38a8.json'),
    ('97ddfe2de5d444edac7c693a78382d33.json', 'fdb4b4febf9c401ebe1441b4f98b98f0.json'),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':')).encode()


def main():
    manifest = json.loads(MANIFEST.read_text())
    assert manifest['archive_name'] == ARCHIVE_NAME
    assert sha(ARCHIVE.read_bytes()) == manifest['archive_sha256']
    verification = json.loads(VERIFICATION.read_text())
    matching = [item for item in verification['items'] if item['asset'] == ARCHIVE_NAME]
    assert len(matching) == 1 and matching[0]['sha256_matches'] and matching[0]['bytes_match']
    rows = []
    for failed_name, successful_name in PAIRS:
        records = []
        for name in (failed_name, successful_name):
            raw = (SOURCE / name).read_bytes()
            member = f'bench/opus47_full_20261018/api_archive/claude/{name}'
            released = subprocess.run(['tar', '-I', 'zstd', '-xOf', str(ARCHIVE), member],
                                      capture_output=True, check=True).stdout
            assert sha(raw) == sha(released), name
            records.append((json.loads(raw), sha(raw)))
        failed, failed_sha = records[0]
        successful, successful_sha = records[1]
        assert failed['status'] == 502 and successful['status'] == 200
        assert failed['request'] == successful['request']
        assert failed['started'] < successful['started']
        rows.append({
            'failed_file': failed_name,
            'failed_file_sha256': failed_sha,
            'failed_http_status': 502,
            'successful_file': successful_name,
            'successful_file_sha256': successful_sha,
            'successful_http_status': 200,
            'exact_request_sha256': sha(canonical(failed['request'])),
            'retry_delay_seconds': round(successful['started'] - failed['started'], 6),
            'thinking_config_equal': failed['request'].get('thinking') == successful['request'].get('thinking'),
            'output_config_equal': failed['request'].get('output_config') == successful['request'].get('output_config'),
            'both_raw_files_byte_matched_to_release_asset': True,
        })
    result = {
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'The two observed HTTP 502 provider records in the Opus 4.7 SWE-Review thinking snapshot, matched to later HTTP 200 records by entire request equality. This does not assign either retry to a particular benchmark task.',
        'release_asset': ARCHIVE_NAME,
        'release_tag': matching[0]['release_tag'],
        'release_asset_sha256': manifest['archive_sha256'],
        'remote_asset_verification_utc': verification['verified_utc'],
        'pairs': rows,
        'qualification': 'two_provider_transport_errors_followed_by_identical_successful_requests_with_published_raw_records',
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'pairs': len(rows), 'qualification': result['qualification']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
