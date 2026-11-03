"""Monitor this authorized queue and retry failed startup before any measured data exists."""
import datetime,fcntl,json,os,re,shutil,subprocess,time
import httpx
from activate_bf16 import backend_matches
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
 api=json.loads((R/'PUBLIC_API.json').read_text());renewal=api.get('renewal_job')
 if renewal:
  phase,hosts,_=scheduler(renewal);future_state=Path(api['renewal_state']);future_plan=json.loads((future_state/'PLAN.json').read_text());marker=Path(future_plan['api_runtime_dir'])/'BACKEND.json'
  if phase=='RUNNING' and marker.exists():
   proof=json.loads(marker.read_text());actual_hosts=run(['scontrol','show','hostnames',hosts]).split()
   if backend_matches(proof,renewal,actual_hosts,time.time()):
    try:
     response=httpx.post(proof['native_base']+'/v1/chat/completions',json={'model':'muse-spark-open-bf16','messages':[{'role':'user','content':'What is 2+3? Reply with just the number.'}],'max_tokens':1024,'reasoning_effort':'low','stream':False},timeout=30,trust_env=False);response.raise_for_status();answer=response.json()['choices'][0];assert answer['message'].get('content','').strip()=='5' and answer.get('finish_reason')=='stop'
     previous_job=api['job'];api.update(job=renewal,state=str(future_state));api.pop('renewal_job');api.pop('renewal_state')
     end=re.search(r'EndTime=(\S+)',run(['scontrol','show','job',str(renewal),'-o'])).group(1);api.update(lease_end_utc=end+' UTC',lease_end_unix=datetime.datetime.fromisoformat(end).replace(tzinfo=datetime.timezone.utc).timestamp())
     save(R/'PUBLIC_API.json',api);rt=Path(api['runtime']);cfg=json.loads((rt/'RESTORE.json').read_text());cfg.update(job=renewal,state=str(future_state),backend_runtime_dir=future_plan['api_runtime_dir']);save(rt/'RESTORE.json',cfg)
     entry={**api,'role':'api','replaces_job':previous_job,'submitted_utc':time.time(),'previous_allocation_retained':True};d['jobs'].append(entry);save(REG,d);latest[api['name']]=entry
    except (httpx.HTTPError,AssertionError,KeyError,ValueError) as exc:warnings.append({'job':renewal,'reason':'Standby API not promoted: '+type(exc).__name__})
 for key,e in latest.items():
  phase,hosts,reason=scheduler(e['job']);observations.append({'name':key,'job':e['job'],'role':e['role'],'slurm':phase,'nodes':hosts,'reason':reason})
  retained=Path(e['state'])/'ALLOCATION_RETAINED.json'
  if retained.exists():
   observations[-1]['retained_after_task']=json.loads(retained.read_text())
   if observations[-1]['retained_after_task'].get('task_returncode'):
    warnings.append({'job':e['job'],'reason':'Task failed; allocation retained for diagnosis instead of release.'})
  if e['role'] not in ('api','coding'):continue
  if phase in ('PENDING','RUNNING','CONFIGURING','COMPLETING','SUSPENDED','UNKNOWN'):continue
  state=Path(e['state'])
  if e['role']=='api':
   api=json.loads((R/'PUBLIC_API.json').read_text());renewal=api.get('renewal_job')
   if renewal:
    renewal_phase,_,_=scheduler(renewal)
    if renewal_phase in ('PENDING','RUNNING','CONFIGURING'):
     newstate=api.pop('renewal_state');api.pop('renewal_job');api.update(job=renewal,state=newstate);save(R/'PUBLIC_API.json',api)
     rt=Path(api['runtime']);cfg=json.loads((rt/'RESTORE.json').read_text());cfg.update(job=renewal,state=newstate);save(rt/'RESTORE.json',cfg)
     cfg['backend_runtime_dir']=json.loads((Path(newstate)/'PLAN.json').read_text())['api_runtime_dir'];save(rt/'RESTORE.json',cfg)
     d['jobs'].append({**api,'role':'api','replaces_job':e['job'],'submitted_utc':time.time()});save(REG,d)
     continue
  if e['role']=='coding' and phase=='COMPLETED':continue
  summaries=list(state.glob('bf16/spec-*/*/c*/summary.json'))
  if e['role']=='coding' and summaries:
   warnings.append({'job':e['job'],'reason':'Partial measured data retained; inspect failed case before resubmitting.'});continue
  number=e.get('resubmission_count',0)
  if number>=2:
   warnings.append({'job':e['job'],'reason':'Two startup allocation retries exhausted; inspect logs.'});continue
  newstate=R/(key+'-retry'+str(number+1));newstate.mkdir(exist_ok=False)
  plan=json.loads((state/'PLAN.json').read_text());plan.pop('reuse_verified_weights_state',None);shutil.copy2(state/'coding_prompts.jsonl',newstate/'coding_prompts.jsonl')
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
 # Give the API renewal first use of our own queued resources near lease end.
 # Holds apply only to this registry's owned PENDING evaluation jobs.
 api=json.loads((R/'PUBLIC_API.json').read_text());end=api.get('lease_end_unix');held=api.get('held_for_api_renewal',[])
 public=Path(api['runtime'])/'PUBLIC_STATUS.json';public_status=json.loads(public.read_text()) if public.exists() else {}
 if api.get('renewal_job') and end and 0<end-time.time()<600:
  for e in latest.values():
   if e['role'] not in ('coding','point_repair','deepinfer_h200_dependency_probe'):continue
   phase,_,reason=scheduler(e['job'])
   if phase=='PENDING' and reason!='JobHeldUser' and e['job'] not in held:
    run(['scontrol','hold',str(e['job'])]);held.append(e['job'])
  api['held_for_api_renewal']=held;save(R/'PUBLIC_API.json',api)
 elif held and public_status.get('phase')=='active' and public_status.get('job')==api['job']:
  for job in held:
   phase,_,reason=scheduler(job)
   if phase=='PENDING' and reason=='JobHeldUser':run(['scontrol','release',str(job)])
  api['held_for_api_renewal']=[];save(R/'PUBLIC_API.json',api)
 save(R/'RECOVERY_HEALTH_20261103.json',{'utc':time.time(),'queue':observations,'warnings':warnings,'stop_marker':'STOP_RESOURCE_RECOVERY','only_owned_jobs_modified':True})

if __name__=='__main__':
 with (R/'resource-recovery-20261103.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
