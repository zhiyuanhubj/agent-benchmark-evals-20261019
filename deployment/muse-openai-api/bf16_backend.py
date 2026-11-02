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


def verify_bf16(info):
    assert info['served_model_name']=='muse-spark-open-bf16'
    assert info['dtype']=='bfloat16' and not info.get('quantization')
    assert info['tp_size']==16 and info['ep_size']==16 and info['nnodes']==2
    assert info['max_running_requests']==8
    assert info['reasoning_parser']=='muse' and info['tool_call_parser']=='muse'


def run(state,plan):
    root=Path(plan['controller_root']);runtime=Path(plan['api_runtime_dir'])
    job=int(os.environ['SLURM_JOB_ID']);assert job==plan['jobs']['bf16']
    nodes=subprocess.check_output(['squeue','-h','-j',str(job),'-o','%N'],text=True).strip()
    hosts=subprocess.check_output(['scontrol','show','hostnames',nodes],text=True).split()
    assert len(hosts)==2 and plan['precision']=='bf16' and plan['server_cap']==8
    base='http://'+hosts[0].removeprefix('ip-').replace('-','.')+':31420'
    def status(phase,**kw):
        d=dict(phase=phase,job=job,nodes=hosts,precision='bf16',gpus=16,global_admission_cap=8,
               native_base=base,updated_unix=time.time(),**kw)
        save(state/'status.json',d);save(runtime/'BACKEND.json',d)
    def interrupted(*_):raise KeyboardInterrupt('Slurm termination')
    signal.signal(signal.SIGTERM,interrupted)
    prefix=['srun','--jobid='+str(job),'--nodelist='+nodes,'--chdir='+str(root),'--overlap','--exact','--gres=none',
            '--kill-on-bad-exit=1','-N2','-n2','--ntasks-per-node=1','-c48',sys.executable,str(root/'node.py')]
    common=['--state',str(state),'--precision','bf16']
    status('preparing_api_weights')
    started=time.time()
    try:
        subprocess.run([*prefix,'preflight',*common],check=True)
        subprocess.run([*prefix,'prepare',*common],check=True)
    except subprocess.CalledProcessError as exc:
        status('failed_preparation',error=type(exc).__name__)
        if retry_placement(state,plan,job,hosts,started,save):return
        raise
    server=None
    try:
        status('starting_api_model')
        with (state/'server-api-bf16.log').open('a') as log:
            server=subprocess.Popen([*prefix,'serve',*common,'--cache'],stdout=log,stderr=subprocess.STDOUT)
            with httpx.Client(trust_env=False,timeout=10) as client:
                for _ in range(180):
                    if server.poll() is not None:raise RuntimeError('Serving ranks exited during startup')
                    try:
                        r=client.get(base+'/server_info');r.raise_for_status();info=r.json();verify_bf16(info)
                        m=client.get(base+'/v1/models');m.raise_for_status()
                        assert 'muse-spark-open-bf16' in {x['id'] for x in m.json()['data']}
                        break
                    except httpx.HTTPError:time.sleep(10)
                else:raise RuntimeError('BF16 model readiness timeout')
                save(runtime/'SERVER_INFO.json',info)
                status('ready_api_backend',model_revision=plan['models']['bf16']['revision'])
                health_failures=0
                while server.poll() is None:
                    time.sleep(15)
                    try:
                        r=client.get(base+'/server_info');r.raise_for_status();verify_bf16(r.json())
                    except httpx.HTTPError:
                        health_failures+=1
                        if health_failures>=3:raise
                        continue
                    health_failures=0
                    status('ready_api_backend',model_revision=plan['models']['bf16']['revision'])
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
