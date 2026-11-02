"""Head-node timer: validate an owned BF16 allocation, then preserve keys and switch routing."""
import argparse
import fcntl
import json
import os
import subprocess
import time
from pathlib import Path

import httpx


def save(path,data):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,path)


def allocation_hosts(job,owner):
    r=subprocess.run(['squeue','-h','-j',str(job),'-o','%u|%T|%N'],capture_output=True,text=True)
    if r.returncode:
        if 'Invalid job id' in r.stderr:return None,'not_allocated'
        raise RuntimeError('Unable to verify allocation ownership with Slurm')
    lines=r.stdout.strip().splitlines()
    if len(lines)!=1:return None,'not_allocated'
    user,phase,nodes=lines[0].split('|')
    if user!=owner:raise RuntimeError('Slurm owner mismatch')
    if phase!='RUNNING':return None,phase
    hosts=subprocess.check_output(['scontrol','show','hostnames',nodes],text=True).split()
    assert len(hosts)==2
    return hosts,phase


def backend_matches(marker,job,hosts,now):
    expected='http://'+hosts[0].removeprefix('ip-').replace('-','.')+':31420'
    return (marker.get('job')==job and marker.get('nodes')==hosts and marker.get('precision')=='bf16'
            and marker.get('phase')=='ready_api_backend' and marker.get('native_base')==expected
            and marker.get('gpus')==16 and marker.get('global_admission_cap')==8
            and 0<=now-marker.get('updated_unix',0)<90)


def gateway_config(old,restoration_id,upstream):
    aliases=['muse-spark-open','muse-spark-open-bf16']
    # The input config is never mutated; all existing key paths and labels survive.
    d=json.loads(json.dumps(old));d['upstream_base']=upstream
    d['models']={alias:'muse-spark-open-bf16' for alias in aliases}
    for binding in d['keys']:binding['models']=aliases[:]
    d['restoration_id']=restoration_id
    return d


def main(runtime):
    runtime=Path(runtime);cfg=json.loads((runtime/'RESTORE.json').read_text())
    lock=(runtime/'activation.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    statusfile=runtime/'PUBLIC_STATUS.json'
    previous=json.loads(statusfile.read_text()) if statusfile.exists() else {}
    def status(phase,**kw):save(statusfile,dict(phase=phase,job=cfg['job'],updated_unix=time.time(),**kw))
    hosts,phase=allocation_hosts(cfg['job'],cfg['owner'])
    gateway=runtime/'gateway-bf16.json'
    if hosts is None:
        if gateway.exists():
            d=json.loads(gateway.read_text())
            if d.get('restoration_id')==cfg['restoration_id'] and d['upstream_base']!='http://127.0.0.1:9/v1':
                d['upstream_base']='http://127.0.0.1:9/v1';save(gateway,d)
                subprocess.run(['systemctl','--user','restart',cfg['relay_unit']],check=True)
        status('waiting_allocation' if phase=='PENDING' else 'allocation_unavailable',slurm_state=phase)
        return
    markerfile=runtime/'BACKEND.json'
    marker=json.loads(markerfile.read_text()) if markerfile.exists() else {}
    if not backend_matches(marker,cfg['job'],hosts,time.time()):
        status('waiting_backend_readiness',backend_phase=marker.get('phase','not_started'));return
    base=marker['native_base']
    with httpx.Client(trust_env=False,timeout=30) as client:
        r=client.get(base+'/v1/models');r.raise_for_status()
        assert 'muse-spark-open-bf16' in {x['id'] for x in r.json()['data']}
        info=client.get(base+'/server_info');info.raise_for_status();info=info.json()
        assert info['dtype']=='bfloat16' and not info.get('quantization') and info['tp_size']==16
        assert info['max_running_requests']==8 and info['reasoning_parser']=='muse'
        expected=base+'/v1'
        current=json.loads(gateway.read_text()) if gateway.exists() else {}
        if previous.get('phase')=='active' and current.get('upstream_base')==expected:
            health=client.get(cfg['public_base'].removesuffix('/v1')+'/healthz');health.raise_for_status()
            status('active',native_base=base,public_base=cfg['public_base'],validated_unix=previous.get('validated_unix'))
            return
        if not (runtime/'gateway-before.json').exists():
            old=json.loads(Path(cfg['previous_gateway']).read_text());save(runtime/'gateway-before.json',old)
        else:old=json.loads((runtime/'gateway-before.json').read_text())
        save(gateway,gateway_config(old,cfg['restoration_id'],expected))
        dropin=Path(cfg['dropin']);dropin.parent.mkdir(parents=True,exist_ok=True)
        tmp=dropin.with_suffix('.tmp');tmp.write_text('[Unit]\nDescription=Key-mapped OpenAI-compatible Muse Spark BF16 API\n\n[Service]\nEnvironment=MUSE_OPENAI_RELAY_CONFIG='+str(gateway)+'\n')
        os.replace(tmp,dropin)
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        subprocess.run(['systemctl','--user','restart',cfg['relay_unit']],check=True)
        for _ in range(30):
            try:
                h=client.get('http://127.0.0.1:8119/healthz');h.raise_for_status();break
            except httpx.HTTPError:time.sleep(1)
        else:raise RuntimeError('Local BF16 relay health check did not pass')
        h=client.get(cfg['public_base'].removesuffix('/v1')+'/healthz');h.raise_for_status()
        checks=[]
        for binding in old['keys']:
            if binding.get('label') not in ['client-01','client-02','client-03']:continue
            key=Path(binding['file']).read_text().strip()
            headers={'Authorization':'Bearer '+key}
            models=client.get(cfg['public_base']+'/models',headers=headers);models.raise_for_status()
            assert 'muse-spark-open-bf16' in {x['id'] for x in models.json()['data']}
            body={'model':'muse-spark-open-bf16','messages':[{'role':'user','content':'请计算 37×43，并简短解释。'}],
                  'max_tokens':128,'reasoning_effort':'high' if binding['label']=='client-01' else 'low',
                  'stream':True,'stream_options':{'include_usage':True}}
            token_events=0;reasoning_events=0;answer_events=0;done=False
            with client.stream('POST',cfg['public_base']+'/chat/completions',headers=headers,json=body,timeout=180) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line.startswith('data: '):continue
                    data=line[6:]
                    if data=='[DONE]':done=True;continue
                    event=json.loads(data)
                    for choice in event.get('choices',[]):
                        delta=choice.get('delta',{})
                        reasoning_events+=bool(delta.get('reasoning_content'));answer_events+=bool(delta.get('content'))
                        token_events+=bool(delta.get('reasoning_content') or delta.get('content'))
            assert done and token_events>0
            checks.append({'label':binding['label'],'models_http':models.status_code,'stream_completed':done,
                           'nonempty_stream_events':token_events,'reasoning_events':reasoning_events,'answer_events':answer_events})
        assert len(checks)==3
        assert sum(check['reasoning_events'] for check in checks)>0, 'No reasoning stream observed during BF16 validation'
        unauthorized=client.get(cfg['public_base']+'/models');assert unauthorized.status_code==401
        save(runtime/'VALIDATION.json',{'updated_unix':time.time(),'job':cfg['job'],'precision':'bf16','gpus':16,
                                      'global_admission_cap':8,'original_three_keys_preserved':True,'checks':checks,'unauthenticated_http':401})
        status('active',native_base=base,public_base=cfg['public_base'],validated_unix=time.time())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--runtime',type=Path,required=True);a=p.parse_args()
    try:main(a.runtime)
    except Exception as exc:
        save(a.runtime/'PUBLIC_STATUS.json',{'phase':'activation_or_validation_failed','updated_unix':time.time(),'error_type':type(exc).__name__})
        raise
