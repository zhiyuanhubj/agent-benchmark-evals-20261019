"""Read-only progress for Beam, Opus4.7, and the separate Muse BF16 run."""
from pathlib import Path
from collections import Counter
import datetime
import hashlib
import json
import os
import subprocess

BEAM = Path(__file__).resolve().parent
OPUS = Path('/fsx/home/zhiyuan/bench/opus47_full_20261018')
MUSE = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018')


def load(path):
    return json.loads(path.read_text()) if path.exists() else None


def pro(roots, expected_ids, excluded_run_names=()):
    expected_set = set(expected_ids)
    assert len(expected_set) == len(expected_ids) == 731
    records = []
    for root in roots:
        for path in root.glob('**/attempt-1/result.json'):
            if any(name in path.parts for name in excluded_run_names):
                continue
            data = load(path)
            # AgentCompass shortens detail directory names. Only task.json
            # preserves the full task ID (including the complete variant).
            task_path = path.parent.parent / 'task.json'
            task = load(task_path)['task_id']
            assert task in expected_set, 'Unexpected Pro task: ' + task
            score = data.get('metrics', {}).get('correct')
            benchmark = (data.get('meta') or {}).get('benchmark') or {}
            evaluation = benchmark.get('eval_raw_data') or {}
            graded = evaluation.get('completed') is True and isinstance(score, bool)
            if graded:
                assert score == bool(evaluation['resolved']), 'Metric disagrees with native grader'
            records.append(dict(task=task, graded=graded, success=graded and score is True,
                native_status=data.get('status'), native_grader_completed=evaluation.get('completed'),
                has_native_error=bool(data.get('error')), path=str(path)))
    ids = Counter(row['task'] for row in records)
    return dict(expected=len(expected_set), terminal=len(records), unique_tasks=len(ids),
                graded=sum(row['graded'] for row in records), success=sum(row['success'] for row in records),
                missing_native_grader_completion=sum(not row['graded'] for row in records),
                native_status_counts=dict(Counter(row['native_status'] for row in records)),
                duplicate_task_ids=[key for key, value in ids.items() if value > 1],
                missing_result_task_count=len(expected_set - set(ids)),
                task_id_source='Original task.json task_id, never a shortened directory name',
                qualification='Partial counts are not full-set accuracy. Native correctness only; no best-of selection.')


def harbor(roots, expected_ids, excluded_originals=None):
    expected_set = set(expected_ids)
    assert len(expected_set) == len(expected_ids)
    records = []
    excluded_originals = excluded_originals or {}
    excluded = []
    for root in roots:
        for path in root.glob('*/result.json'):
            data = load(path)
            if not data.get('task_name') or not data.get('finished_at'):
                continue
            task = Path(data['config']['task']['path']).name
            assert task in expected_set, 'Unexpected Harbor task: ' + task
            score = (data.get('verifier_result') or {}).get('rewards', {}).get('reward')
            if str(path) in excluded_originals:
                frozen = excluded_originals[str(path)]
                assert hashlib.sha256(path.read_bytes()).hexdigest() == frozen['sha256'], 'Frozen invalid original changed'
                assert score is None and (data.get('exception_info') or {}).get('exception_type') == 'BadRequestError'
                assert 'missing its reasoning' in data['exception_info']['exception_message']
                excluded.append(dict(path=str(path), task=task, **frozen))
                continue
            records.append(dict(task=task, reward=score,
                exception=(data.get('exception_info') or {}).get('exception_type')))
    ids = Counter(row['task'] for row in records)
    assert {row['path'] for row in excluded} == set(excluded_originals)
    return dict(expected=len(expected_set), terminal=len(records), unique_tasks=len(ids),
                graded=sum(row['reward'] in [0, 1] for row in records),
                success=sum(row['reward'] == 1 for row in records),
                exceptions=dict(Counter(row['exception'] for row in records if row['exception'])),
                duplicate_task_ids=[key for key, value in ids.items() if value > 1],
                excluded_invalid_protocol_originals=excluded,
                missing_result_task_count=len(expected_set - set(ids)),
                task_id_source='Original trial config task path; finished native trial and binary reward required')


legacy = BEAM / 'legacy_bench_20261018'
record = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
partition = load(legacy / 'partition-plan.json')
beam_pro_ids = partition['initial']['pro']['tasks'] + partition['remaining_first_round']['pro']['tasks']
opus_command = load(OPUS / 'pro-command.json')
opus_pro_ids = json.loads(opus_command[opus_command.index('--benchmark-params') + 1])['sample_ids']
muse_command = load(MUSE / 'legacy_bench/pro-command.template.json')
muse_pro_ids = json.loads(muse_command[muse_command.index('--benchmark-params') + 1])['sample_ids']
assert set(beam_pro_ids) == set(opus_pro_ids) == set(muse_pro_ids)
expected_harbor = {}
for kind in ['tb', 'deep']:
    ids = partition['initial'][kind]['tasks'] + partition['remaining_first_round'][kind]['tasks']
    opus_config = load(OPUS / 'configs' / (kind + '-r1.json'))
    muse_config = load(MUSE / 'legacy_bench/configs' / (kind + '-r1.template.json'))
    opus_tasks = opus_config.get('config', opus_config)['tasks']
    muse_tasks = muse_config.get('config', muse_config)['tasks']
    assert set(ids) == {Path(task['path']).name for task in opus_tasks} == {Path(task['path']).name for task in muse_tasks}
    assert len(set(ids)) == len(ids) == {'tb': 89, 'deep': 113}[kind]
    expected_harbor[kind] = ids
beam_pro_round2_name = 'beam_pro_full731_round2_2888_20261020'
beam_pro_round2_root = (legacy / 'remaining_pro/pro-results' / beam_pro_round2_name /
                        'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent' /
                        'beam-pro-full731-r2-2888-20261020')
record['beam_bf16'] = dict(
    pro=pro([legacy / 'pro-results', legacy / 'remaining_pro/pro-results'], beam_pro_ids,
            excluded_run_names=(beam_pro_round2_name,)),
    pro_round2=pro([beam_pro_round2_root], beam_pro_ids),
)
record['beam_bf16']['tb_initial_client_protocol_issue'] = load(legacy / 'state/tb-initial-output-length-client-issue.json')
record['beam_bf16']['future_tb_output_length_thinking_validation'] = load(legacy / 'remaining_tb/state/output-length-thinking-validation.json')
beam_tb_recovery = legacy / 'tb_protocol_recovery_20261018'
beam_tb_recovery_plan = load(beam_tb_recovery / 'plan.json')
for kind, count in [('tb', 89), ('deep', 113)]:
    rounds = {}
    for number in [1, 2, 3]:
        roots = list((legacy / ('remaining_' + kind) / (kind + '-results')).glob('beam-' + kind + '-r' + str(number) + '*'))
        if number == 1:
            roots += list((legacy / (kind + '-results')).glob('beam-' + kind + '-r1-initial24'))
        excluded = {}
        if kind == 'tb' and number == 1 and beam_tb_recovery_plan:
            roots += [Path(beam_tb_recovery_plan['native_job'])]
            excluded = {beam_tb_recovery_plan['original_invalid_result']: dict(
                sha256=beam_tb_recovery_plan['original_invalid_result_sha256'],
                original_actual_model_responses=93,
                qualification=beam_tb_recovery_plan['qualification'])}
        rounds[str(number)] = harbor(roots, expected_harbor[kind], excluded)
    record['beam_bf16'][kind] = rounds
opus_pro_run_id = opus_command[opus_command.index('--run-id') + 1]
opus_pro_roots = list((OPUS / 'pro-results').glob(f'*/*/{opus_pro_run_id}'))
assert len(opus_pro_roots) == 1, f'Expected one original Opus Pro run, got {opus_pro_roots}'
record['opus47'] = dict(pro=pro(opus_pro_roots, opus_pro_ids))
record['opus47']['pro']['scoring_run_id'] = opus_pro_run_id
record['opus47']['pro']['excluded_verifier_recovery_run_ids'] = sorted(
    path.name for path in opus_pro_roots[0].parent.glob('opus47-pro-eval-recovery-*') if path.is_dir())
record['beam_bf16']['tb_first_round_client_protocol_recovery'] = dict(
    current=load(beam_tb_recovery / 'state/current.json'),
    native_preflight=load(beam_tb_recovery / 'state/preflight-verified.json'),
    qualification=beam_tb_recovery_plan['qualification'] if beam_tb_recovery_plan else None)
for kind, count in [('tb', 89), ('deep', 113)]:
    record['opus47'][kind] = {str(number): harbor(
        [OPUS / (kind + '-results') / ('opus47-tb-r1-counter-corrected' if kind == 'tb' and number == 1 else 'opus47-' + kind + '-r' + str(number))], expected_harbor[kind])
        for number in [1, 2, 3]}
invalid = load(OPUS / 'state/tb-r1-token-counter-invalid-attempts.json')
record['opus47']['tb_invalid_harness_run'] = dict(
    excluded_from_valid_rounds=bool(invalid), source=str(OPUS / 'state/tb-r1-token-counter-invalid-attempts.json'),
    model_responses_before_failure=invalid.get('model_responses_before_failure') if invalid else None,
    qualification='Local-only token counter was invalid for Claude gateway. Originals retained; replacement resamples incomplete invalid-protocol attempts, never correctness-selected.')
record['muse_bf16'] = dict(weight_staging=load(MUSE / 'stage_2869/prefetch-current.json'),
    paired_runtime=load(MUSE / 'pair-current.json'), endpoint_ready=load(MUSE / 'endpoint-ready.json'),
    native_tool_thinking_preflight=load(MUSE / 'native-preflight-ready.json'),
    future_cpu_placement=load(MUSE / 'cpu_placement_repair_20261018/waiting-controllers-reloaded.json'))
muse_pro_parent = (MUSE / 'legacy_bench/pro-results/muse_bf16_full'
    / 'muse-spark-open-bf16_swebench_pro_verified_mini_swe_agent')
muse_pro_original = muse_pro_parent / 'muse-bf16-pro-full-r1'
muse_pro_resumed = muse_pro_parent / 'muse-bf16-pro-full-r1-resume-20261020'
muse_pro_source_progress = load(muse_pro_original / 'progress.json')
muse_pro_resume_progress = load(muse_pro_resumed / 'progress.json')
if muse_pro_resume_progress:
    assert muse_pro_source_progress and muse_pro_resume_progress['total_tasks'] == 731
    assert muse_pro_resume_progress['reused_tasks'] == muse_pro_source_progress['completed_tasks'], (
        'The resumed Pro run did not reuse every completed original task')
    muse_pro_scoring_run = muse_pro_resumed
else:
    muse_pro_scoring_run = muse_pro_original
record['muse_bf16']['pro'] = pro([muse_pro_scoring_run], muse_pro_ids)
record['muse_bf16']['pro'].update(
    scoring_run_id=muse_pro_scoring_run.name,
    source_run_id=muse_pro_original.name,
    reused_original_completed_tasks=(muse_pro_resume_progress or {}).get('reused_tasks', 0),
    original_unreused_failed_tasks=(muse_pro_source_progress or {}).get('failed_tasks', 0),
    recovery_qualification=('Original completed tasks are counted once; failed source attempts and '
        'interrupted source tasks remain separately preserved. The resumed run is scored on its '
        'own native results, without pooling duplicate task records.'))
for kind, count in [('tb', 89), ('deep', 113)]:
    record['muse_bf16'][kind] = {str(number): harbor([MUSE / ('legacy_bench/' + kind + '-results') / ('muse-bf16-' + kind + '-r' + str(number))], expected_harbor[kind]) for number in [1, 2, 3]}
record['reserved_capacity'] = load(BEAM / 'expanded_capacity_20261018/current.json')
record['reserved_beam_servers'] = load(BEAM / 'expanded_capacity_20261018/serving-current.json')
revision_runtime = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/revision_capacity_20261018')
record['swe_review_original_revision_pipeline'] = dict(
    serving=load(revision_runtime / 'runtime-current.json'),
    revision_queues=load(revision_runtime / 'revision-current.json'),
    native_da_rrr=load(revision_runtime / 'revision-scoring-current.json'),
    native_scoring_validation=load(revision_runtime / 'revision-scoring-validation.json'),
    qualification='Original PR generators are dependencies, not additional tested reviewer models. GPU/tool preflight is pending reserved capacity; no RRR score is claimed before native grading and full coverage.')
muse_parallel = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018/review_recovery_20261018/parallel_20261018')
record['muse_nvfp4_parallel_review'] = dict(
    controller=load(muse_parallel / 'current.json'),
    validated_handoff=load(muse_parallel / 'prelaunch-validation.json'),
    worker_states={p.stem: load(p) for p in (muse_parallel / 'state').glob('worker-*.json')},
    old_parent_retired=load(muse_parallel / 'old-parent-retired.json'),
    relayed_successor=load(muse_parallel / 'relayed_20261018/current.json'),
    pre_response_transport_reconciliation=load(muse_parallel / 'relayed_20261018/archive-verified.json'),
    qualification='Identical shared NVFP4 weights and pinned runtime. Original288 retained; suffix722 includes16 already sampled good cases plus706 future actual draws. Thirty-two failed positive connectivity probes were proven to precede SDK generation and archived unchanged; they are included in706. Review slots4+4+8, model services and generation/verifier settings unchanged.')
record['muse_bf16']['review_pipeline'] = load(MUSE / 'review_bench/state/current.json')
checkpoint_run = Path('/fsx/home/zhiyuan/.private/nemotron35super/runs/opus48_mix3_20261014')
record['trained_checkpoint_control'] = dict(
    early95_same_fixed_expanded_first_round_bounds=load(checkpoint_run / 'base_matched_validation_20261017/state/early95-expanded-base-bounds-summary.json'),
    early9_full_pro_same_fixed_control=load(checkpoint_run / 'base_matched_validation_20261017/state/full-pro-fixed-control-paired-summary.json'),
    early9_supplemental_report_aggregation=load(checkpoint_run / 'early9_full_validation_20261017/state/report-aggregation-current.json'),
    early9_never_started_deep_remainder_handoff=load(checkpoint_run / 'early9_full_validation_20261017/deep_parallel_remainder_20261018/current.json'),
    early9_deep_same_client_boundary_control=load(checkpoint_run / 'early9_full_validation_20261017/deep_parallel_remainder_20261018/same-client-boundary-control.json'))
early9_client = checkpoint_run / 'early9_full_validation_20261017/deep_parallel_remainder_20261018/mcp_dependency_recovery_20261018'
record['trained_checkpoint_control']['early9_client_infrastructure_recovery'] = dict(
    current=load(early9_client / 'current.json'),
    excluded_pre_response_phase=load(early9_client / 'invalid-phase-preserved.json'),
    prior94_full_deep_client_audit=load(early9_client / 'prior94-client-audit.json'),
    fixed24_base_early9_client_audit=load(early9_client / 'fixed24-client-audit.json'),
    actual_returned_thinking=load(early9_client / 'actual-returned-thinking-observed.json'))
recovery = checkpoint_run / 'checkpoint_selection/artifact_recovery_20261018'
backup469 = load(recovery / 'mix469-backup-verified.json')
record['trained_checkpoint_artifact_recovery'] = dict(
    mix469_inference_backup_verified=bool(backup469 and backup469.get('verified')),
    mix469_backup_tensor_count=backup469.get('tensor_count') if backup469 else None,
    mix469_backup_bytes=backup469.get('total_bytes') if backup469 else None,
    mix469_backup_receipt=str(recovery / 'mix469-backup-verified.json'),
    mix469_persistent_data_volume_copy=load(Path('/fsx/data/zhiyuan/.private/nemotron35super/opus48_mix3_20261014/mix469/current.json')),
    mix469_persistent_complete_verified=load(recovery / 'mix469-persistent-backup-verified.json'),
    mix469_persistent_completion_audit=load(recovery / 'mix469-persistent-completion-audit.json'),
    original449_469_partial_weight_comparison=load(recovery / 'original449-469-weight-samples/combined.json'),
    mix449_original_file_recovery=load(recovery / 'salvage-current.json'),
    mix449_persistent_partial_archive=load(checkpoint_run / 'checkpoint_selection/retained_models/mix449-partial-native-zstd-20261018/current.json'),
    mix449_persistent_partial_archive_complete=load(recovery / 'mix449-partial-persistent-backup-verified.json'),
    mix449_receiver_independent_archive=load(recovery / 'durable-source-archive-20261018/current.json'),
    mix449_receiver_independent_archive_deployment=load(recovery / 'durable-source-archive-20261018/deployment-verified.json'),
    qualification='Artifact recovery only. A preserved inference export is not proof of better evaluation performance. Frozen early9/mix449 Top2 is unchanged. CPU-only salvage requests are separate from GPU evaluation allocations.')
late = checkpoint_run / 'checkpoint_selection/original_late_validation_20261018'
record['trained_checkpoint_next_fixed_control'] = dict(
    comparison=load(late / 'current.json'),
    queue_states={tag: load(late / tag / 'state/current.json') for tag in ['mix449', 'mix469']},
    original449_export=load(recovery / 'inference-export-449/current.json'),
    original449_export_controller=load(recovery / 'inference-export-449/controller-current.json'),
    original449_inference_ready=load(recovery / 'mix449-inference-export-verified.json'),
    qualification='Same fixed base128/24/24 sample. Original449 remains primary; original469 supplemental only. Old sampled clients must finish before an exact GPU handoff. Original449 native shards remain preserved; a verified inference export is required before loading.')
record['controller_states'] = {}
for name in [
    'opus47-pro-full-20261018', 'opus47-deep-full-three-rounds-20261018',
    'opus47-tb-native-counter-three-rounds-20261018',
    'beam-pro-initial128-20261018', 'beam-tb-initial24-20261018', 'beam-deep-initial24-20261018',
    'beam-pro-full-rounds-continuation-20261018', 'beam-tb-full-rounds-continuation-20261018',
    'beam-deep-full-rounds-continuation-20261018', 'expanded-beam-muse-bf16-capacity-20261018',
    'expanded-beam-reserve-serving-20261018', 'muse-bf16-paired-runtime-controller-20261018',
    'muse-bf16-native-benchmark-start-20261018', 'muse-bf16-review-after-pro-controller-20261018',
    'swe-review-original-generator-runtime-controller-20261018',
    'swe-review-original-revision-controller-20261018', 'swe-review-native-da-rrr-audit-20261018',
    'mix449-original-inference-export-controller-20261018',
    'mix449-retained-file-salvage-controller-20261018',
    'mix449-original32-persistent-archive-20261018',
    'mix469-original-persistent-data-backup-20261018',
    'mix3-original-mix449-expanded-queue-20261018', 'mix3-original-mix469-expanded-queue-20261018',
    'mix3-original-late-fixed-control-audit-20261018',
    'mix3-early9-deep-parallel-handoff-controller-20261018',
    'mix3-early9-deep-safe-boundary-20261018',
    'mix3-early9-deep-safe-boundary-v2-20261018',
    'mix3-early9-mcp-recovery-controller-20261018',
    'beam-tb-first-round-client-protocol-recovery-controller-20261018',
    'beam-tb-first-round-client-protocol-recovery-native-20261018',
    'muse-swe-review-three-replica-supervisor-20261018',
    'muse-swe-review-three-replica-remaining-20261018',
    'muse-swe-review-relayed-three-replica-20261018',
    'muse-swe-review-relayed-supervisor-20261018',
    'muse-nvfp4-node2869-model-relay-20261018']:
    result = subprocess.run(['systemctl', '--user', 'show', name, '-p', 'MainPID',
        '-p', 'ActiveState', '-p', 'Result'], capture_output=True, text=True, timeout=10)
    record['controller_states'][name] = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
record['qualification'] = 'Muse BF16 and NVFP4 are separate original checkpoints and result sets. Raw returned reasoning retained. Pending nodes are not counted as active GPUs. TB and Deep stop at three valid rounds; Pro is one full first round.'
p = BEAM / 'expanded-current.json'
temp = p.with_name(p.name + '.' + str(os.getpid()) + '.tmp')
temp.write_text(json.dumps(record, indent=2) + '\n')
temp.replace(p)
print(json.dumps(record))
