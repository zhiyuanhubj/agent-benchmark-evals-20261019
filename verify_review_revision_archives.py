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
        HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/generation/qwen3_30b_instruct2507_500'),
     HOME / '.private/muse_spark_open_20261016/review_bench_20261018/revision/prepared'),
    ('beam', 'beam_review_revision_inputs', 'beam_revision_review_full_io', (
        HOME / '.private/beam_20261018/review_bench/revision/generation/qwen3_30b_instruct2507_500',),
     HOME / '.private/beam_20261018/review_bench/revision/prepared'),
)


def members(group):
    manifest_dir = ROOT / 'input_output/archive_manifests'
    manifests = sorted([manifest_dir / (group + '.json'), *manifest_dir.glob(group + '_delta_*.json')])
    all_names = set()
    chain = []
    for manifest_path in manifests:
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
        all_names.update(names)
        chain.append((manifest_path, manifest))
    return chain, all_names


release = json.loads((ROOT / 'evidence/release-assets-verification.json').read_text())
verified = {item['asset'] for item in release['items'] if item['sha256_matches'] and item['bytes_match']}
observed = []
for label, input_group, output_group, works, prepared in PAIR:
    input_chain, input_names = members(input_group)
    output_chain, output_names = members(output_group)
    assert all(manifest['archive_name'] in verified for _, manifest in input_chain + output_chain)
    active = set()
    for work in works:
        queue = work / 'gateway-recovery-20261020/queue'
        plan = json.loads((queue / 'queue-plan.json').read_text())
        for split, spec in plan['splits'].items():
            source = Path(spec['source_tasks'])
            for task in spec['tasks']:
                active.add(str((source / task / 'task.toml').relative_to(HOME)))
                active.add(str((source / task / 'instruction.md').relative_to(HOME)))
        old = work / 'queue/results'
        old_files = [str(path.relative_to(HOME)) for path in old.rglob('result.json')]
        assert set(old_files) <= output_names, 'Original pre-model failure file missing from release'
        resume_records = [queue / 'resume-audit.json', *queue.glob('queue-exit-pre-resume-*.json')]
        assert {str(path.relative_to(HOME)) for path in resume_records if path.exists()} <= input_names, \
            'Revision queue resume receipt missing from release'
    expected = {str(path.relative_to(HOME)) for path in prepared.rglob('task.toml')}
    expected |= {str(path.relative_to(HOME)) for path in prepared.rglob('instruction.md')}
    assert len(expected) % 2 == 0 and active <= expected
    assert expected <= input_names
    assert not any('/solution/' in '/' + name or '/tests/' in '/' + name for name in input_names)
    original_outputs = sum('/queue/results/' in '/' + name and '/gateway-recovery-20261020/' not in '/' + name
                           for name in output_names)
    recovery_outputs = sum('/gateway-recovery-20261020/queue/results/' in '/' + name for name in output_names)
    assert original_outputs and recovery_outputs
    observed.append(dict(reviewer=label, expected_task_card_files=len(expected),
                         expected_task_cards=len(expected) // 2,
                         active_gateway_recovery_task_cards=len(active) // 2,
                         released_task_card_files=len(expected & input_names),
                         released_input_file_count=len(input_names),
                         released_original_host_ip_output_files=original_outputs,
                         released_gateway_recovery_output_files=recovery_outputs,
                         input_manifests=[str(path.relative_to(ROOT)) for path, _ in input_chain],
                         output_manifests=[str(path.relative_to(ROOT)) for path, _ in output_chain],
                         input_archive_sha256=[manifest['archive_sha256'] for _, manifest in input_chain],
                         output_archive_sha256=[manifest['archive_sha256'] for _, manifest in output_chain],
                         remote_sha256_and_size_verified=True))

result = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
              scope='Released base and delta archive coverage of prepared revision task cards. Live native output files added or changed afterward require later timestamped delta archives; this is not a claim of current complete revision output coverage.',
              groups=observed)
target = ROOT / 'evidence/review_revision_release_coverage.json'
temp = target.with_suffix('.tmp')
temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
temp.replace(target)
print(json.dumps({row['reviewer']: dict(tasks=row['expected_task_cards'],
                                         original_files=row['released_original_host_ip_output_files'],
                                         recovery_files=row['released_gateway_recovery_output_files'])
                  for row in observed}))
