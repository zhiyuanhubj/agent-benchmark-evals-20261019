#!/usr/bin/env python3
"""Real-KV decode-only windows with all cohort members actively generating.

Each cohort receives real prefill. Its measured interval starts after the last
first token and ends before the first last token. No requests are admitted in
that interval. Aggregate actual native output increments over disjoint valid
intervals; prefill and refill gaps never enter the decode denominator.
"""
import argparse
import asyncio
import gzip
import json
import math
import statistics
import time
from pathlib import Path

import httpx
from native_client import Prompts, Round, distribution, save


def decode_window(rows, gpus, guard_tokens=64):
    if not rows or any(not r['valid'] for r in rows):
        return {'valid': False, 'reason': 'request_failure', 'failed_requests': sum(not r['valid'] for r in rows)}
    # Trim 64 output tokens from both ends of every stream, beyond the warmup,
    # to exclude first-decode transients and transport-delayed completion tails.
    start = math.nextafter(max(r['started'] + next(t for t,n in r['token_timing'] if n >= 1+guard_tokens) for r in rows), math.inf)
    end = min(r['started'] + next(t for t,n in r['token_timing'] if n >= r['meta']['completion_tokens']-guard_tokens) for r in rows)
    if end <= start:
        return {'valid': False, 'reason': 'no_full_resident_decode_interval'}
    total, speeds, tpots = 0, [], []
    for r in rows:
        previous, selected = 0, []
        for relative, cumulative in r['token_timing']:
            t = r['started'] + relative
            if start <= t < end:
                total += cumulative - previous
                selected.append((t, cumulative))
            previous = cumulative
        if len(selected) < 2 or selected[-1][0] <= selected[0][0]:
            return {'valid': False, 'reason': 'insufficient_decode_events_for_every_request'}
        tpot = (selected[-1][0] - selected[0][0]) / (selected[-1][1] - selected[0][1])
        tpots.append(tpot); speeds.append(1 / tpot)
    seconds = end - start
    return {'valid': True, 'start_monotonic': start, 'end_monotonic': end,
            'decode_seconds': seconds, 'actual_output_tokens': total,
            'output_tokens_s_gpu': total / seconds / gpus,
            'request_decode_speeds': speeds, 'request_tpots_s': tpots,
            'requests': len(rows), 'failed_requests': 0}


def counters(body):
    result = {}
    for line in body.splitlines():
        if not line or line.startswith('#'):
            continue
        key = line.split('{', 1)[0].split(' ', 1)[0]
        if key in ('sglang:num_retracted_reqs', 'sglang:max_total_num_tokens',
                   'sglang:max_total_num_tokens_swa', 'sglang:num_running_reqs', 'sglang:num_queue_reqs'):
            result.setdefault(key, []).append(float(line.rsplit(' ', 1)[-1]))
    return result


class DecodeRound(Round):
    async def measure(self, client, prompts):
        self.directory.mkdir(parents=True, exist_ok=False)
        save(self.directory / 'server-before.json', (await client.get(self.args.base + '/server_info')).json())
        r = await client.post(self.args.base + '/flush_cache', params={'timeout':30});r.raise_for_status()
        self.raw = gzip.open(self.directory / 'requests.jsonl.gz', 'wt')
        monitor = asyncio.create_task(self.telemetry(client))
        windows, warm, successes, phase, index = [], 0., 0, 'warmup', 0
        batches = gzip.open(self.directory / 'batches.jsonl.gz', 'wt')
        began = time.perf_counter()
        try:
            while True:
                before = await client.get(self.args.base + '/metrics'); before.raise_for_status()
                before = counters(before.text)
                rows = await asyncio.gather(*(self.request(client, prompts, f'{phase}-{index}-{i}') for i in range(self.c)))
                after = await client.get(self.args.base + '/metrics');after.raise_for_status()
                after = counters(after.text)
                w = decode_window(rows, self.args.gpus)
                retracted_before = before.get('sglang:num_retracted_reqs')
                retracted_after = after.get('sglang:num_retracted_reqs')
                if retracted_before is None or retracted_after is None or sum(retracted_after) != sum(retracted_before):
                    w.update(valid=False, reason='KV_retraction_or_missing_retraction_counter')
                if w['valid'] and not self.scenario['cache'] and any(r['meta'].get('cached_tokens', 0) for r in rows):
                    w.update(valid=False, reason='unexpected_prefix_cache_hit')
                w.update(batch=index, phase=phase, metrics_before=before, metrics_after=after,
                         attempted_requests=len(rows), native_successes=sum(r['valid'] for r in rows),
                         native_failures=sum(not r['valid'] for r in rows),
                         all_native_output_tokens=sum(r['meta'].get('completion_tokens',0) for r in rows),
                         unix_offset=self.epoch_offset)
                batches.write(json.dumps(w)+'\n');batches.flush();index += 1
                if not w['valid']:
                    save(self.directory / 'INVALID.json', w)
                    raise RuntimeError(w['reason'])
                if phase == 'warmup':
                    warm += w['decode_seconds']
                    if warm >= self.args.warmup:
                        phase = 'measurement'
                else:
                    windows.append(w);successes += len(rows)
                save(self.directory / 'progress.json', {'phase':phase, 'decode_seconds':sum(w['decode_seconds'] for w in windows),
                     'warmup_decode_seconds':warm, 'successful_measured_requests':successes, 'batches':index})
                if sum(w['decode_seconds'] for w in windows) >= self.args.seconds and successes >= self.args.min_samples:
                    break
                if time.perf_counter() - began > 7200:
                    raise RuntimeError('Two-hour point safety limit; incomplete point retained')
        finally:
            self.stop = True
            await monitor
            self.raw.close();batches.close()
        duration = sum(w['decode_seconds'] for w in windows)
        tokens = sum(w['actual_output_tokens'] for w in windows)
        speeds = [s for w in windows for s in w['request_decode_speeds']]
        measured = [r for r in self.rows if str(r['worker']).startswith('measurement-')]
        spec = [r['meta'] for r in measured if r['meta'].get('spec_verify_ct')]
        verifies = sum(m['spec_verify_ct'] for m in spec)
        result = {'measurement_kind':'real_KV_full_resident_decode_only_windows',
                  'precision':self.args.precision, 'gpus':self.args.gpus, 'scenario':self.scenario,
                  'concurrency':self.c,'repeat':self.repeat,'valid':True,
                  'warmup_decode_seconds':warm,'decode_seconds':duration,'actual_output_tokens':tokens,
                  'output_tokens_s_gpu':tokens/duration/self.args.gpus,
                  'request_decode_speed':distribution(speeds), 'request_decode_speeds':speeds,
                  'tpot_s':distribution([s for w in windows for s in w['request_tpots_s']]),
                  'ttft_s':distribution([r['ttft_s'] for r in measured]),
                  'e2e_s':distribution([r['e2e_s'] for r in measured]),
                  'successful_measured_requests':len(measured),'failed_measured_requests':0,
                  'warmup_requests':len(self.rows)-len(measured),'windows':windows,
                  'prompt_tokens':sum(r['meta']['prompt_tokens'] for r in measured),
                  'output_tokens_full_requests':sum(r['meta']['completion_tokens'] for r in measured),
                  'spec_verify_steps':verifies,
                  'spec_accept_length':sum(m['completion_tokens'] for m in spec)/verifies if verifies else None,
                  'output_includes_reasoning_and_answer':True,'prefill_refill_and_tail_time_in_decode_denominator':False}
        if self.scenario['speculative'] != 'off' and not verifies:
            result['valid'] = False; result['invalid_reason'] = 'Missing native speculative verification counters'
        save(self.directory / 'summary.json', result)
        print(json.dumps({k:result[k] for k in ('precision','concurrency','repeat','valid','decode_seconds','output_tokens_s_gpu')}),flush=True)
        return result


async def main(args):
    corpus = [json.loads(s) for s in args.corpus.read_text().splitlines()]
    scenario = {'workload':args.workload,'input_tokens':args.input_tokens,'cache':False,'speculative':args.speculative}
    if args.input_range:
        scenario.update(input_range=list(args.input_range), input_label=f'native-{args.input_range[0]}-{args.input_range[1]}')
    async with httpx.AsyncClient(trust_env=False,timeout=httpx.Timeout(600,connect=30),
              limits=httpx.Limits(max_connections=1024,max_keepalive_connections=512)) as client:
        info=(await client.get(args.base+'/server_info')).json()
        assert info['disable_radix_cache'] and info['kv_cache_dtype']=='fp8_e4m3'
        assert (info.get('speculative_algorithm') or 'off') == args.speculative
        save(args.output/'CONFIG.json',{'args':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},'server_info':info})
        prompts=await Prompts.build(client,args.base,corpus,scenario,20261029)
        save(args.output/'PROMPTS.json',{'templates':prompts.templates,'scenario':scenario,'seed':20261029})
        curve=[]
        cs=[int(c) for c in args.concurrency.split(',')]
        for c in cs:
            repeats=5 if args.precision=='nvfp4' and args.input_tokens==8192 and c in (4,8) else 3
            group=[]
            for repeat in range(repeats):
                directory=args.output/f'c{c:03d}-r{repeat}'
                if (directory/'summary.json').exists():
                    result=json.loads((directory/'summary.json').read_text())
                else:
                    prompts.sequence=0
                    result=await DecodeRound(args,scenario,c,repeat,directory).measure(client,prompts)
                group.append(result);curve.append(result)
            if any(not r['valid'] for r in group) or max(r['tpot_s']['p95'] for r in group)>.3:
                save(args.output/'DECODE_BOUNDARY.json',{'concurrency':c,'reason':'invalid_point_or_TPOT_p95_over_300ms'});break
        save(args.output/'DONE.json',{'rounds':len(curve),'valid_rounds':sum(r['valid'] for r in curve)})


def parser():
    p=argparse.ArgumentParser()
    p.add_argument('--base',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--precision',required=True);p.add_argument('--gpus',type=int,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--input-tokens',type=int,default=8192)
    p.add_argument('--workload',choices=['synthetic','coding'],default='synthetic')
    p.add_argument('--input-range',type=int,nargs=2)
    p.add_argument('--speculative',choices=['off','NGRAM'],default='off')
    p.add_argument('--concurrency',default='1,2,4,8,16,32,64,128,256')
    p.add_argument('--seconds',type=float,default=120);p.add_argument('--warmup',type=float,default=60)
    p.add_argument('--min-samples',type=int,default=32)
    return p


if __name__=='__main__':asyncio.run(main(parser().parse_args()))
