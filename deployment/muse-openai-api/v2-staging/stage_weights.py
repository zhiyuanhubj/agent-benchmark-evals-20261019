"""Stage pinned BF16 files from another node within this owned allocation."""
import json,sys,os,time,hashlib,socket
from pathlib import Path
from http.server import ThreadingHTTPServer
r=Path(__file__).parent.parent;sys.path.insert(0,str(r));from native_transfer import source_handler as handler,fetch_native as fetch
state=Path(__file__).parent;plan=json.loads((state/'PLAN.json').read_text());manifest=plan['models']['bf16'];token=(state/'peer-transfer.key').read_text().strip()
assert os.environ['SLURM_JOB_ID']=='3388'
if sys.argv[1]=='source':
 assert socket.gethostname()=='ip-10-1-112-220'
 prior=r/'bf16-8k-c256-repair-20261103/bf16/rank1/weights.json';proof=json.loads(prior.read_text());weights=Path(proof['path']);cutoff=prior.stat().st_mtime
 assert proof['complete'] and proof['revision']==manifest['revision'] and set(proof['verified_files'])=={x['file'] for x in manifest['files']}
 for row in manifest['files']:
  p=weights/row['file'];st=p.stat();assert p.resolve().is_relative_to(weights.resolve()) and st.st_size==row['bytes'] and st.st_mtime<=cutoff and st.st_ctime<=cutoff,str(p)
 target=state/'bf16/rank1';target.mkdir(parents=True,exist_ok=True);proof.update(reused_verified_receipt=str(prior),source_receipt_sha256=hashlib.sha256(prior.read_bytes()).hexdigest(),file_metadata_unchanged_since_verification=True);(target/'weights.json').write_text(json.dumps(proof,indent=2)+'\n')
 ThreadingHTTPServer(('10.1.112.220',31481),handler(weights,manifest,token)).serve_forever()
else:
 assert sys.argv[1]=='fetch' and socket.gethostname()=='ip-10-1-25-253'
 weights=Path('/opt/dlami/nvme/zhiyuan-muse-perf-3388-0/weights')
 result=fetch('http://10.1.112.220:31481',weights,manifest,token,state/'PEER_TRANSFER.json',workers=16)
 target=state/'bf16/rank0';target.mkdir(parents=True,exist_ok=True);(target/'weights.json').write_text(json.dumps({'path':str(weights),'repo':manifest['repo'],'revision':manifest['revision'],'complete':True,'verified_files':result['verified_files'],'verified_by':'streaming peer transfer SHA-256','transfer_receipt':str(state/'PEER_TRANSFER.json')},indent=2)+'\n')
 print(json.dumps({'valid':result['valid'],'bytes_received':result['bytes_received'],'elapsed_seconds':result['elapsed_seconds']}))
