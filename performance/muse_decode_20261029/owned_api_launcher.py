"""Head-node API coordinator using the verified scope of an existing owned allocation."""
import argparse,json,os,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);a=p.parse_args()
plan=json.loads((a.state/'PLAN.json').read_text());job=plan['jobs']['bf16']
r=subprocess.run(['squeue','-h','-j',str(job),'-o','%u|%T|%D|%N'],capture_output=True,text=True,check=True)
if not r.stdout.strip():raise SystemExit(0)
owner,phase,count,nodes=r.stdout.strip().split('|');assert owner=='zhiyuan' and count=='2'
if phase!='RUNNING':raise SystemExit(0)
env=os.environ.copy()
for key in list(env):
 if key.startswith('SLURM_STEP_'):env.pop(key)
env.update(SLURM_JOB_ID=str(job),SLURM_JOBID=str(job),SLURM_JOB_NODELIST=nodes,
           SLURM_JOB_NUM_NODES='2',SLURM_NNODES='2',SLURM_CPUS_PER_TASK='96',SLURM_NTASKS='2',MUSE_API_HEAD_COORDINATOR='1')
os.execve(sys.executable,[sys.executable,'-u',str(Path(__file__).parent/'recovery_entry.py'),'--state',str(a.state)],env)
