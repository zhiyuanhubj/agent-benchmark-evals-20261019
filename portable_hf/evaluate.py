#!/usr/bin/env python3
"""Prepare or run fixed benchmark protocols against a supplied model bridge."""
import argparse
import copy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
W=ROOT/'workspace'
M=W/'.private/muse_spark_open_20261016'
B=W/'.private/beam_20261018'
F=W/'.private/muse_bf16_20261018'
E=B/'tb_v1_exact_images_20261019'
STRICT=W/'bench/strict_four_models_20261008'
SPLITS=('glm5_500','qwen3_coder_30b_500','qwen3_30b_instruct2507_500')
MODELS={'muse_nvfp4':'muse-spark-open-nvfp4','muse_bf16':'muse-spark-open-bf16',
        'beam':'Beam-1.0-501B-A23B','opus47':'claude-opus-4-7'}


def read(path):return json.loads(path.read_text())


def relocated(value):
    if isinstance(value,str):return value.replace('/fsx/home/zhiyuan',str(W))
    if isinstance(value,list):return [relocated(x) for x in value]
    if isinstance(value,dict):return {k:relocated(v) for k,v in value.items()}
    return value


def bridge_config(value,api):
    if isinstance(value,list):return [bridge_config(x,api) for x in value]
    if not isinstance(value,dict):return value
    result={}
    for key,item in value.items():
        if key in ('api_base','base_url','OPENAI_API_BASE','OPENAI_BASE_URL','LLM_BASE_URL'):item=api
        elif key in ('OPENAI_API_KEY','MSWEA_API_KEY','LLM_API_KEY','api_key'):item='EMPTY'
        else:item=bridge_config(item,api)
        result[key]=item
    return result


def directories(profile):
    if profile=='muse_nvfp4':return M/'shard0',M/'review_bench_20261018',E/'muse_nvfp4'
    if profile=='muse_bf16':return F/'legacy_bench',F/'review_bench',F/'legacy_bench'
    if profile=='beam':return E/'beam',B/'review_bench',E/'beam'
    return W/'bench/opus47_full_20261018',W/'.private/opus47_review_20261020',E/'opus47'


def pro_source(profile):
    if profile=='muse_nvfp4':return M/'shard0/configs/pro-command.json'
    if profile=='muse_bf16':return F/'legacy_bench/pro-command.template.json'
    if profile=='beam':return B/'legacy_bench_20261018/remaining_pro/pro-command.template.json'
    return W/'bench/opus47_full_20261018/pro-command.json'


def harbor_source(bench,profile,split):
    local,review,tb=directories(profile)
    if bench=='swe_review':return review/'configs'/f'{split}.json',review/'swe_entry.py'
    if bench=='deepswe':
        source={'muse_nvfp4':M/'shard0/configs/deep.json',
            'muse_bf16':F/'legacy_bench/configs/deep-r1.json',
            'beam':B/'legacy_bench_20261018/remaining_deep/configs/deep-r2.json',
            'opus47':local/'configs/deep-r1.json'}[profile]
        return source,local/'deep_entry.py'
    source={'muse_nvfp4':E/'muse_nvfp4/configs/r1-completion-2866-b00.json',
        'muse_bf16':F/'legacy_bench/configs/tb-r1.json',
        'beam':E/'beam/configs/r1.json','opus47':E/'opus47/configs/r1.json'}[profile]
    return source,ROOT/'harbor_job.py'


def prepare_harbor(args,out,split):
    source,entry=harbor_source(args.benchmark,args.profile,split)
    spec=relocated(read(source));config=spec.get('config',spec)
    config=bridge_config(config,args.api_base)
    if args.benchmark=='tb21':
        tasks=[{'path':str(p.parent)} for p in sorted((STRICT/'sources/terminal-bench-2-1').glob('*/task.toml'))]
        assert len(tasks)==89
    elif args.benchmark=='deepswe':
        paths=read(ROOT/'WORKSPACE_MANIFEST.json')['deepswe_task_paths']
        tasks=[{'path':relocated(p)} for p in paths]
        assert len(tasks)==113
    else:
        task_root=M/'review_bench_20261018/swe_review'/split/'tasks'
        tasks=[{'path':str(p.parent)} for p in sorted(task_root.glob('*/task.toml'))]
        assert len(tasks)==dict(zip(SPLITS,(500,462,422)))[split]
    if args.limit:tasks=tasks[:args.limit]
    config.pop('datasets',None)
    config['tasks']=tasks
    config['job_name']=out.name+('-'+split if split else '')
    config['jobs_dir']=str(out/'trials')
    config['n_attempts']=1
    config.setdefault('retry',{'max_retries':0})
    if args.concurrency:config['n_concurrent_trials']=args.concurrency
    for agent in config['agents']:
        agent['model_name']='openai/'+args.model.removeprefix('openai/')
        kwargs=agent.get('kwargs',{})
        if 'send_reasoning_content_models' in kwargs:
            kwargs['send_reasoning_content_models']=[args.model.removeprefix('openai/')]
    target=out/(args.benchmark+('-'+split if split else '')+'.json')
    value=config if args.benchmark=='tb21' else {'config':config,'regrade':False}
    target.write_text(json.dumps(value,indent=2)+'\n')
    from harbor.models.job.config import JobConfig
    JobConfig.model_validate(config)
    local,review,tb=directories(args.profile)
    env={'MIX_SERVER_IP':args.bridge_ip,'MIX_SERVER_PORT':'31320',
         'PYTHONPATH':os.pathsep.join(map(str,[tb if args.benchmark=='tb21' else entry.parent,
             W/'bench/tb21_v1_four_models_20261012',STRICT,STRICT/'sources/swe-pro/v2/tooling',W/'vendor'])),
         'OPENAI_API_KEY':'EMPTY','MSWEA_API_KEY':'EMPTY',
         'OPENAI_API_BASE':args.api_base,'OPENAI_BASE_URL':args.api_base,
         'LLM_BASE_URL':args.api_base,'LLM_API_KEY':'EMPTY',
         'OPENHANDS_LLM_NATIVE_TOOL_CALLING':'true'}
    return {'source':str(source),'tasks':len(tasks),'argv':[sys.executable,str(entry),str(target)],'env':env}


def prepare_pro(args,out):
    source=pro_source(args.profile)
    command=relocated(read(source));command[0]=sys.executable
    # A supplied positional model id changes only the served model alias.
    assert command[2:5]==['run','swebench_pro_verified','mini_swe_agent']
    command[5]=args.model.removeprefix('openai/')
    inventory=W/'AgentCompass-official-baseline/data/swe_bench_pro_verified/swebench_pro_verified.jsonl'
    ids=[json.loads(line)['instance_id'] for line in inventory.read_text().splitlines() if line.strip()]
    assert len(ids)==len(set(ids))==731
    if args.limit:ids=ids[:args.limit]
    params=json.loads(command[command.index('--benchmark-params')+1]);params['sample_ids']=ids
    flags={'--data-dir':str(W/'AgentCompass-official-baseline/data'),
        '--results-dir':str(out/'trials'),'--run-name':out.name,'--run-id':out.name,
        '--model-base-url':args.api_base,'--model-api-key':'EMPTY',
        '--benchmark-params':json.dumps(params),'--k':'1','--attempt-strategy':'pass'}
    if args.concurrency:flags['--task-concurrency']=str(args.concurrency)
    for flag,value in flags.items():command[command.index(flag)+1]=value
    (out/'pro-command.json').write_text(json.dumps(command,indent=2)+'\n')
    return {'source':str(source),'tasks':len(ids),'argv':command,
        'env':{'MIX_SERVER_IP':args.bridge_ip,'OPENAI_API_KEY':'EMPTY',
               'HF_HOME':str(ROOT/'cache/hf'),'UV_CACHE_DIR':str(ROOT/'cache/uv'),
               'PYTHONPATH':str(W/'AgentCompass/src')}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('benchmark',choices=['tb21','pro','deepswe','swe_review'])
    p.add_argument('--profile',choices=MODELS,default='muse_nvfp4')
    p.add_argument('--model');p.add_argument('--bridge-ip',default='172.17.0.1')
    p.add_argument('--api-base',help='Defaults to the local model bridge; sandbox must reach this IP')
    p.add_argument('--split',choices=('all',*SPLITS),default='all')
    p.add_argument('--limit',type=int);p.add_argument('--concurrency',type=int)
    p.add_argument('--rounds',type=int,default=1,choices=(1,2,3))
    p.add_argument('--output',type=Path);p.add_argument('--execute',action='store_true')
    args=p.parse_args();args.model=args.model or MODELS[args.profile]
    args.api_base=args.api_base or f'http://{args.bridge_ip}:31320/v1'
    assert (ROOT/'MATERIALIZATION.json').exists(),'Run setup_bundle.py first'
    assert args.limit is None or args.limit>0
    assert args.concurrency is None or args.concurrency>0
    output=(args.output or ROOT/'outputs'/(args.benchmark+'-'+args.profile+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))).resolve()
    output.mkdir(parents=True,exist_ok=False)
    plans=[]
    for number in range(1,args.rounds+1):
        out=output/f'round-{number}';out.mkdir()
        splits=SPLITS if args.benchmark=='swe_review' and args.split=='all' else ((args.split,) if args.benchmark=='swe_review' else ('',))
        for split in splits:
            plan=prepare_pro(args,out) if args.benchmark=='pro' else prepare_harbor(args,out,split)
            plan.update(round=number,partial_smoke=bool(args.limit))
            plans.append(plan)
    (output/'PLAN.json').write_text(json.dumps(plans,indent=2)+'\n')
    print(json.dumps({'plans':len(plans),'tasks':sum(x['tasks'] for x in plans),'output':str(output),'execute':args.execute}),flush=True)
    if args.execute:
        for plan in plans:
            env=dict(os.environ);env.update(plan['env'])
            subprocess.run(plan['argv'],env=env,cwd=W/'AgentCompass' if args.benchmark=='pro' else ROOT,check=True)


if __name__=='__main__':main()
