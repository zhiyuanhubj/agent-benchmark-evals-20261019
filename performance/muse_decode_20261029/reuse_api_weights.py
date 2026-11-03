"""Reuse this allocation's freshly hashed, unchanged BF16 files during API handoff."""
import hashlib,json,os,socket,subprocess
from pathlib import Path
import argparse
p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);a=p.parse_args()
plan=json.loads((a.state/'PLAN.json').read_text());job=int(os.environ['SLURM_JOB_ID']);assert plan['jobs']['bf16']==job
hosts=subprocess.check_output(['scontrol','show','hostnames',os.environ['SLURM_JOB_NODELIST']],text=True).split();rank=hosts.index(socket.gethostname())
source=Path(plan['reuse_verified_weights_state'])/'bf16'/('rank'+str(rank))/'weights.json';proof=json.loads(source.read_text());manifest=plan['models']['bf16'];weights=Path(proof['path']).resolve();cutoff=source.stat().st_mtime
assert weights.is_relative_to(Path('/opt/dlami/nvme')) and proof['complete'] and proof['revision']==manifest['revision']
assert set(proof['verified_files'])=={r['file'] for r in manifest['files']}
for row in manifest['files']:
 f=weights/row['file'];s=f.stat();assert f.resolve().is_relative_to(weights) and s.st_size==row['bytes'] and s.st_mtime<=cutoff and s.st_ctime<=cutoff, str(f)
target=a.state/'bf16'/('rank'+str(rank));target.mkdir(parents=True,exist_ok=True)
proof.update(reused_verified_state=str(source),source_receipt_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),file_metadata_unchanged_since_verification=True)
(target/'weights.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps({'rank':rank,'reused_files':len(manifest['files']),'revision':manifest['revision']}))
