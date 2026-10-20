#!/usr/bin/env python3
"""Verify released revision input coverage and native archive separation."""
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone

HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parent
PAIR = (
    ('muse', 'muse_review_revision_inputs', 'muse_revision_review_full_io', (
        HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_coder_30b_500',
        HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500')),
    ('beam', 'beam_review_revision_inputs', 'beam_revision_review_full_io', (
        HOME / '.private/beam_20261018/review_bench/revision/generation/qwen3_30b_instruct2507_500',)),
)


def members(group):
    manifest_path = ROOT / 'input_output/archive_manifests' / (group + '.json')
    manifest = json.loads(manifest_path.read_text())
    archive = ROOT / '.release_assets' / manifest['archive_name']
    assert archive.stat().st_size == manifest['archive_size_bytes']
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == manifest['archive_sha256']
    process = subprocess.Popen(['zstd', '-dc', str(archive)], stdout=subprocess.PIPE)
    names = []
    try:
        with tarfile.open(fileobj=process.stdout, mode='r|') as tar:
            for member in tar:
                assert member.isfile() and not member.name.startswith('/')
                assert '..' not in Path(member.name).parts
                names.append(member.name)
    finally:
        process.stdout.close()
    assert process.wait() == 0
    assert len(names) == len(set(names)) == manifest['file_count']
    return manifest_path, manifest, set(names)


release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
verified = {item['asset'] for item in release['items'] if item['sha256_matches'] and item['bytes_match']}
observed = []
for label, input_group, output_group, works in PAIR:
    input_path, input_manifest, input_names = members(input_group)
    output_path, output_manifest, output_names = members(output_group)
    assert input_manifest['archive_name'] in verified and output_manifest['archive_name'] in verified
    expected = set()
    for work in works:
        plan = json.loads((work / 'gateway-recovery-20261020/queue/queue-plan.json').read_text())
        for split, spec in plan['splits'].items():
            source = Path(spec['source_tasks'])
            for task in spec['tasks']:
                expected.add(str((source / task / 'task.toml').relative_to(HOME)))
                expected.add(str((source / task / 'instruction.md').relative_to(HOME)))
        old = work / 'queue/results'
        old_files = [str(path.relative_to(HOME)) for path in old.rglob('result.json')]
        assert set(old_files) <= output_names, 'Original pre-model failure file missing from release'
    assert expected <= input_names
    assert not any('/solution/' in '/' + name or '/tests/' in '/' + name for name in input_names)
    original_outputs = sum('/queue/results/' in '/' + name and '/gateway-recovery-20261020/' not in '/' + name
                           for name in output_names)
    recovery_outputs = sum('/gateway-recovery-20261020/queue/results/' in '/' + name for name in output_names)
    assert original_outputs and recovery_outputs
    observed.append(dict(reviewer=label, expected_task_card_files=len(expected),
                         expected_task_cards=len(expected) // 2,
                         released_task_card_files=len(expected & input_names),
                         released_input_file_count=len(input_names),
                         released_original_host_ip_output_files=original_outputs,
                         released_gateway_recovery_output_files=recovery_outputs,
                         input_manifest=str(input_path.relative_to(ROOT)),
                         output_manifest=str(output_path.relative_to(ROOT)),
                         input_archive_sha256=input_manifest['archive_sha256'],
                         output_archive_sha256=output_manifest['archive_sha256'],
                         remote_sha256_and_size_verified=True))

result = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
              scope='Base release archive coverage at each archive generation time. Live native files added or changed afterward require timestamped delta archives; this is not a claim of current complete revision output coverage.',
              groups=observed)
target = ROOT / 'evidence/review_revision_release_coverage.json'
temp = target.with_suffix('.tmp')
temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
temp.replace(target)
print(json.dumps({row['reviewer']: dict(tasks=row['expected_task_cards'],
                                         original_files=row['released_original_host_ip_output_files'],
                                         recovery_files=row['released_gateway_recovery_output_files'])
                  for row in observed}))
