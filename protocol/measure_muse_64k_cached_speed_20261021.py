#!/usr/bin/env python3
"""Synthetic 64K/400-token cached-prefix probe; not a Dynamo trace reproduction."""
import asyncio
import argparse
import hashlib
import json
import statistics
import time
import uuid
from datetime import datetime, timezone

import httpx
from protocol import measure_muse_serving_speed_20261021 as stream

TARGET = 'nvfp4_direct'
BASE = 'http://10.1.76.28:31320'
MODEL = 'muse-spark-open-nvfp4'
LINE = 'The stored record contains a number and a label.\n'
COMMON = 'Unique agent probe session '+uuid.uuid4().hex+'\n'+LINE*5740
ROWS, BATCHES, CHECKS = [], [], []


def body(text, max_tokens=400):
    return {'model':MODEL, 'messages':[{'role':'user','content':text}],
            'max_tokens':max_tokens,'temperature':0,'stream':True,
            'stream_options':{'include_usage':True},'ignore_eos':True,
            'chat_template_kwargs':{'reasoning_effort':'xhigh'}}


def full_body():
    return body(COMMON+'New agent turn '+uuid.uuid4().hex+'\n'+LINE*640+
                '\nExplain the invariant of binary search and give pseudocode.')


async def tokenize(client, value):
    response=await client.post(BASE+'/tokenize',json={k:value[k] for k in ('model','messages','chat_template_kwargs')})
    response.raise_for_status()
    return response.json()


async def cache_check(client, common_ids, label):
    payload={'input_ids':common_ids,'sampling_params':{'max_new_tokens':1,'temperature':0,'ignore_eos':True},'stream':False}
    response=await client.post(BASE+'/generate',json=payload)
    response.raise_for_status()
    value=response.json()
    meta=value.get('meta_info') or {}
    check={'label':label,'prompt_tokens':meta.get('prompt_tokens'),
           'cached_tokens':meta.get('cached_tokens'),'all_meta':meta}
    CHECKS.append(check)
    stream.write(stream.OUT/(label+'.cache-check.json'),value)
    return check


async def batch(client, concurrency, repeat):
    label=f'{TARGET.split("_")[0]}-64k-shared90-c{concurrency}-r{repeat}'
    check=await cache_check(client,COMMON_IDS,label)
    started=time.perf_counter()
    rows=await asyncio.gather(*(stream.request(client,TARGET,label+f'-q{i}','synthetic_64k_shared90',
                                              400,full_body()) for i in range(concurrency)))
    elapsed=time.perf_counter()-started
    assert all(r['valid'] and r['usage']['completion_tokens']==400 for r in rows),rows
    entry={'concurrency':concurrency,'repeat':repeat,'requests':concurrency,'wall_s':elapsed,
           'output_tokens_per_second':sum(r['usage']['completion_tokens'] for r in rows)/elapsed,
           'common_prefix_check':check,'request_ids':[r['request'] for r in rows]}
    ROWS.extend(rows);BATCHES.append(entry)
    print(json.dumps({'batch':label,'ttft_p50_s':statistics.median(r['ttft_including_reasoning_s'] for r in rows),
          'decode_p50_tokens_per_second':statistics.median(r['decode_tokens_per_second'] for r in rows),
          'batch_output_tokens_per_second':entry['output_tokens_per_second'],
          'cached_common_prefix_tokens':check['cached_tokens']}),flush=True)


async def main():
    global COMMON_IDS
    async with httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(600,connect=15),
                                 limits=httpx.Limits(max_connections=24)) as client:
        seed=full_body()
        common=await tokenize(client,body(COMMON));full=await tokenize(client,seed)
        COMMON_IDS=common['tokens']
        shared=0
        for a,b in zip(COMMON_IDS,full['tokens']):
            if a!=b:break
            shared+=1
        shape={'common_prompt_tokens':common['count'],'full_prompt_tokens':full['count'],
               'common_prefix_tokens':shared,'nominal_shared_prefix_fraction':shared/full['count']}
        assert 62000<=full['count']<=66000 and .89<=shape['nominal_shared_prefix_fraction']<=.91,shape
        print('SHAPE',json.dumps(shape),flush=True)
        cold=await stream.request(client,TARGET,TARGET.split('_')[0]+'-64k-cold-baseline','synthetic_64k_cold',400,seed)
        assert cold['valid'],cold
        print('COLD',json.dumps({k:cold[k] for k in ('ttft_including_reasoning_s','decode_tokens_per_second','usage')}),flush=True)
        for repeat in range(3):await batch(client,1,repeat)
        for concurrency in (4,8,12,16):await batch(client,concurrency,0)
    summary={}
    for concurrency in (1,4,8,12,16):
        batches=[b for b in BATCHES if b['concurrency']==concurrency]
        ids={name for b in batches for name in b['request_ids']}
        rows=[r for r in ROWS if r['request'] in ids]
        summary[str(concurrency)]={'requests':len(rows),'valid_requests':sum(r['valid'] for r in rows),
            'ttft_p50_ms':1000*statistics.median(r['ttft_including_reasoning_s'] for r in rows),
            'ttft_max_ms':1000*max(r['ttft_including_reasoning_s'] for r in rows),
            'decode_tokens_per_second_p50':statistics.median(r['decode_tokens_per_second'] for r in rows),
            'e2e_output_tokens_per_second_p50':statistics.median(r['e2e_output_tokens_per_second'] for r in rows),
            'e2e_p50_s':statistics.median(r['e2e_s'] for r in rows),
            'batch_output_tokens_per_second':[b['output_tokens_per_second'] for b in batches],
            'prompt_tokens':[r['usage']['prompt_tokens'] for r in rows]}
    trace=stream.BASE/'.private/muse_openai_api_20261021/reference-agentic-trace.jsonl'
    assert all((check['cached_tokens'] or 0)>=shape['common_prefix_tokens'] for check in CHECKS)
    trace_rows=[json.loads(line) for line in trace.read_text().splitlines()]
    target=stream.TARGETS[TARGET]
    result={'generated_utc':datetime.now(timezone.utc).isoformat(),'hardware':f"{target['gpus']}x H200",
        'framework':'SGLang Muse adaptation 0.0.0.dev0','precision':target['precision']+' weights + FP8 KV cache',
        'max_running_requests':8,'shape':shape,'summary':summary,'cold_baseline':cold,
        'native_common_prefix_checks':CHECKS,'batches':BATCHES,'requests':ROWS,'raw_artifacts':str(stream.OUT),
        'reference':{'official_url':'https://docs.nvidia.com/dynamo/dev/recipes/Muse-Spark-Open',
            'trace_sha256':hashlib.sha256(trace.read_bytes()).hexdigest(),'trace_requests':3541,
            'trace_input_tokens_mean':statistics.mean(r['input_length'] for r in trace_rows),
            'trace_input_tokens_p50':statistics.median(r['input_length'] for r in trace_rows),
            'trace_output_tokens_mean':statistics.mean(r['output_length'] for r in trace_rows),
            'trace_output_tokens_p50':statistics.median(r['output_length'] for r in trace_rows),
            'used_for_replay':False},
        'qualification':'Synthetic approximately 64K input, 400 output, 90% common-prefix requests with '
            'native common-prefix cache checks. Existing Pro clients continue sharing the same replica. '
            'Incoming concurrency may exceed the backend limit of eight. Not AIPerf, not the original '
            '3,541-request trace, not an isolated or equal-hardware comparison with NVIDIA. '
            'The OpenAI route does not report per-request cached_tokens; native checks show common-prefix '
            'cache residency, not a per-request measured 90% hit rate. TTFT includes returned thinking.',
        'target':TARGET}
    filename=('muse_bf16_64k_cached_speed_20261021.json' if TARGET=='bf16_direct'
              else 'muse_64k_cached_speed_20261021.json')
    stream.write(stream.ROOT/'evidence'/filename,result)
    print('SUMMARY',json.dumps(summary),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=('nvfp4_direct','bf16_direct'), default='nvfp4_direct')
    args=parser.parse_args()
    TARGET=args.target
    BASE=stream.TARGETS[TARGET]['url'].removesuffix('/v1')
    MODEL=stream.TARGETS[TARGET]['model']
    asyncio.run(main())
