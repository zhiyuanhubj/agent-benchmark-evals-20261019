"""Check pinned BF16 weight reuse and disk capacity before distributed staging."""
import json
import hashlib
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor


def verify_files(weights, manifest, workers=8):
    weights=Path(weights)
    def verify(row):
        target=weights/row['file']
        assert target.is_file() and target.stat().st_size==row['bytes'], str(target)
        assert row['algorithm'] in ('sha256','git-blob-sha1')
        h=hashlib.sha256() if row['algorithm']=='sha256' else hashlib.sha1()
        if row['algorithm']=='git-blob-sha1':h.update(('blob '+str(row['bytes'])+'\0').encode())
        with target.open('rb') as stream:
            for block in iter(lambda:stream.read(16*2**20),b''):h.update(block)
        assert h.hexdigest()==row['expected'], 'Pinned weight mismatch: '+str(target)
        return row['file']
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(verify,manifest['files']))


def choose_weights(nvme, local, manifest, free_bytes, reserve=250 * 2**30):
    nvme, local = Path(nvme), Path(local)
    def complete(path):
        return all((path / row['file']).is_file()
                   and (path / row['file']).stat().st_size == row['bytes']
                   and (path / row['file']).resolve().is_relative_to(path.resolve())
                   for row in manifest['files'])
    weights = next((p for p in sorted(nvme.glob('zhiyuan-muse-perf-*/weights')) if complete(p)), local / 'weights')
    missing = sum(row['bytes'] for row in manifest['files']
                  if not (weights / row['file']).is_file()
                  or (weights / row['file']).stat().st_size != row['bytes'])
    reusable = complete(weights)
    return {'path': str(weights), 'reuses_complete_weights': reusable,
            'missing_bytes': missing, 'free_bytes': free_bytes, 'reserve_bytes': reserve,
            'valid': reusable or free_bytes > missing + reserve,
            'reason': None if reusable or free_bytes > missing + reserve else 'insufficient_local_NVMe'}


def retry_placement(state, plan, job, hosts, started, save):
    """Requeue only our allocation, only for fresh disk-capacity failures."""
    keep = Path(plan['controller_root']) / 'KEEP_ALLOCATIONS_20261103.json' if plan.get('controller_root') else None
    if keep and keep.exists() and json.loads(keep.read_text()).get('enabled'):
        return False  # User requested retention: diagnose the current node instead of releasing it.
    limit = plan.get('placement_retry_limit', 0)
    journal = state / 'PLACEMENT_RETRIES.json'
    previous = json.loads(journal.read_text()) if journal.exists() else []
    if len(previous) >= limit:
        return False
    bad = set()
    for path in (state / plan['precision']).glob('rank*/placement.json'):
        d = json.loads(path.read_text())
        if (d.get('job') == job and d.get('hostname') in hosts
                and d.get('updated_unix', 0) >= started
                and d.get('reason') == 'insufficient_local_NVMe'):
            bad.add(d['hostname'])
    if not bad:
        return False
    excluded = set(plan.get('excluded_nodes', [])) | bad
    for item in previous:
        excluded.update(item['excluded_nodes'])
    attempt = {'updated_unix': time.time(), 'job': job, 'failed_nodes': sorted(bad),
               'action': 'requeuehold_for_placement',
               'excluded_nodes': sorted(excluded), 'reason': 'insufficient_local_NVMe'}
    save(journal, previous + [attempt])
    save(state / 'status.json', {'phase': 'requeue_requested_after_disk_capacity_failure', **attempt})
    # Slurm permits changing placement constraints only while PENDING. The
    # head-node watcher updates exclusions after this running batch is held.
    subprocess.run(['scontrol', 'requeuehold', str(job)], check=True)
    return True


def finish_placement_retry(state,job,owner,save):
    journal=state/'PLACEMENT_RETRIES.json'
    if not journal.exists():return False
    entries=json.loads(journal.read_text())
    if not entries or entries[-1].get('action')!='requeuehold_for_placement' or entries[-1].get('completed_unix'):
        return False
    attempt=entries[-1]
    assert attempt['job']==job
    r=subprocess.run(['squeue','-h','-j',str(job),'-o','%u|%T|%r'],capture_output=True,text=True,check=True)
    if not r.stdout.strip():return False
    actual,phase,reason=r.stdout.strip().split('|')
    assert actual==owner,'Refusing to update another owner allocation'
    if phase!='PENDING' or reason not in ('JobHeldUser','job requeued in held state','job_requeued_in_held_state'):
        return False
    subprocess.run(['scontrol','update',f'JobId={job}','NodeList=',
                    'ExcNodeList='+','.join(attempt['excluded_nodes'])],check=True)
    subprocess.run(['scontrol','release',str(job)],check=True)
    attempt['completed_unix']=time.time();save(journal,entries)
    save(state/'status.json',{'phase':'queued_after_disk_placement_retry','job':job,'updated_unix':time.time(),
                             'excluded_nodes':attempt['excluded_nodes']})
    return True
