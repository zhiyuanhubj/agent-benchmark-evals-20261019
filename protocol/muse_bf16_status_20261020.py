"""Read-only, precision-specific readiness check for the queued BF16 run."""
from pathlib import Path
import datetime
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent
CAPACITY = Path('/fsx/home/zhiyuan/.private/beam_20261018/expanded_capacity_20261018')
MANUAL = ROOT / 'manual_pair_2865_2869_20261019'
REPLICA_2886 = ROOT / 'manual_pair_2886_20261019'
JOB = '2886'


def read(path):
    return json.loads(path.read_text()) if path.exists() else None


def active(unit):
    result = subprocess.run(['systemctl', '--user', 'is-active', unit],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and result.stdout.strip() == 'active'


queue = subprocess.run(['squeue', '-u', 'zhiyuan', '-h', '-j', JOB,
                        '-o', '%i|%u|%j|%T|%D|%N|%S'],
                       capture_output=True, text=True, timeout=15, check=True)
rows = [line.split('|') for line in queue.stdout.splitlines() if line.strip()]
assert len(rows) <= 1 and (not rows or rows[0][0] == JOB)
job = dict(zip(['id', 'owner', 'name', 'state', 'nodes', 'host_expression',
                'estimated_start'], rows[0])) if rows else None
stage = read(ROOT / 'stage_2869/prefetch-current.json')
verification = read(ROOT / 'stage_2869/muse_bf16-verification.json')
source_ready = bool(stage and stage.get('complete') and verification and
                    verification.get('complete') and len(verification.get('verified_files', [])) == 78 and
                    stage.get('models', {}).get('muse_bf16', {}).get('index_shards') == 65)
claim_paths = [CAPACITY / f'allocation-{JOB}-rank-{rank}/launch-claim.json'
               for rank in (0, 1)]
claims = [read(path) for path in claim_paths]
pair_launch = read(ROOT / 'pair-unit-launch.json')
endpoint = read(ROOT / 'endpoint-ready.json')
preflight = read(ROOT / 'native-preflight-ready.json')
review_current = read(ROOT / 'review_bench/state/current.json') or {}
manual_prefetch = read(MANUAL / 'prefetch-current.json') or {}
manual_progress = read(MANUAL / 'cutover-current.json')
manual_cutover = read(MANUAL / 'cutover-complete.json')
manual_endpoint = read(MANUAL / 'endpoint-ready.json')
manual_retry = read(MANUAL / 'retry2-current.json') or read(MANUAL / 'retry1-current.json')
replica_2886_endpoint = read(REPLICA_2886 / 'endpoint-ready.json')
replica_2886_preflight = read(REPLICA_2886 / 'native-preflight-ready.json')
replica_2886_weights = [read(CAPACITY / f'allocation-{JOB}-rank-{rank}/prefetch-current.json')
                        for rank in (0, 1)]
retry_controller_active = active('muse-bf16-manual-retry1-controller-20261019') or active('muse-bf16-manual-retry2-controller-20261019')
unit_names = {
    'capacity': 'expanded-beam-muse-bf16-capacity-20261018',
    'pair': 'muse-bf16-paired-runtime-controller-20261018',
    'benchmark': 'muse-bf16-native-benchmark-start-20261018',
    'review': 'muse-bf16-review-after-pro-controller-20261018',
}
units = {key: active(name) for key, name in unit_names.items()}
units['review'] = (units['review'] or active('muse-bf16-review-after-pro-controller-20261019')
                   or active('muse-bf16-review-on-2886-v2-20261019')
                   or active('muse-bf16-swrbench-20261018')
                   or active('muse-bf16-swe-review-20261018'))
units['replica_2886_rank0'] = active('muse-bf16-pair-2886-rank0-20261019')
units['replica_2886_rank1'] = active('muse-bf16-pair-2886-rank1-20261019')
complete = {kind: bool(read(ROOT / f'legacy_bench/state/{kind}-complete.json'))
            for kind in ('pro', 'tb', 'deep')}
recovery_root = ROOT / 'recovery_20261020'
recovery_claim = read(recovery_root / 'bridge-and-resume-claim.json')
recovery_backup = read(recovery_root / 'interrupted-original-dirs-manifest.json')
bridge_preflight_path = ROOT / 'legacy_bench/state/endpoint-bridge-preflight.json'
bridge_preflight = read(bridge_preflight_path)
replica_proof_path = REPLICA_2886 / 'endpoint-ready.json'
recovery_units = {
    'pro': 'muse-bf16-pro-r1-reuse-tmpfix-2922-20261020.service',
    'tb': 'muse-bf16-tb-r1-resume-2919-20261020.service',
    'deep': 'muse-bf16-deep-r1-resume-2922-20261020.service',
}
recovery_active = {kind: active(unit) for kind, unit in recovery_units.items()}
direct_units = {
    'pro': 'muse-bf16-pro-r1-direct-2886-20261020.service',
    'tb': 'muse-bf16-tb-r1-direct-2886-20261020.service',
    'deep': 'muse-bf16-deep-r1-direct-2886-20261020.service',
}
direct_active = {kind: active(unit) for kind, unit in direct_units.items()}
bridge_active = active('muse-bf16-endpoint-bridge-2869-to-2886-20261020.service')
recovery_verified = bool(
    recovery_claim and recovery_backup and bridge_preflight and replica_2886_endpoint
    and recovery_claim.get('original_endpoint') == 'http://10.1.77.106:31324/v1'
    and recovery_claim.get('bridge_to_verified_2886_endpoint') == replica_2886_endpoint.get('api_base')
    and bridge_preflight.get('model') == 'muse-spark-open-bf16'
    and bridge_preflight.get('nonempty_reasoning')
    and bridge_preflight.get('excluded_from_benchmarks')
    and hashlib.sha256(bridge_preflight_path.read_bytes()).hexdigest() ==
        recovery_claim['endpoint_provenance']['bridge_preflight_sha256']
    and hashlib.sha256(replica_proof_path.read_bytes()).hexdigest() ==
        recovery_claim['endpoint_provenance']['2886_ready_sha256']
    and hashlib.sha256((recovery_root / 'interrupted-original-dirs-manifest.json').read_bytes()).hexdigest() ==
        recovery_claim['interrupted_native_trial_backup_manifest_sha256']
    and all(hashlib.sha256(Path(recovery_backup['jobs'][kind]['archive']).read_bytes()).hexdigest() ==
            recovery_backup['jobs'][kind]['archive_sha256'] for kind in ('tb', 'deep'))
)
bridge_expiry_plan_path = recovery_root / 'bridge-2869-expiry-stop-plan.json'
bridge_expiry_plan = read(bridge_expiry_plan_path)
old_allocation_state = subprocess.run(
    ['sacct', '-n', '-P', '-j', '2869', '--format=JobIDRaw,State,End'],
    capture_output=True, text=True, timeout=15)
expired_rows = [line.split('|') for line in old_allocation_state.stdout.splitlines() if line.startswith('2869|')]
bridge_expiry_verified = bool(
    bridge_expiry_plan and recovery_verified and replica_2886_endpoint
    and old_allocation_state.returncode == 0 and len(expired_rows) == 1
    and expired_rows[0][1] == 'TIMEOUT'
    and expired_rows[0][2].startswith('2026-10-20T16:00:')
    and bridge_expiry_plan['old_allocation'] == 2869
    and bridge_expiry_plan['old_endpoint'] == recovery_claim['original_endpoint']
    and bridge_expiry_plan['verified_live_model_endpoint'] == replica_2886_endpoint['api_base']
    and not bridge_active and not any(recovery_active.values())
    and all(hashlib.sha256(Path(row['config']).read_bytes()).hexdigest() == row['config_sha256']
            for row in bridge_expiry_plan['harbor'])
)
problems = []
if not source_ready:
    problems.append('Original BF16 staged source verification missing')
if not job and not all(complete.values()):
    problems.append('Paired BF16 allocation 2886 disappeared before native benchmarks completed')
if job and (job['owner'] != 'zhiyuan' or job['name'] != 'muse-bf16-pair-2886'
            or job['state'] not in ('PENDING', 'RUNNING') or job['nodes'] != '2'):
    problems.append('Paired allocation ownership, topology or state changed')
if not all(claims) and not units['capacity']:
    problems.append('Capacity controller stopped before both paired nodes were claimed')
for rank, claim in enumerate(claims):
    if not claim:
        continue
    directory = claim_paths[rank].parent
    launched = read(directory / 'launch-exit.json')
    prefetched = read(directory / 'prefetch-current.json') or {}
    if launched and not prefetched.get('complete') and not active(claim['unit']):
        problems.append(f'BF16 rank {rank} weight prefetch stopped before verification')
if not pair_launch and not units['pair'] and not (MANUAL / 'cutover-intent.json').exists():
    problems.append('Paired runtime controller stopped before model launch')
if pair_launch and not all(complete.values()) and not active(pair_launch['unit']):
    problems.append('Paired BF16 model unit stopped before native benchmarks completed')
if manual_cutover and not manual_endpoint:
    for rank in (0, 1):
        if not (active(f'muse-bf16-manual-rank{rank}-2865-2869-20261019') or
                active(f'muse-bf16-manual-rank{rank}-retry1-2865-2869-20261019') or
                active(f'muse-bf16-manual-rank{rank}-retry2-2865-2869-20261019')):
            problems.append(f'Manual BF16 rank {rank} stopped before endpoint became ready')
if (MANUAL / 'pair-plan.json').exists() and read(MANUAL / 'pair-plan.json').get('cutover_allowed'):
    if not manual_endpoint and not (active('muse-bf16-manual-cutover-v2-20261019') or
                                    active('muse-bf16-manual-retry1-controller-20261019') or
                                    active('muse-bf16-manual-retry2-controller-20261019')):
        problems.append('Manual BF16 cutover controller stopped before endpoint became ready')
if endpoint and endpoint.get('precision') != 'BF16':
    problems.append('Endpoint precision is not BF16')
if not preflight and not units['benchmark'] and not (retry_controller_active and not endpoint):
    problems.append('Native benchmark controller stopped before tool/thinking preflight')
if preflight:
    for kind in ('pro', 'tb', 'deep'):
        launched = read(ROOT / f'legacy_bench/state/{kind}-unit-launch.json')
        if not launched and not units['benchmark']:
            problems.append(f'Native {kind} controller was never launched')
        if launched and not complete[kind] and not active(launched['unit']) and not (
                (recovery_verified and bridge_active and recovery_active[kind])
                or bridge_expiry_verified):
            problems.append(f'Native {kind} controller stopped before completion')
if (review_current.get('phase') not in ('native_swr_generation_judging_and_review_pipeline_started',
                                      'verified_2886_swr_generation_judging_and_review_pipeline_started')
        and not units['review'] and not (retry_controller_active and not endpoint)):
    problems.append('Review controller stopped before independent BF16 review launch')
record = {
    'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'precision': 'BF16', 'model_repo': 'meta-models/Muse-Spark-Open-816B-A42B',
    'revision': '0fb02478b02565b2ce7fc57e6051c91172774ac9',
    'job': job, 'verified_staged_source': source_ready,
    'paired_node_claims': [bool(claim) for claim in claims],
    'paired_runtime_launched': bool(pair_launch) or bool(replica_2886_endpoint),
    'replica_2886': {'weights_verified_both_ranks': all(value and value.get('complete') for value in replica_2886_weights),
                     'endpoint_ready': bool(replica_2886_endpoint),
                     'tool_thinking_preflight_ready': bool(replica_2886_preflight),
                     'review_phase': review_current.get('phase')},
    'manual_pair': {'allocations_by_rank': [2869, 2865],
                    'prefetch_complete': bool(manual_prefetch.get('complete')),
                    'prefetch_completed_gib': round(manual_prefetch.get('models', {}).get('muse_bf16', {}).get('completed_file_bytes', 0) / 2**30, 2),
                    'cutover_phase': manual_progress.get('phase') if manual_progress else None,
                    'cutover_controller_active': active('muse-bf16-manual-cutover-v2-20261019') or
                                                 active('muse-bf16-manual-retry1-controller-20261019') or
                                                 active('muse-bf16-manual-retry2-controller-20261019'),
                    'retry_phase': manual_retry.get('phase') if manual_retry else None,
                    'cutover_complete': bool(manual_cutover), 'endpoint_ready': bool(manual_endpoint)},
    'endpoint_ready': bool(endpoint), 'tool_thinking_preflight_ready': bool(preflight),
    'native_complete': complete, 'controllers_active': units,
    'allocation_expiry_recovery': {
        'verified': recovery_verified, 'bridge_active': bridge_active,
        'replacement_controllers_active': recovery_active,
        'claim': str(recovery_root / 'bridge-and-resume-claim.json') if recovery_claim else None,
        'original_allocation_2865_expired': bool(recovery_claim),
    },
    'bridge_2869_expiry_recovery': {
        'phase': ('direct_endpoint_partial_resume_running' if any(direct_active.values()) else
                  'documented_pause_before_direct_endpoint_resume') if bridge_expiry_verified else 'needs_audit',
        'verified': bridge_expiry_verified,
        'old_allocation_state': expired_rows[0][1] if expired_rows else None,
        'stop_plan': str(bridge_expiry_plan_path) if bridge_expiry_plan else None,
        'previous_controllers_active': recovery_active,
        'direct_controllers_active': direct_active,
        'live_model_endpoint': replica_2886_endpoint.get('api_base') if replica_2886_endpoint else None,
    },
    'model_sampling_started': bool(preflight or (ROOT / 'smoke-tool-first.json').exists()),
    'problems': problems,
    'qualification': ('BF16 native Pro/TB/Deep disjoint unfinished tasks are running on the verified direct 2886 endpoint '
                      'after bridge allocation 2869 expired; earlier samples are preserved. '
                      'BF16 remains separate from NVFP4.' if bridge_expiry_verified and all(direct_active.values()) else
                      'BF16 bridge 2869 expired; direct endpoint recovery is partial or paused. '
                      'Earlier samples are preserved and BF16 remains separate from NVFP4.' if bridge_expiry_verified else
                      'BF16 results remain separate from NVFP4; source staging and pending jobs are not model samples.'),
}
path = ROOT / 'status-current.json'
temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
temporary.write_text(json.dumps(record, indent=2) + '\n')
temporary.replace(path)
print(json.dumps(record))
if problems:
    raise SystemExit(1)
