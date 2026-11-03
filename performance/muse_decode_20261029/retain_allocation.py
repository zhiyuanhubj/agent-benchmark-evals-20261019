"""Keep an explicitly requested owned lease after work, without artificial GPU activity."""
import argparse,json,os,subprocess,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
def retain(state,returncode):
 policy=ROOT/'KEEP_ALLOCATIONS_20261103.json'
 if not policy.exists() or not json.loads(policy.read_text()).get('enabled'):return
 job=os.environ['SLURM_JOB_ID'];state=Path(state);iteration=0
 while not (state/'RELEASE_ALLOCATION').exists():
  status=subprocess.run(['squeue','-h','-j',job,'-o','%u|%T|%N'],capture_output=True,text=True,timeout=30)
  if status.returncode or not status.stdout.strip():return
  owner,phase,nodes=status.stdout.strip().split('|');assert owner=='zhiyuan'
  if phase not in ('RUNNING','COMPLETING'):return
  value={'utc':time.time(),'job':job,'phase':'allocation_retained_after_task','task_returncode':returncode,'nodes':nodes,'gpu_busy_load_generated':False,'release_marker':'RELEASE_ALLOCATION','lease_expiry_still_enforced_by_scheduler':True}
  p=state/'ALLOCATION_RETAINED.json';tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2));tmp.replace(p)
  if iteration%10==0:print(json.dumps(value),flush=True)
  iteration+=1;time.sleep(30)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--returncode',type=int,default=0);a=p.parse_args();retain(a.state,a.returncode)
