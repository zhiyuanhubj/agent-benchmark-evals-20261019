"""Retry only startup transport errors, preserving all raw outputs and logs."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from retain_allocation import retain

def retryable(state):
    marker=state/'status.json'
    if not marker.exists():return False
    status=json.loads(marker.read_text())
    if status.get('phase') not in ('failed','api_backend_stopped'):return False
    if not any(x in status.get('error','') for x in ('readiness','startup','Serving ranks exited')):return False
    logs=list(state.glob('server-*.log'))
    return any(any(s in p.read_text(errors='replace')[-120000:] for s in
                   ('ofi cq creation failed','NCCL error','ncclInternalError','RDMA endpoint rail init')) for p in logs)

def main():
    p=argparse.ArgumentParser();p.add_argument('--state',required=True,type=Path);a=p.parse_args()
    root=Path(__file__).resolve().parent;attempts=[]
    for attempt in range(3):
        began=time.time();r=subprocess.run([sys.executable,'-u',str(root/'control.py'),'--state',str(a.state)])
        again=r.returncode!=0 and attempt<2 and retryable(a.state)
        attempts.append({'attempt':attempt+1,'started_utc':began,'ended_utc':time.time(),'returncode':r.returncode,'retrying_transport_startup':again})
        path=a.state/'STARTUP_RECOVERY.json';tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'job':os.environ['SLURM_JOB_ID'],'attempts':attempts},indent=2));tmp.replace(path)
        if not again:
            if os.environ.get('MUSE_API_HEAD_COORDINATOR')!='1':retain(a.state,r.returncode)
            raise SystemExit(r.returncode)
        time.sleep(30)

if __name__=='__main__':main()
