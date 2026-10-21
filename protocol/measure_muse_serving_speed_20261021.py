#!/usr/bin/env python3
"""Measure client-observed SSE latency under the existing shared evaluation load."""
import asyncio
import json
import statistics
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = Path('/fsx/home/zhiyuan')
ROOT = BASE/'agent-benchmark-evals-20261019'
STAMP = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT = BASE/'.private/muse_openai_api_20261021/performance'/STAMP
OUT.mkdir(parents=True)
TARGETS = {
    'bf16_direct': {'url':'http://10.1.13.41:31324/v1', 'model':'muse-spark-open-bf16', 'precision':'BF16', 'gpus':16},
    'nvfp4_direct': {'url':'http://10.1.76.28:31320/v1', 'model':'muse-spark-open-nvfp4', 'precision':'NVFP4', 'gpus':8},
    'bf16_public': {'url':'https://muse.zhiyuanllm.com/v1', 'model':'muse-spark-open-bf16', 'precision':'BF16', 'gpus':16},
}
ROWS, BATCHES = [], []


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')


async def request(client, target, name, length, output_tokens=256):
    text = ('The stored record contains a number and a label.\n' * (8 if length=='short' else 700))
    prompt = ('Independent performance probe '+uuid.uuid4().hex+'\n'+text+
              '\nExplain the invariant of binary search and give pseudocode. This is a synthetic service probe.')
    body = {'model':TARGETS[target]['model'], 'messages':[{'role':'user','content':prompt}],
            'max_tokens':output_tokens, 'temperature':0, 'stream':True,
            'stream_options':{'include_usage':True}, 'ignore_eos':True,
            'chat_template_kwargs':{'reasoning_effort':'xhigh'}}
    write(OUT/(name+'.request.json'), body)
    events, usage = [], {}
    started = time.perf_counter()
    first_event = first_token = first_answer = last_token = headers_time = None
    delta_events = 0
    done = False
    error = None
    status = None
    try:
        async with client.stream('POST', TARGETS[target]['url']+'/chat/completions', json=body) as response:
            status = response.status_code
            headers_time = time.perf_counter()-started
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                now = time.perf_counter()-started
                payload = line[6:]
                events.append({'time_s':now, 'data':payload})
                if payload=='[DONE]':
                    done=True
                    continue
                event = json.loads(payload)
                if first_event is None:
                    first_event=now
                if event.get('usage'):
                    usage.update(event['usage'])
                for choice in event.get('choices', []):
                    delta = choice.get('delta') or {}
                    if delta.get('reasoning_content') or delta.get('content') or delta.get('tool_calls'):
                        if first_token is None:
                            first_token=now
                        last_token=now
                        delta_events+=1
                    if delta.get('content') and first_answer is None:
                        first_answer=now
    except Exception as exception:
        error=type(exception).__name__
    elapsed = time.perf_counter()-started
    tokens = usage.get('completion_tokens')
    decode_s = last_token-first_token if first_token is not None and last_token is not None else None
    result = {'request':name, 'target':target, 'input_case':length, 'http_status':status,
        'expected_output_tokens':output_tokens, 'usage':usage, 'sse_done':done,
        'headers_s':headers_time, 'first_sse_event_s':first_event,
        'ttft_including_reasoning_s':first_token, 'first_visible_answer_s':first_answer,
        'last_token_s':last_token, 'e2e_s':elapsed, 'nonempty_delta_events':delta_events,
        'decode_tokens_per_second':(tokens-1)/decode_s if tokens and tokens>1 and decode_s else None,
        'mean_time_per_output_token_ms':decode_s/(tokens-1)*1000 if tokens and tokens>1 and decode_s else None,
        'e2e_output_tokens_per_second':tokens/elapsed if tokens else None, 'error':error,
        'valid':status==200 and done and first_token is not None and bool(tokens)}
    with (OUT/(name+'.sse.jsonl')).open('w') as stream:
        for event in events:
            stream.write(json.dumps(event,ensure_ascii=False)+'\n')
    write(OUT/(name+'.result.json'),result)
    return result


async def batch(client, target, length, concurrency, repeat):
    label=f'{target}-{length}-c{concurrency}-r{repeat}'
    started=time.perf_counter()
    rows=await asyncio.gather(*(request(client,target,label+f'-q{i}',length) for i in range(concurrency)))
    elapsed=time.perf_counter()-started
    ROWS.extend(rows)
    entry={'target':target,'input_case':length,'concurrency':concurrency,'repeat':repeat,
           'wall_s':elapsed,'valid_requests':sum(row['valid'] for row in rows),
           'requests':concurrency,'completion_tokens':sum(row['usage'].get('completion_tokens',0) for row in rows)}
    entry['batch_output_tokens_per_second']=entry['completion_tokens']/elapsed
    BATCHES.append(entry)
    print(json.dumps({'batch':label,**entry,'ttft_s':[round(row['ttft_including_reasoning_s'],3)
          if row['ttft_including_reasoning_s'] is not None else None for row in rows]}),flush=True)


async def run_target(target, public_only=False):
    headers={}
    if target=='bf16_public':
        headers['Authorization']='Bearer '+(BASE/'.private/muse_openai_api_20261021/primary.key').read_text().strip()
    async with httpx.AsyncClient(headers=headers,timeout=httpx.Timeout(300,connect=15),
                                 limits=httpx.Limits(max_connections=16),
                                 trust_env=target=='bf16_public') as client:
        warm=await request(client,target,target+'-warmup','short',16)
        assert warm['valid'],warm
        for repeat in range(3):
            await batch(client,target,'short',1,repeat)
        if not public_only:
            for repeat in range(3):
                await batch(client,target,'long',1,repeat)
            for concurrency in (4,8):
                await batch(client,target,'short',concurrency,0)


def summarize():
    groups={}
    for batch_row in BATCHES:
        key=f"{batch_row['target']}/{batch_row['input_case']}/c{batch_row['concurrency']}"
        groups.setdefault(key,[]).append(batch_row)
    summary={}
    for key,batches in groups.items():
        target,length,c=key.split('/')
        labels={f"{target}-{length}-{c}-r{b['repeat']}-q{i}" for b in batches for i in range(b['requests'])}
        rows=[row for row in ROWS if row['request'] in labels]
        stats={}
        for field in ('ttft_including_reasoning_s','e2e_s','decode_tokens_per_second','mean_time_per_output_token_ms','e2e_output_tokens_per_second'):
            values=[row[field] for row in rows if row[field] is not None and row['valid']]
            stats[field]={'median':statistics.median(values),'min':min(values),'max':max(values)} if values else None
        summary[key]={'requests':len(rows),'valid_requests':sum(row['valid'] for row in rows),
            'prompt_tokens':[row['usage'].get('prompt_tokens') for row in rows],
            'completion_tokens':[row['usage'].get('completion_tokens') for row in rows],
            'batch_output_tokens_per_second':[b['batch_output_tokens_per_second'] for b in batches],
            'metrics':stats}
    result={'generated_utc':datetime.now(timezone.utc).isoformat(),'targets':TARGETS,
        'summary':summary,'batches':BATCHES,'requests':ROWS,'raw_artifacts':str(OUT),
        'methodology':{
            'load':'Existing evaluation clients continue sharing the same replicas; not isolated peak capacity.',
            'scheduling':'BF16 direct and NVFP4 direct tests overlap on independent hardware; BF16 public tests run afterward.',
            'generation':'Unique nonce before repeated context avoids complete-prompt prefix-cache hits; output capped/forced to 256 tokens with ignore_eos. Synthetic nonbenchmark requests.',
            'ttft':'Client POST start to first SSE delta with nonempty reasoning_content/content/tool_calls; includes queue, prefill and transport. Empty role chunks are excluded.',
            'visible_answer':'First visible answer is recorded separately; it can be absent in a thinking-only 256-token response.',
            'decode_speed':'(completion_tokens-1)/(last nonempty token-delta time-first nonempty token-delta time); token count is from server usage, not chunk count.',
            'batch_throughput':'Total probe completion tokens divided by batch wall time; excludes unrelated evaluation tokens.',
            'limits':'Three single-request repetitions per input case; one batch each at concurrency 4/8. No p95, long-context SLA, or maximum throughput claim.'}}
    write(ROOT/'evidence/muse_serving_speed_20261021.json',result)
    print('EVIDENCE',str(ROOT/'evidence/muse_serving_speed_20261021.json'),flush=True)


async def main():
    await asyncio.gather(run_target('bf16_direct'),run_target('nvfp4_direct'))
    await run_target('bf16_public',True)
    summarize()


if __name__=='__main__':
    asyncio.run(main())
