"""Dedicated BF16 API allocation; uses the pinned benchmark node preparation code."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from native_client import save
from placement import retry_placement


def verify_bf16(info, precision='bf16'):
    assert precision in ('bf16','nvfp4')
    assert info['served_model_name']=='muse-spark-open-'+precision
    size=16 if precision=='bf16' else 8
    if precision=='bf16':assert info['dtype']=='bfloat16' and not info.get('quantization')
    else:assert info.get('quantization')=='modelopt_fp4'
    assert info['tp_size']==size and info['ep_size']==size and info['nnodes']==size//8
    assert info['max_running_requests']==8
    assert info['reasoning_parser']=='muse' and info['tool_call_parser']=='muse'


def run(state,plan):
    root=Path(plan['controller_root']);runtime=Path(plan['api_runtime_dir'])
    precision=plan['precision'];n=1 if precision=='nvfp4' else 2
    job=int(os.environ['SLURM_JOB_ID']);assert job==plan['jobs'][precision]
    nodes=subprocess.check_output(['squeue','-h','-j',str(job),'-o','%N'],text=True).strip()
    hosts=subprocess.check_output(['scontrol','show','hostnames',nodes],text=True).split()
    assert len(hosts)==n and plan['server_cap']==8
    base='http://'+hosts[0].removeprefix('ip-').replace('-','.')+':31420'
    def status(phase,**kw):
        d=dict(phase=phase,job=job,nodes=hosts,precision=precision,gpus=n*8,global_admission_cap=8,
               native_base=base,updated_unix=time.time(),**kw)
        save(state/'status.json',d);save(runtime/'BACKEND.json',d)
    def interrupted(*_):raise KeyboardInterrupt('Slurm termination')
    signal.signal(signal.SIGTERM,interrupted)
    prefix=['srun','--jobid='+str(job),'--nodelist='+nodes,'--chdir='+str(root),'--overlap','--exact','--gres=none',
            '--kill-on-bad-exit=1','-N'+str(n),'-n'+str(n),'--ntasks-per-node=1','-c48',sys.executable,str(root/'node.py')]
    common=['--state',str(state),'--precision',precision]
    status('preparing_api_weights')
    started=time.time()
    try:
        subprocess.run([*prefix,'preflight',*common],check=True)
        if plan.get('reuse_verified_weights_state'):
            reuse=['srun','--jobid='+str(job),'--nodelist='+nodes,'--chdir='+str(root),'--overlap','--exact','--gres=none',
                   '--kill-on-bad-exit=1','-N'+str(n),'-n'+str(n),'--ntasks-per-node=1','-c2',sys.executable,str(root/'reuse_api_weights.py'),'--state',str(state)]
            subprocess.run(reuse,check=True)
        else:
            subprocess.run([*prefix,'prepare',*common],check=True)
    except subprocess.CalledProcessError as exc:
        status('failed_preparation',error=type(exc).__name__)
        if retry_placement(state,plan,job,hosts,started,save):return
        raise
    server=None
    try:
        status('starting_api_model')
        with (state/('server-api-'+precision+'.log')).open('a') as log:
            server=subprocess.Popen([*prefix,'serve',*common,'--cache'],stdout=log,stderr=subprocess.STDOUT)
            with httpx.Client(trust_env=False,timeout=10) as client:
                for _ in range(180):
                    if server.poll() is not None:raise RuntimeError('Serving ranks exited during startup')
                    try:
                        r=client.get(base+'/server_info');r.raise_for_status();info=r.json();verify_bf16(info,precision)
                        m=client.get(base+'/v1/models');m.raise_for_status()
                        assert 'muse-spark-open-'+precision in {x['id'] for x in m.json()['data']}
                        break
                    except httpx.HTTPError:time.sleep(10)
                else:raise RuntimeError('BF16 model readiness timeout')
                save(runtime/'SERVER_INFO.json',info)
                status('ready_api_backend',model_revision=plan['models'][precision]['revision'])
                health_failures=0
                while server.poll() is None:
                    time.sleep(15)
                    try:
                        r=client.get(base+'/server_info');r.raise_for_status();verify_bf16(r.json(),precision)
                    except httpx.HTTPError:
                        health_failures+=1
                        if health_failures>=3:raise
                        continue
                    health_failures=0
                    status('ready_api_backend',model_revision=plan['models'][precision]['revision'])
                raise RuntimeError('Dedicated API model ranks exited')
    except BaseException as exc:
        status('api_backend_stopped',error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        subprocess.run([*prefix,'stop',*common],check=False)
        if server is not None:
            try:server.wait(timeout=90)
            except subprocess.TimeoutExpired:server.terminate()


if __name__=='__main__':
    state=Path(sys.argv[1]);run(state,json.loads((state/'PLAN.json').read_text()))
