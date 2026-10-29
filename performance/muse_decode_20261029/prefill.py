#!/usr/bin/env python3
"""Prefill-only cohorts: one real output token, native engine-phase timestamps."""
import asyncio
import gzip
import json
import time

from native_client import Round, distribution, save


def phase_window(rows, gpus):
    if not rows or any(not r['valid'] for r in rows):
        return {'valid':False,'reason':'request_failure'}
    ms=[r['meta'] for r in rows]
    if any(m.get('num_retractions') != 0 or m.get('cached_tokens') != 0 for m in ms):
        return {'valid':False,'reason':'KV_retraction_or_prefix_cache_hit'}
    if any(m.get('forward_entry_time') is None or m.get('prefill_finished_time') is None for m in ms):
        return {'valid':False,'reason':'missing_native_prefill_timestamps'}
    begin=min(m['forward_entry_time'] for m in ms);end=max(m['prefill_finished_time'] for m in ms)
    latencies=[m['prefill_finished_time']-m['forward_entry_time'] for m in ms]
    if end<=begin or any(t<=0 for t in latencies):
        return {'valid':False,'reason':'invalid_native_prefill_timestamps'}
    tokens=sum(m['prompt_tokens'] for m in ms)
    return {'valid':True,'engine_start_unix':begin,'engine_end_unix':end,'engine_seconds':end-begin,
            'actual_input_tokens':tokens,'input_tokens_s_gpu':tokens/(end-begin)/gpus,
            'request_prefill_latencies_s':latencies,'requests':len(rows)}


class PrefillRound(Round):
    async def one(self,client,prompts,phase,index,worker):
        tokens,provenance=prompts.next();start=time.perf_counter();meta={};error=None;status=None
        try:
            r=await client.post(self.args.base+'/generate',json={'input_ids':tokens,'stream':False,
                'sampling_params':{'max_new_tokens':1,'min_new_tokens':1,'ignore_eos':True,
                                   'temperature':1.,'top_p':1.,'top_k':-1}})
            status=r.status_code;r.raise_for_status();data=r.json();meta=data['meta_info']
        except Exception as exc:
            error=type(exc).__name__+': '+str(exc)[:300];data={}
        row={'phase':phase,'batch':index,'worker':worker,'started':start,'finished':time.perf_counter(),
             'meta':meta,'error':error,'http_status':status,'provenance':provenance,'text':data.get('text'),
             'valid':error is None and meta.get('prompt_tokens')==len(tokens) and meta.get('completion_tokens')==1}
        self.raw.write(json.dumps(row)+'\n');self.raw.flush();return row

    async def measure(self,client,prompts):
        self.directory.mkdir(parents=True,exist_ok=False)
        save(self.directory/'server-before.json',(await client.get(self.args.base+'/server_info')).json())
        r=await client.post(self.args.base+'/flush_cache',params={'timeout':30});r.raise_for_status()
        self.raw=gzip.open(self.directory/'requests.jsonl.gz','wt')
        monitor=asyncio.create_task(self.telemetry(client));batches=gzip.open(self.directory/'batches.jsonl.gz','wt')
        windows=[];warm=0.;phase='warmup';index=0;measured_rows=[];began=time.perf_counter()
        try:
            while True:
                rows=await asyncio.gather(*(self.one(client,prompts,phase,index,i) for i in range(self.c)))
                w=phase_window(rows,self.args.gpus);w.update(batch=index,phase=phase);index+=1
                batches.write(json.dumps(w)+'\n');batches.flush()
                if not w['valid']:
                    save(self.directory/'INVALID.json',{'window':w,'requests':rows});raise RuntimeError(w['reason'])
                if phase=='warmup':
                    warm+=w['engine_seconds']
                    if warm>=60:phase='measurement'
                else:windows.append(w);measured_rows.extend(rows)
                seconds=sum(w['engine_seconds'] for w in windows)
                save(self.directory/'progress.json',{'phase':phase,'engine_seconds':seconds,'warmup_engine_seconds':warm,
                     'successful_requests':len(measured_rows),'batches':index})
                if seconds>=120 and len(measured_rows)>=32:break
                if time.perf_counter()-began>7200:raise RuntimeError('Prefill point exceeded two-hour safety limit')
        finally:
            self.stop=True;await monitor;self.raw.close();batches.close()
        seconds=sum(w['engine_seconds'] for w in windows);tokens=sum(w['actual_input_tokens'] for w in windows)
        result={'measurement_kind':'real_prefill_only_one_output_token','valid':True,'precision':self.args.precision,
                'gpus':self.args.gpus,'input_tokens':self.args.input_tokens,'concurrency':self.c,'repeat':self.repeat,
                'engine_seconds':seconds,'actual_input_tokens':tokens,'input_tokens_s_gpu':tokens/seconds/self.args.gpus,
                'request_prefill_latencies_s':[t for w in windows for t in w['request_prefill_latencies_s']],
                'client_e2e_s':distribution([r['finished']-r['started'] for r in measured_rows]),
                'successful_requests':len(measured_rows),'failed_requests':0,'warmup_engine_seconds':warm,
                'output_tokens_per_request':1,'windows':windows,
                'definition':'Native engine prefill phase wall time; includes chunk scheduling and first-token sampling, not isolated CUDA-kernel time'}
        save(self.directory/'summary.json',result)
        print(json.dumps({k:result[k] for k in ['measurement_kind','precision','input_tokens','concurrency','repeat','input_tokens_s_gpu']}),flush=True)


async def sweep(args,client,prompts,state):
    output=state/args.precision/'prefill'/('synthetic-'+str(args.input_tokens))
    save(output/'CONFIG.json',{'server_info':(await client.get(args.base+'/server_info')).json(),
         'input_tokens':args.input_tokens,'output_tokens':1,'concurrency':[1,8,32],
         'temperature':1.,'top_p':1.,'top_k':-1,'cache':False,'speculation':'off',
         'timing':'native forward_entry_time to prefill_finished_time; cohort union envelope',
         'not_pure_cuda_kernel_time':True})
    for c in [1,8,32]:
        for repeat in range(3):
            directory=output/f'c{c:03d}-r{repeat}'
            if (directory/'summary.json').exists():continue
            prompts.sequence=0
            await PrefillRound(args,{'cache':False,'speculative':'off','workload':'synthetic'},c,repeat,directory).measure(client,prompts)
