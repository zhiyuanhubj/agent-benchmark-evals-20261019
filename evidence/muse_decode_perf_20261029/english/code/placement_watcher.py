"""Finish owned, explicitly requested placement retries after Slurm requeuehold."""
import argparse
import fcntl
import json
import os
import pwd
from pathlib import Path
from placement import finish_placement_retry


def save(p,d):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(d,indent=2)+'\n');os.replace(tmp,p)


def main(root):
    lock=(root/'placement-watcher.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    jobs=json.loads((root/'ALLOCATIONS.json').read_text())['jobs']
    api=root/'PUBLIC_API.json'
    if api.exists():jobs.append(json.loads(api.read_text()))
    owner=pwd.getpwuid(os.getuid()).pw_name
    for job in jobs:
        state=Path(job['state']);plan=json.loads((state/'PLAN.json').read_text())
        assert plan['jobs'][plan['precision']]==job['job']
        if finish_placement_retry(state,job['job'],owner,save):
            print(json.dumps({'job':job['job'],'placement_retry_released':True}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();main(a.root)
