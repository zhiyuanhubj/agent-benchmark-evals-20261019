"""Check pinned BF16 weight reuse and disk capacity before distributed staging."""
import json
import subprocess
import time
from pathlib import Path


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
               'excluded_nodes': sorted(excluded), 'reason': 'insufficient_local_NVMe'}
    save(journal, previous + [attempt])
    subprocess.run(['scontrol', 'update', f'JobId={job}', 'ExcNodeList=' + ','.join(sorted(excluded))], check=True)
    save(state / 'status.json', {'phase': 'requeue_requested_after_disk_capacity_failure', **attempt})
    subprocess.run(['scontrol', 'requeue', str(job)], check=True)
    return True
