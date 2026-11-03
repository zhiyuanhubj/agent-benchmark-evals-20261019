"""Monitor this authorized queue and retry failed startup before any measured data exists."""
import fcntl,json,os,shutil,subprocess,time
from pathlib import Path

R=Path(__file__).resolve().parent
REG=R/'RESOURCE_RECOVERY_20261103.json'
def run(args):return subprocess.run(args,check=True,text=True,capture_output=True,timeout=45).stdout.strip()
def save(p,d):
 tmp=p.with_name(p.name+'.'+str(os.getpid())+'.tmp');tmp.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');tmp.replace(p)
def scheduler(job):
 p=subprocess.run(['squeue','-h','-j',str(job),'-o','%u|%T|%N|%r'],text=True,capture_output=True,timeout=30)
 if p.returncode and 'Invalid job id' not in p.stderr:p.check_returncode()
 if p.stdout.strip():
  owner,phase,hosts,reason=p.stdout.strip().split('|');assert owner=='zhiyuan';return phase,hosts,reason
 acct=run(['sacct','-X','-j',str(job),'-n','-P','-o','State']).splitlines()
 return (acct[0].split('|')[0].split()[0].rstrip('+') if acct else 'UNKNOWN'),'',''

def main():
 if (R/'STOP_RESOURCE_RECOVERY').exists():return
 d=json.loads(REG.read_text());latest={}
 for entry in d['jobs']:
  key=entry.get('name',entry['role']);latest[key]=entry
 observations=[];warnings=[]
 for key,e in latest.items():
  phase,hosts,reason=scheduler(e['job']);observations.append({'name':key,'job':e['job'],'role':e['role'],'slurm':phase,'nodes':hosts,'reason':reason})
  if e['role'] not in ('api','coding'):continue
  if phase in ('PENDING','RUNNING','CONFIGURING','COMPLETING','SUSPENDED','UNKNOWN'):continue
  state=Path(e['state'])
  if e['role']=='coding' and phase=='COMPLETED':continue
  summaries=list(state.glob('bf16/spec-*/*/c*/summary.json'))
  if e['role']=='coding' and summaries:
   warnings.append({'job':e['job'],'reason':'Partial measured data retained; inspect failed case before resubmitting.'});continue
  number=e.get('resubmission_count',0)
  if number>=2:
   warnings.append({'job':e['job'],'reason':'Two startup allocation retries exhausted; inspect logs.'});continue
  newstate=R/(key+'-retry'+str(number+1));newstate.mkdir(exist_ok=False)
  plan=json.loads((state/'PLAN.json').read_text());shutil.copy2(state/'coding_prompts.jsonl',newstate/'coding_prompts.jsonl')
  args=['sbatch','--parsable','--hold','--nodes=2','--job-name=muse-'+key+'-r'+str(number+1),'--output='+str(newstate/'slurm-%j.log'),'--time='+('1-00:00:00' if e['role']=='api' else '08:00:00'),'--time-min='+('08:00:00' if e['role']=='api' else '03:00:00')]
  excluded=plan.get('excluded_nodes',[])
  if excluded:args.append('--exclude='+','.join(excluded))
  job=int(run([*args,str(R/'recovery_run.sbatch'),str(newstate)]).split(';')[0]);plan['jobs']={'bf16':job};save(newstate/'PLAN.json',plan)
  updated={**e,'job':job,'state':str(newstate),'resubmission_count':number+1,'replaces_job':e['job'],'submitted_utc':time.time()};d['jobs'].append(updated);save(REG,d)
  if e['role']=='api':
   api=json.loads((R/'PUBLIC_API.json').read_text());api.update(job=job,state=str(newstate));save(R/'PUBLIC_API.json',api)
   rt=Path(api['runtime']);cfg=json.loads((rt/'RESTORE.json').read_text());cfg.update(job=job,state=str(newstate));save(rt/'RESTORE.json',cfg)
  else:
   allocations=json.loads((R/'ALLOCATIONS.json').read_text());allocations['jobs'].append(updated);allocations['requested_nodes']=sum(x['nodes'] for x in allocations['jobs']);save(R/'ALLOCATIONS.json',allocations)
  run(['scontrol','release',str(job)])
 save(R/'RECOVERY_HEALTH_20261103.json',{'utc':time.time(),'queue':observations,'warnings':warnings,'stop_marker':'STOP_RESOURCE_RECOVERY','only_owned_jobs_modified':True})

if __name__=='__main__':
 with (R/'resource-recovery-20261103.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
