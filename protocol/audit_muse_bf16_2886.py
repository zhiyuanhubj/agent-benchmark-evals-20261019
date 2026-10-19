#!/usr/bin/env python3
"""Audit the owned two-node original-BF16 service before its review evaluations."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


HOME = Path('/fsx/home/zhiyuan')
ROOT = Path(__file__).resolve().parents[1]
SOURCE = HOME / '.private/muse_bf16_20261018/stage_2869/muse_bf16-verification.json'
PAIR = HOME / '.private/muse_bf16_20261018/manual_pair_2886_20261019'
STATE = HOME / '.private/beam_20261018/expanded_capacity_20261018'
REVIEW = HOME / '.private/muse_bf16_20261018/review_bench'
REVISION = '0fb02478b02565b2ce7fc57e6051c91172774ac9'
IMAGE = 'lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a'
API = 'http://10.1.13.41:31324/v1'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


source = read(SOURCE)
assert source['complete'] and source['revision'] == REVISION
assert len(source['verified_files']) == 78
source_files = {row['file']: (row['bytes'], row['algorithm'], row['expected'])
                for row in source['verified_files']}
assert len(source_files) == 78

pair_plan_path = PAIR / 'pair-plan.json'
pair_plan = read(pair_plan_path)
assert pair_plan['hosts'] == ['ip-10-1-13-41', 'ip-10-1-122-30']
assert pair_plan['allocations_by_rank'] == [2886, 2886]
assert pair_plan['head_ip'] == '10.1.13.41'
assert pair_plan['image_digest'] == IMAGE and pair_plan['revision'] == REVISION

ranks = []
for rank in (0, 1):
    directory = STATE / f'allocation-2886-rank-{rank}'
    verification_path = directory / 'muse_bf16-verification.json'
    verification = read(verification_path)
    assert verification['complete'] and verification['revision'] == REVISION
    assert verification['verification_method'] == 'read-and-hash-each-existing-or-copied-file'
    assert {row['file']: (row['bytes'], row['algorithm'], row['expected'])
            for row in verification['verified_files']} == source_files
    status_path = directory / 'prefetch-current.json'
    status = read(status_path)
    model = status['models']['muse_bf16']
    assert status['complete'] and model['status'] == 'verified'
    assert model['completed_files'] == 78
    assert model['completed_file_bytes'] == sum(row['bytes'] for row in source['verified_files'])
    runtime_path = directory / 'runtime-image-ready.json'
    runtime = read(runtime_path)
    assert runtime['image'] == IMAGE and len(runtime['rdma_devices']) >= 1
    probe_path = directory / 'manual-nccl-probe-exit.json'
    probe = read(probe_path)
    assert probe['returncode'] == 0
    assert 'NCCL_16_GPU_SUM_AND_128_GATHERS_OK' in (directory / 'nccl-probe.log').read_text()
    launch_path = directory / 'manual-model-launch.json'
    launch = read(launch_path)
    command = launch['command']
    assert launch['precision'] == 'BF16' and launch['revision'] == REVISION
    assert IMAGE in command
    for flag, value in (('--dtype', 'bfloat16'), ('--tp-size', '16'), ('--ep-size', '16'),
                        ('--nnodes', '2'), ('--node-rank', str(rank)),
                        ('--model-path', '/weights'), ('--served-model-name', 'muse-spark-open-bf16')):
        assert command[command.index(flag) + 1] == value
    ranks.append(dict(rank=rank, host=pair_plan['hosts'][rank],
        verification_sha256=sha(verification_path), file_count=78,
        verified_bytes=model['completed_file_bytes'], remaining_disk_bytes=status['available_bytes'],
        runtime_sha256=sha(runtime_path), nccl_probe_sha256=sha(probe_path),
        model_launch_sha256=sha(launch_path)))

endpoint_path = PAIR / 'endpoint-ready.json'
endpoint = read(endpoint_path)
assert endpoint['api_base'] == API and endpoint['model'] == 'muse-spark-open-bf16'
assert endpoint['revision'] == REVISION and endpoint['precision'] == 'BF16'
assert endpoint['allocations_by_rank'] == [2886, 2886]
preflight_path = PAIR / 'native-preflight-ready.json'
preflight = read(preflight_path)
assert preflight['api_base'] == API and preflight['precision'] == 'BF16'
assert preflight['tool_roundtrip'] and preflight['returned_thinking_preserved']
first_path = PAIR / 'nonbenchmark-tool-first.json'
second_path = PAIR / 'nonbenchmark-tool-roundtrip.json'
first = read(first_path)
second = read(second_path)
assert first['excluded_from_benchmarks'] and second['excluded_from_benchmarks']
first_message = first['response']['choices'][0]['message']
second_message = second['response']['choices'][0]['message']
assert first_message['reasoning_content'] and second_message['reasoning_content']
calls = first_message['tool_calls']
assert len(calls) == 1 and calls[0]['function']['name'] == 'multiply'
assert json.loads(calls[0]['function']['arguments']) == {'a': 11, 'b': 13}
assert '143' in (second_message['content'] or '')
assert second['request']['messages'][-1]['content'] == '143'

review_plan_path = REVIEW / 'queue/queue-plan.json'
review_plan = read(review_plan_path)
assert review_plan['api_base'] == API and review_plan['model_allocation'] == 2886
assert review_plan['sandbox_allocation'] == 2886
assert review_plan['sandbox_hostname'] == 'ip-10-1-122-30'
assert str(preflight_path) in review_plan['required_gate_files']
assert len(review_plan['splits']) == 3
swr_launch_path = REVIEW / 'swrbench/launch.json'
swr_launch = read(swr_launch_path)
assert swr_launch['api_base'] == API and swr_launch['expected'] == 1000

evidence = dict(generated_utc=datetime.now(timezone.utc).isoformat(),
    model='meta-models/Muse-Spark-Open-816B-A42B', revision=REVISION,
    precision='original BF16, no NVFP4 cast', image_digest=IMAGE,
    pair_plan_sha256=sha(pair_plan_path), source_verification_sha256=sha(SOURCE),
    source_verified_file_count=78, ranks=ranks,
    endpoint=API, endpoint_receipt_sha256=sha(endpoint_path),
    preflight_receipt_sha256=sha(preflight_path),
    nonbenchmark_tool_first_sha256=sha(first_path),
    nonbenchmark_tool_roundtrip_sha256=sha(second_path),
    review_plan_sha256=sha(review_plan_path),
    review_sandbox_host='ip-10-1-122-30',
    swr_launch_sha256=sha(swr_launch_path),
    qualification='Pinned bytes and native launch receipts audited. These checks prove the serving identity and tool/thinking transport, not benchmark accuracy or clean trajectories.')
target = ROOT / 'evidence/muse_bf16_2886_deployment_audit.json'
target.write_text(json.dumps(evidence, indent=2) + '\n')
print(json.dumps(dict(evidence=str(target), ranks=len(ranks), verified_files=78,
                      review_sandbox_host=evidence['review_sandbox_host'])))
