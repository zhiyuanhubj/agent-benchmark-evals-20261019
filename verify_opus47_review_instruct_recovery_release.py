#!/usr/bin/env python3
"""Verify every selected Opus instruct DA source against released native I/O."""

import hashlib
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
DA = ROOT / 'evidence/opus47_review_instruct_recovery_da.json'
SOURCE_RECEIPT = ROOT / 'evidence/opus47_review_instruct_cancelled_source_release_receipt.json'
RELEASE = ROOT / 'evidence/release-assets-verification.json'
OUTPUT = ROOT / 'evidence/opus47_review_instruct_recovery_da_release.json'
GROUP = 'opus47_review_full_io'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    score = json.loads(DA.read_text())
    assert score['DA']['total'] == 422 and len(score['selected']) == 422
    assert score['status'] == 'complete_with_declared_infrastructure_replacement_release_pending'
    receipt = json.loads(SOURCE_RECEIPT.read_text())
    assert receipt['claim_sha256'] == score['claim_sha256']
    assert receipt['remote_sha256_and_size_verified']
    wanted = {}
    for task, row in score['selected'].items():
        for path_key, hash_key in (('native_result', 'native_result_sha256'),
                                   ('review_report', 'review_report_sha256')):
            path = Path(row[path_key])
            assert sha(path) == row[hash_key], (task, path)
            member = str(path.relative_to(HOME))
            assert member not in wanted
            wanted[member] = row[hash_key]
    assert len(wanted) == 844

    release = json.loads(RELEASE.read_text())
    released = {row['asset'] for row in release['items']
                if row['sha256_matches'] and row['bytes_match']}
    manifests = [ROOT / f'input_output/archive_manifests/{GROUP}.json',
                 *sorted((ROOT / 'input_output/archive_manifests').glob(f'{GROUP}_delta_*.json'))]
    seen = {}
    scanned = []
    for manifest_path in manifests:
        manifest = json.loads(manifest_path.read_text())
        name = manifest['archive_name']
        if name not in released:
            continue
        archive = ROOT / '.release_assets' / name
        assert archive.is_file() and archive.stat().st_size == manifest['archive_size_bytes']
        assert sha(archive) == manifest['archive_sha256']
        process = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as tar:
                for member in tar:
                    if member.name not in wanted:
                        continue
                    stream = tar.extractfile(member)
                    assert stream is not None
                    digest = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                    seen[member.name] = {'sha256': digest.hexdigest(), 'asset': name}
        finally:
            process.stdout.close()
            stderr = process.stderr.read()
            assert process.wait() == 0, stderr.decode(errors='replace')[-1000:]
        scanned.append(name)
    missing = sorted(set(wanted) - set(seen))
    mismatched = sorted(path for path, expected in wanted.items()
                        if path in seen and seen[path]['sha256'] != expected)
    verified = len(wanted) - len(missing) - len(mismatched)
    complete = not missing and not mismatched
    result = {
        'verified_utc': datetime.now(timezone.utc).isoformat(),
        'score_evidence': str(DA.relative_to(ROOT)),
        'score_evidence_sha256': sha(DA),
        'source_cancellation_release_receipt': str(SOURCE_RECEIPT.relative_to(ROOT)),
        'source_cancellation_release_receipt_sha256': sha(SOURCE_RECEIPT),
        'release_verification_sha256': sha(RELEASE),
        'expected_selected_native_result_and_report_files': len(wanted),
        'released_matching_files': verified,
        'missing': missing,
        'hash_mismatches': mismatched,
        'scanned_released_archives': scanned,
        'DA': score['DA'],
        'RRR': None,
        'qualification': ('complete_verified_official_da_with_declared_interruption_replacement'
                          if complete else 'pending_released_native_io'),
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'expected': len(wanted), 'verified': verified,
                      'missing': len(missing), 'mismatched': len(mismatched),
                      'qualification': result['qualification']}))


if __name__ == '__main__':
    main()
