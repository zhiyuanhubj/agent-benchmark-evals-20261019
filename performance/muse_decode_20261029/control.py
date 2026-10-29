#!/usr/bin/env python3
"""Independently queued replicas: pinned preparation, decode windows, cleanup."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
from native_client import save


def main():
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);a=p.parse_args()
    plan=json.loads((a.state/'PLAN.json').read_text());root=Path(plan['controller_root'])
    precision=plan['precision'];job=int(os.environ['SLURM_JOB_ID']);assert job==plan['jobs'][precision]
    n=1 if precision=='nvfp4' else 2
    nodes=subprocess.check_output(['squeue','-h','-j',str(job),'-o','%N'],text=True).strip()
    hosts=subprocess.check_output(['scontrol','show','hostnames',nodes],text=True).split();assert len(hosts)==n
    base='http://'+hosts[0].removeprefix('ip-').replace('-','.')+':31420'
    def status(phase,**kw):save(a.state/'status.json',{'phase':phase,'job':job,'precision':precision,'nodes':hosts,'updated_unix':time.time(),**kw})
    def interrupted(*_):raise KeyboardInterrupt('Slurm termination')
    signal.signal(signal.SIGTERM,interrupted)
    prefix=['srun','--jobid='+str(job),'--nodelist='+nodes,'--chdir='+str(root),'--overlap','--exact','--gres=none',
            '--kill-on-bad-exit=1','-N'+str(n),'-n'+str(n),'--ntasks-per-node=1','-c48',sys.executable,str(root/'node.py')]
    common=['--state',str(a.state),'--precision',precision]
    status('preparing_and_verifying_pinned_weights')
    try:
        subprocess.run([*prefix,'prepare',*common],check=True)
    except BaseException as exc:
        status('failed_preparation',error=type(exc).__name__+': '+str(exc))
        raise
    monitor=subprocess.Popen(['srun','--jobid='+str(job),'--nodelist='+nodes,'--overlap','--exact','--gres=none',
        '-N'+str(n),'-n'+str(n),'--ntasks-per-node=1','-c1',sys.executable,str(root/'gpu.py'),'--output',str(a.state/precision/'gpu')])
    server=None;failures=[]
    try:
        configs=[]
        if plan['input_lengths']:configs.append(('off',False))
        if plan['mode'] in ('paired_spec','long_and_paired_spec'):configs += [('off',True),('NGRAM',True)]
        for spec, paired_graphs in configs:
            status('starting_fixed_server',speculative=spec)
            label=spec+('-paired-graphs' if paired_graphs else '')
            logfile=(a.state/('server-'+label+'.log')).open('a')
            flags=['--paired-graphs'] if paired_graphs else []
            server=subprocess.Popen([*prefix,'serve',*common,'--speculative',spec,*flags],stdout=logfile,stderr=subprocess.STDOUT)
            ready=False
            with httpx.Client(trust_env=False,timeout=10) as client:
                for _ in range(180):
                    if server.poll() is not None:break
                    try:
                        r=client.get(base+'/server_info')
                        if r.status_code==200:
                            info=r.json();assert info['disable_radix_cache']
                            assert (info.get('speculative_algorithm') or 'off')==spec
                            save(a.state/('server-info-'+label+'.json'),info);ready=True;break
                    except httpx.HTTPError:pass
                    time.sleep(10)
            if not ready:
                failures.append({'speculative':spec,'reason':'server_failed_readiness'});raise RuntimeError(str(failures[-1]))
            cases=[]
            if not paired_graphs:
                cases += [('synthetic',length,None) for length in plan['input_lengths']]
            if paired_graphs:
                cases += [('coding',0,(0,8192)),('coding',0,(8192,32768))]
            for workload,length,bucket in cases:
                name='synthetic-'+str(length) if bucket is None else 'coding-native-'+str(bucket[0])+'-'+str(bucket[1])
                directory=a.state/precision/('spec-'+spec)/name
                cs=(plan.get('decode_concurrency','1,2,4,8,16,32,64,128,256') if workload=='synthetic'
                    else plan.get('coding_concurrency','1,2,4,8,16,32'))
                command=['srun','--jobid='+str(job),'--nodelist='+hosts[0],'--chdir='+str(root),'--overlap','--exact','--gres=none',
                    '-N1','-n1','-c8',sys.executable,str(root/'decode.py'),'--base',base,'--output',str(directory),
                    '--precision',precision,'--gpus',str(n*8),'--corpus',str(a.state/'coding_prompts.jsonl'),
                    '--input-tokens',str(length),'--workload',workload,'--speculative',spec,'--concurrency',cs]
                if bucket:command += ['--input-range',str(bucket[0]),str(bucket[1])]
                status('measuring_decode_only',speculative=spec,workload=workload,input_tokens=length,input_range=bucket,output=str(directory))
                clientproc=subprocess.Popen(command)
                while clientproc.poll() is None:
                    if server.poll() is not None or monitor.poll() is not None:
                        clientproc.terminate();clientproc.wait(timeout=30)
                        raise RuntimeError('Serving or GPU telemetry step exited during decode test')
                    time.sleep(3)
                if clientproc.returncode:failures.append({'speculative':spec,'case':name,'returncode':clientproc.returncode})
            subprocess.run([*prefix,'stop',*common],check=False)
            try:server.wait(timeout=90)
            except subprocess.TimeoutExpired:server.terminate();server.wait(timeout=30)
            server=None;logfile.close()
        status('finished' if not failures else 'finished_with_incomplete_cases',failures=failures)
    except BaseException as exc:
        status('failed',error=type(exc).__name__+': '+str(exc),failures=failures);raise
    finally:
        subprocess.run([*prefix,'stop',*common],check=False)
        if server is not None:
            try:server.wait(timeout=90)
            except subprocess.TimeoutExpired:server.terminate()
        monitor.terminate()
        try:monitor.wait(timeout=20)
        except subprocess.TimeoutExpired:monitor.kill()


if __name__=='__main__':main()
