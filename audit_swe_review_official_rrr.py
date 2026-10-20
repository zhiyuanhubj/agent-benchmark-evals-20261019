#!/usr/bin/env python3
"""Publish only complete official SWE-Review split RRR with released native evidence."""

import hashlib
import json
import subprocess
import tarfile
from pathlib import Path


HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
SCORER = HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision_capacity_20261018'
REVIEWERS = {
    'muse-nvfp4': (HOME / '.private/muse_spark_open_20261016/review_bench_20261018',
                   'muse_revision_review_full_io'),
    'beam-bf16': (HOME / '.private/beam_20261018/review_bench',
                  'beam_revision_review_full_io'),
    'muse-bf16': (HOME / '.private/muse_bf16_20261018/review_bench',
                  'muse_bf16'),
}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_if_changed(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if not path.exists() or path.read_text() != data:
        path.write_text(data)


def released_hashes(group, wanted, released):
    manifest_dir = ROOT / 'input_output/archive_manifests'
    manifests = [manifest_dir / f'{group}.json', *sorted(manifest_dir.glob(f'{group}_delta_*.json'))]
    seen = {}
    for manifest_path in manifests:
        if not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text())
        archive_name = manifest['archive_name']
        if archive_name not in released:
            continue
        archive = ROOT / '.release_assets' / archive_name
        assert archive.is_file(), archive
        process = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout, mode='r|') as tar:
                for member in tar:
                    if member.name not in wanted:
                        continue
                    stream = tar.extractfile(member)
                    assert stream is not None, member.name
                    digest = hashlib.sha256()
                    while chunk := stream.read(1024 * 1024):
                        digest.update(chunk)
                    seen[member.name] = (digest.hexdigest(), archive_name)
        finally:
            process.stdout.close()
            stderr = process.stderr.read()
            assert process.wait() == 0, stderr.decode(errors='replace')[-1000:]
    return seen


def main():
    plan = json.loads((SCORER / 'revision-execution-plan.json').read_text())
    public_scorer = ROOT / 'protocol/muse_review_revision_v2/revision_score_v3.py'
    assert sha(public_scorer) == sha(SCORER / 'revision_score_v3.py')
    for path, expected in plan['source_sha256'].items():
        if path.endswith(('compute_da.py', 'compute_rrr.py')):
            assert sha(path) == expected, path
    release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
    assert release['remote_asset_count'] == release['manifest_count'] == release['sha256_and_size_match_count']
    released = {row['asset'] for row in release['items']
                if row['sha256_matches'] and row['bytes_match']}
    sealed_da = json.loads((ROOT / 'evidence/swe_review_complete_split_da.json').read_text())
    complete = {}
    for reviewer, (review_root, archive_group) in REVIEWERS.items():
        for split, spec in plan['splits'].items():
            metrics_dir = review_root / 'revision/metrics'
            summary_path = metrics_dir / f'{split}-summary.json'
            evidence_path = metrics_dir / f'{split}-evidence.json'
            if not summary_path.is_file() or not evidence_path.is_file():
                continue
            summary = json.loads(summary_path.read_text())
            if not summary.get('complete'):
                continue
            evidence = json.loads(evidence_path.read_text())
            expected = summary['expected_revisions']
            assert summary['revision_queue_terminal'] and summary['native_graded_revisions'] == expected
            assert expected == summary['RRR']['revised'] == len(evidence['outcomes'])
            assert summary['RRR']['total'] == summary['DA']['total'] == spec['expected']
            assert not evidence['ungraded'] and not evidence['missing_native_grades']
            assert summary['RRR']['fallback'] == summary['DA']['model_fail']
            assert sha(evidence['canonical_receipt']) == evidence['canonical_receipt_sha256']
            sealed = sealed_da['reviewers'].get(reviewer, {}).get(split)
            if sealed:
                assert summary['DA'] == sealed['metrics']
            sources = evidence['graded_revision_sources_sha256']
            assert len(sources) == expected * 2
            for path, expected_hash in sources.items():
                assert sha(path) == expected_hash, f'Native RRR source changed: {path}'
            wanted = {str(Path(path).relative_to(HOME)): expected_hash
                      for path, expected_hash in sources.items()}
            archived = released_hashes(archive_group, wanted, released)
            if set(archived) != set(wanted):
                continue  # A new terminal result awaits the next released I/O delta.
            assert all(archived[path][0] == digest for path, digest in wanted.items()), \
                'Released native RRR result or verifier report differs from the scored source'
            label = f'{reviewer}_{split}'.replace('-', '_')
            summary_public = {key: value for key, value in summary.items() if key != 'utc'}
            evidence_public = {key: value for key, value in evidence.items() if key != 'utc'}
            write_if_changed(ROOT / 'evidence' / f'{label}_rrr_summary.json', summary_public)
            write_if_changed(ROOT / 'evidence' / f'{label}_rrr_native_evidence.json', evidence_public)
            complete[f'{reviewer}/{split}'] = {
                'DA': summary['DA'], 'RRR': summary['RRR'],
                'expected_revisions': expected,
                'verified_native_result_and_verifier_files': len(wanted),
                'summary': f'evidence/{label}_rrr_summary.json',
                'native_evidence': f'evidence/{label}_rrr_native_evidence.json',
                'scorer_sha256': sha(public_scorer),
                'release_tag': release['release_tag'],
                'release_tags': release.get('release_tags', [release['release_tag']]),
                'qualification': 'complete_verified_official_split_rrr',
            }
    output = {'scope': 'Only complete SWE-Review split RRR with unchanged official metric functions, '
                       'native first attempts and SHA-verified released result/verifier files.',
              'complete_splits': complete}
    write_if_changed(ROOT / 'evidence/swe_review_official_rrr.json', output)
    print(json.dumps({name: row['RRR']['RRR'] for name, row in complete.items()}))


if __name__ == '__main__':
    main()
