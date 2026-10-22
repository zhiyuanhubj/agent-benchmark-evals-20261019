#!/usr/bin/env python3
"""Portable driver around the unchanged official SWRBench prompt and scorer."""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor,as_completed
import importlib.util
import json
import logging
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent
WORK=ROOT/'workspace/.private/muse_spark_open_20261016/review_bench_20261018'
DATA=ROOT/'workspace/bench/code-review-eval/data/repos/swrbench/data/swr_datasets_d5c5.jsonl'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('generate','judge'))
    p.add_argument('--model',required=True)
    p.add_argument('--profile',choices=('muse_nvfp4','muse_bf16','beam'),default='muse_nvfp4')
    p.add_argument('--api-base',default='http://172.17.0.1:31320/v1')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--concurrency',type=int,default=4)
    p.add_argument('--limit',type=int)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    assert args.concurrency>0 and (args.limit is None or args.limit>0)
    os.environ.update(OPENAI_API_BASE=args.api_base,OPENAI_API_KEY='EMPTY',
        SWR_ARCHIVE=str(out/('raw_responses' if args.action=='generate' else 'judge_raw_responses')))
    transport=module('portable_swr_utils',WORK/'swr_utils.py');sys.modules['utils']=transport
    items=[json.loads(line) for line in DATA.read_text().splitlines() if line.strip()]
    assert len(items)==len({x['instance_id'] for x in items})==1000
    if args.limit:items=items[:args.limit]
    logging.basicConfig(level=logging.INFO);logger=logging.getLogger('swrbench')
    if args.action=='generate':
        assert not (out/'generation.jsonl').exists(),'Do not overwrite sampled outputs'
        os.environ['SWR_EXTRA_BODY_JSON']=json.dumps({'chat_template_kwargs':{
            'reasoning_effort':'max' if args.profile=='beam' else 'xhigh'},
            'top_k':-1,'top_p':0.99 if args.profile=='beam' else 1.0})
        official=module('official_swr_generation',WORK/'vendor/swr_generation.py')
        values=SimpleNamespace(model=args.model,temperature=0.7 if args.profile=='beam' else 0.2,
            max_tokens=8192,output_file=str(out/'generation.jsonl'))
        lock=threading.Lock();failures=[]
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures={pool.submit(official.generate_task_base,values,item,logger,lock):item['instance_id'] for item in items}
            for future in as_completed(futures):
                try:future.result()
                except Exception as e:failures.append({'instance_id':futures[future],'error_type':type(e).__name__})
        (out/'generation-status.json').write_text(json.dumps({'expected':len(items),
            'full_benchmark':not bool(args.limit),'failures':failures},indent=2)+'\n')
        if failures:raise SystemExit('Generation incomplete; preserve originals and inspect failures')
    else:
        assert not (out/'evaluation.json').exists(),'Do not replace an existing judged result'
        os.environ['SWR_EXTRA_BODY_JSON']='{}'
        official=module('official_swr_evaluation',WORK/'vendor/swr_evaluation_struct.py')
        predictions=[json.loads(line) for line in (out/'generation.jsonl').read_text().splitlines() if line.strip()]
        ids=[x['instance_id'] for x in predictions]
        assert len(ids)==len(set(ids))==len(items) and set(ids)=={x['instance_id'] for x in items}
        truth={x['instance_id']:x for x in items}
        values=SimpleNamespace(model=args.model,temperature=1.0,max_tokens=8192)
        results=[];failures=[]
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures={pool.submit(official.evaluate_one,values,
                {'pred':copy.deepcopy(pred),'instance':copy.deepcopy(truth[pred['instance_id']])},official.logger):pred['instance_id']
                for pred in predictions}
            for future in as_completed(futures):
                try:
                    result=future.result()
                    assert result is not None and result['instance_id']==futures[future]
                    results.append(result)
                    with (out/'judged-native.jsonl').open('a') as handle:handle.write(json.dumps(result,ensure_ascii=False)+'\n')
                except Exception as e:failures.append({'instance_id':futures[future],'error_type':type(e).__name__})
        status={'expected':len(items),'judged':len(results),'failures':failures,
            'full_benchmark':len(items)==1000 and not args.limit,'judge_model':args.model}
        if not failures:status.update(analysis_results=official.analyze_result(results),details=results)
        (out/'evaluation.json').write_text(json.dumps(status,indent=2,ensure_ascii=False)+'\n')
        if failures:raise SystemExit('Judging incomplete; partial output is not a full benchmark score')


if __name__=='__main__':main()
