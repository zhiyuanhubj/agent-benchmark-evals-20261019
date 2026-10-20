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
        HOME / '.private/beam_20261018/review_bench/revision/generation/qwen3_coder_30b_500',
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
        is_beam_coder = label == 'beam' and work.name == 'qwen3_coder_30b_500'
        queue = work / ('gateway-portfix-20261020/queue' if is_beam_coder
                        else 'gateway-recovery-20261020/queue')
        plan_path = queue / 'queue-plan.json'
        assert str(plan_path.relative_to(HOME)) in input_names, \
            'Active revision queue plan missing from release'
        plan = json.loads(plan_path.read_text())
        for split, spec in plan['splits'].items():
            source = Path(spec['source_tasks'])
            for task in spec['tasks']:
                active.add(str((source / task / 'task.toml').relative_to(HOME)))
                active.add(str((source / task / 'instruction.md').relative_to(HOME)))
        old = work / 'queue/results'
        old_files = [str(path.relative_to(HOME)) for path in old.rglob('result.json')]
        assert set(old_files) <= output_names, 'Original pre-model failure file missing from release'
        if is_beam_coder:
            failure = json.loads((ROOT / 'evidence/beam_coder_pre_model_port_mismatch.json').read_text())
            assert failure['failed_pre_model_task_count'] == 16
            assert failure['model_response_count'] == failure['native_grade_count'] == 0
            for record in failure['failed_records']:
                assert record['connectivity'] in output_names, 'Beam Coder pre-model connectivity missing from release'
                if record['native_result_exists']:
                    assert record['result'] in output_names, 'Beam Coder pre-model result missing from release'
        resume_records = [queue / 'resume-audit.json', *queue.glob('queue-exit-pre-resume-*.json')]
        latest_input_archive = datetime.fromisoformat(input_chain[-1][1]['generated_utc']).timestamp()
        receipt_cutoff = min(latest_input_archive - 300,
                             datetime.now(timezone.utc).timestamp() - 600)
        due_receipts = {str(path.relative_to(HOME)) for path in resume_records
                        if path.exists() and path.stat().st_ctime <= receipt_cutoff}
        assert due_receipts <= input_names, \
            'Revision queue resume receipt missing from release'
    prepared_files = {str(path.relative_to(HOME)): path
                      for name in ('task.toml', 'instruction.md')
                      for path in prepared.rglob(name)}
    expected = set(prepared_files)
    cards = {}
    for path in prepared_files.values():
        cards.setdefault(path.parent, set()).add(path.name)
    assert active <= expected
    assert active <= input_names, 'An active revision task card is missing from the release'
    # Preparation can publish a new directory while this verifier reads the
    # release. Preserve the strict check for old omissions, but let recent
    # unqueued cards wait for the next ten-minute input archive.
    latest_input_archive = datetime.fromisoformat(input_chain[-1][1]['generated_utc']).timestamp()
    recent_cutoff = max(latest_input_archive - 300,
                        datetime.now(timezone.utc).timestamp() - 600)
    incomplete_cards = [directory for directory, names in cards.items()
                        if names != {'task.toml', 'instruction.md'}]
    assert all(directory.stat().st_ctime >= recent_cutoff for directory in incomplete_cards), \
        'An old prepared revision card is incomplete'
    pending = expected - input_names
    assert all(max(prepared_files[name].stat().st_ctime,
                   prepared_files[name].parent.stat().st_ctime) >= recent_cutoff
               for name in pending), 'An old prepared revision task card is missing from the release'
    assert not any('/solution/' in '/' + name or '/tests/' in '/' + name for name in input_names)
    original_outputs = sum('/queue/results/' in '/' + name and
                           '/gateway-recovery-20261020/' not in '/' + name and
                           '/gateway-portfix-20261020/' not in '/' + name
                           for name in output_names)
    recovery_outputs = sum(('/gateway-recovery-20261020/queue/results/' in '/' + name or
                            '/gateway-portfix-20261020/queue/results/' in '/' + name)
                           for name in output_names)
    assert original_outputs and recovery_outputs
    observed.append(dict(reviewer=label, expected_task_card_files=len(expected),
                         expected_task_cards=len(cards),
                         active_gateway_recovery_task_cards=len(active) // 2,
                         released_task_card_files=len(expected & input_names),
                         pending_new_task_card_files=len(pending),
                         pending_incomplete_task_cards=len(incomplete_cards),
                         released_input_file_count=len(input_names),
                         released_original_host_ip_output_files=original_outputs,
                         released_gateway_recovery_output_files=recovery_outputs,
                         input_manifests=[str(path.relative_to(ROOT)) for path, _ in input_chain],
                         output_manifests=[str(path.relative_to(ROOT)) for path, _ in output_chain],
                         input_archive_sha256=[manifest['archive_sha256'] for _, manifest in input_chain],
                         output_archive_sha256=[manifest['archive_sha256'] for _, manifest in output_chain],
                         remote_sha256_and_size_verified=True))

result = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
              scope='Released base and delta archive coverage of prepared revision task cards. Every active gateway task card is released; recently materialized unqueued cards are counted as pending until the next input archive. Live native outputs require later timestamped delta archives; this is not a claim of current complete revision output coverage.',
              groups=observed)
target = ROOT / 'evidence/review_revision_release_coverage.json'
temp = target.with_suffix('.tmp')
temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
temp.replace(target)
print(json.dumps({row['reviewer']: dict(tasks=row['expected_task_cards'],
                                         pending_new_task_card_files=row['pending_new_task_card_files'],
                                         original_files=row['released_original_host_ip_output_files'],
                                         recovery_files=row['released_gateway_recovery_output_files'])
                  for row in observed}))
