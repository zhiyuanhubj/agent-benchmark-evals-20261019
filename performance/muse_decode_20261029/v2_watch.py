"""Promote only the independently verified BF16 standby for the public v2 API."""
import datetime,fcntl,json,re,subprocess,time
from pathlib import Path
import httpx
from activate_bf16 import backend_matches
from recovery_watch import scheduler,save,run
R=Path(__file__).resolve().parent

def main():
 p=R/'PUBLIC_API_V2.json';api=json.loads(p.read_text());renewal=api.get('renewal_job')
 if not renewal:return
 phase,hosts,_=scheduler(renewal);future=Path(api['renewal_state']);plan=json.loads((future/'PLAN.json').read_text());marker=Path(plan['api_runtime_dir'])/'BACKEND.json'
 if phase=='RUNNING' and marker.exists():
  proof=json.loads(marker.read_text());nodes=run(['scontrol','show','hostnames',hosts]).split()
  if backend_matches(proof,renewal,nodes,time.time(),'bf16'):
   response=httpx.post(proof['native_base']+'/v1/chat/completions',json={'model':'muse-spark-open-bf16','messages':[{'role':'user','content':'What is 2+3? Reply with just the number.'}],'reasoning_effort':'low','max_tokens':1024,'stream':False},timeout=60,trust_env=False);response.raise_for_status();choice=response.json()['choices'][0];assert choice['finish_reason']=='stop' and choice['message'].get('content','').strip()=='5'
   previous=api['job'];api.update(job=renewal,state=str(future),previous_allocation_retained=True);api.pop('renewal_job');api.pop('renewal_state')
   end=re.search(r'EndTime=(\S+)',run(['scontrol','show','job',str(renewal),'-o'])).group(1);api.update(lease_end_utc=end+' UTC',lease_end_unix=datetime.datetime.fromisoformat(end).replace(tzinfo=datetime.timezone.utc).timestamp());save(p,api)
   rt=Path(api['runtime']);cfg=json.loads((rt/'RESTORE.json').read_text());cfg.update(job=renewal,state=str(future),precision='bf16',backend_runtime_dir=plan['api_runtime_dir']);save(rt/'RESTORE.json',cfg)
   save(R/'API_V2_PROMOTION.json',{'previous_job':previous,'job':renewal,'utc':time.time(),'native_canary_passed':True,'previous_allocation_retained':True})
   return
 active,_,_=scheduler(api['job'])
 if active not in ('RUNNING','CONFIGURING','PENDING') and phase in ('RUNNING','CONFIGURING','PENDING'):
  api.update(job=renewal,state=str(future));api.pop('renewal_job');api.pop('renewal_state');save(p,api)
  rt=Path(api['runtime']);cfg=json.loads((rt/'RESTORE.json').read_text());cfg.update(job=renewal,state=str(future),precision='bf16',backend_runtime_dir=plan['api_runtime_dir']);save(rt/'RESTORE.json',cfg)
 save(R/'API_V2_CONTINUITY_HEALTH.json',{'utc':time.time(),'job':api['job'],'active_slurm_state':active,'standby_job':renewal,'standby_slurm_state':phase})

if __name__=='__main__':
 with (R/'api-v2-continuity.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);main()
