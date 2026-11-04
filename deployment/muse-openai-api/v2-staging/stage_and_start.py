"""Start the BF16 v2 guardian only after both node-local weight receipts pass."""
import os,subprocess,sys,time,json
from pathlib import Path
import httpx
state=Path(__file__).parent;r=state.parent;py='/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
base=['srun','--jobid=3388','--overlap','--exact','--gres=none','-N1','-n1','-c32']
with (state/'peer-source.log').open('a') as log:
 source=subprocess.Popen([*base,'-w','ip-10-1-112-220',py,str(state/'stage_weights.py'),'source'],stdout=log,stderr=subprocess.STDOUT)
 try:
  token=(state/'peer-transfer.key').read_text().strip()
  for _ in range(30):
   if source.poll() is not None:raise RuntimeError('Verified weight source failed')
   try:
    resp=httpx.get('http://10.1.112.220:31481/config.json',headers={'Authorization':'Bearer '+token},timeout=3,trust_env=False);resp.raise_for_status();break
   except httpx.HTTPError:time.sleep(2)
  else:raise RuntimeError('Weight source did not become ready')
  subprocess.run([*base,'-w','ip-10-1-25-253',py,str(state/'stage_weights.py'),'fetch'],check=True)
 finally:
  source.terminate()
  try:source.wait(timeout=30)
  except subprocess.TimeoutExpired:source.kill()
unit=Path.home()/'.config/systemd/user/muse-api-v2-handoff-3388-20261104.service'
unit.write_text('[Unit]\nDescription=Muse BF16 v2 API on retained owned allocation 3388\nAfter=network-online.target\nStartLimitIntervalSec=1800\nStartLimitBurst=3\n\n[Service]\nType=simple\nWorkingDirectory='+str(r)+'\nExecStart='+py+' -u '+str(r/'owned_api_launcher.py')+' --state '+str(state)+'\nRestart=on-failure\nRestartSec=30\n\n[Install]\nWantedBy=default.target\n')
subprocess.run(['systemctl','--user','daemon-reload'],check=True);subprocess.run(['systemctl','--user','enable','--now',unit.name],check=True)
print(json.dumps({'stage_complete':True,'api_guardian_started':unit.name}))
