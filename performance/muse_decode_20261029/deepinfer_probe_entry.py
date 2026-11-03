"""Dedicated, bounded H200 dependency probe; never reports an operator check as a model curve."""
import argparse,json,os,shutil,subprocess,time,traceback
from pathlib import Path
from retain_allocation import retain
IMAGE='lmsysorg/sglang@sha256:8cfc5a72cb296771f5f8a4a4688cb6d05685610a830cbb616fa4ab0eb7bb2b0a'
p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);a=p.parse_args();job=os.environ['SLURM_JOB_ID'];name='zhiyuan-deepinfer-h200-probe-'+job
def execute():
    env=os.environ.copy()
    for k in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH'):env.pop(k,None)
    docker=['docker','--host=unix:///var/run/docker.sock']
    plan=json.loads((a.state/'PLAN.json').read_text())
    source_job=str(plan.get('reuse_build_job',job));assert source_job.isdigit()
    local=Path('/opt/dlami/nvme')/('zhiyuan-deepinfer-h200-probe-'+source_job);local.mkdir(exist_ok=True);assert shutil.disk_usage(local).free>40*2**30
    used=[int(x) for x in subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],text=True).split()];assert len(used)==8 and max(used)<2000,'GPU work is already present; preserve it'
    hardware=subprocess.check_output(['nvidia-smi','--query-gpu=name,uuid,compute_cap','--format=csv,noheader'],text=True)
    (a.state/'HARDWARE.txt').write_text(hardware)
    if subprocess.run([*docker,'image','inspect',IMAGE],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=env).returncode:subprocess.run([*docker,'pull',IMAGE],check=True,env=env)
    bootstrap='command -v lspci >/dev/null || { apt-get update -qq && apt-get install -y --no-install-recommends pciutils; }; exec /opt/sglang/bin/python /evidence/deepinfer_probe_inside.py'
    cmd=[*docker,'run','--rm','--init','--name',name,'-e','HOME=/work/home','--gpus','all','--network','host','--ipc','host','-v',str(local)+':/work','-v',str(a.state)+':/evidence','--entrypoint','bash',IMAGE,'-lc',bootstrap]
    (a.state/'COMMAND.json').write_text(json.dumps(cmd,indent=2));started=time.time()
    try:
     result=subprocess.run(cmd,env=env,timeout=6600)
    finally:
     subprocess.run([*docker,'stop','-t','10',name],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
    (a.state/'EXIT.json').write_text(json.dumps({'job':job,'started_utc':started,'ended_utc':time.time(),'returncode':result.returncode,'valid_performance_points':0},indent=2))
    return result.returncode

rc=1
try:
    rc=execute()
except Exception:
    traceback.print_exc()
finally:
    retain(a.state,rc)
raise SystemExit(rc)
