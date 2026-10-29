#!/usr/bin/env python3
"""Extend an in-flight three-point sweep on the same warm GPU replica.

Only the CPU coordinator is stopped. Its current measurement client, model
server and telemetry continue. Resume the coordinator for normal cleanup after
the extended client finishes; never mix two load generators on the replica.
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from native_client import save


def proc_matches(pid, ticks, script, state, proc_root=Path('/proc')):
    p=proc_root/str(pid)
    try:
        stat=(p/'stat').read_text().split()
        args=(p/'cmdline').read_bytes().split(b'\0')
        return stat[2]!='Z' and stat[21]==str(ticks) and str(script).encode() in args and str(state).encode() in args
    except (FileNotFoundError,PermissionError,ProcessLookupError):return False


def remote_action(a,receipt):
    root=Path(receipt['root']);state=Path(receipt['state'])
    control=receipt['controller'];client=receipt['client']
    parent_ok=proc_matches(control['pid'],control['start_ticks'],root/'control.py',state)
    client_ok=proc_matches(client['pid'],client['start_ticks'],root/'decode.py',Path(receipt['case']))
    if a.remote_action=='pause':
        assert parent_ok and client_ok,'Current coordinator/client changed; refusing handoff'
        os.kill(control['pid'],signal.SIGSTOP)
        receipt['paused']=True;receipt['paused_unix']=time.time();save(a.receipt,receipt)
    elif a.remote_action=='resume' and parent_ok:
        os.kill(control['pid'],signal.SIGCONT)
    print(json.dumps({'parent_matches':parent_ok,'client_running':client_ok}),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--remote-action',choices=['inspect','pause','resume'])
    a=p.parse_args();r=json.loads(a.receipt.read_text());root=Path(r['root']);state=Path(r['state'])
    if a.remote_action:return remote_action(a,r)
    def interrupted(*_):raise KeyboardInterrupt('Dense extension supervisor stopped')
    signal.signal(signal.SIGTERM,interrupted)
    prefix=['srun','--jobid='+str(r['job']),'--nodelist='+r['host'],'--chdir='+str(root),
            '--overlap','--exact','--gres=none','-N1','-n1','-c1','--immediate=30',sys.executable,
            str(root/'dense_followup.py'),'--receipt',str(a.receipt)]
    audit=state/r.get('audit_file','DENSE_EXTENSION.json')
    def update(phase,**kw):save(audit,{'phase':phase,'updated_unix':time.time(),'same_warm_replica':True,**kw})
    def inspect():
        result=subprocess.check_output([*prefix,'--remote-action','inspect'],text=True)
        return json.loads(result.splitlines()[-1])
    try:
        while not json.loads(a.receipt.read_text()).get('paused'):time.sleep(1)
        update('waiting_current_sweep',concurrency=r.get('initial_concurrency','1,8,32'))
        while True:
            allocated=subprocess.check_output(['squeue','-h','-j',str(r['job']),'-o','%T'],text=True).strip()
            if allocated not in ('RUNNING','COMPLETING'):
                update('allocation_ended_before_followup',slurm_state=allocated);return
            info=inspect()
            if not info['parent_matches']:raise RuntimeError('Original coordinator exited')
            if not info['client_running']:break
            time.sleep(30)
        directory=Path(r['case'])
        if r.get('action')!='prefill_only':
            for name in ['CONFIG.json','PROMPTS.json']:
                source=directory/name;backup=directory/(source.stem+'.initial-three-point.json')
                if source.exists() and not backup.exists():shutil.copyfile(source,backup)
        lead=['srun','--jobid='+str(r['job']),'--nodelist='+r['host'],'--chdir='+str(root),
              '--overlap','--exact','--gres=none','-N1','-n1','-c8',sys.executable]
        if r.get('action')=='prefill_only':
            update('deferred_prefill_on_warm_replica')
            command=[*lead,str(root/'prefill.py'),'--base',r['base'],'--state',str(state),
                     '--precision','nvfp4','--gpus','8','--input-tokens',str(r['input_tokens'])]
        else:
            update('extending_warm_replica',concurrency='1,2,4,8,16,32,64,128,256')
            command=[*lead,str(root/'decode.py'),'--base',r['base'],'--output',str(directory),
                '--precision','nvfp4','--gpus','8','--corpus',str(state/'coding_prompts.jsonl'),
                '--input-tokens',str(r.get('input_tokens',32768)),
                '--workload','synthetic','--speculative','off','--concurrency','1,2,4,8,16,32,64,128,256']
        result=subprocess.run(command)
        update('complete' if result.returncode==0 else 'failed',returncode=result.returncode)
    except BaseException as exc:
        update('failed',error=type(exc).__name__+': '+str(exc));raise
    finally:
        subprocess.run([*prefix,'--remote-action','resume'],check=False)


if __name__=='__main__':main()
