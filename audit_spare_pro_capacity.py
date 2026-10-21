#!/usr/bin/env python3
"""Audit disjoint spare-replica Pro shards, preserving round and task identity."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = Path('/fsx/home/zhiyuan/.private/spare_pro_capacity_20261021')
RUNNER = ROOT / 'protocol/run_spare_pro_capacity_20261021.py'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    rounds, claims = {}, []
    for path in sorted((WORK/'claims').glob('*/claim.json')):
        claim = json.loads(path.read_text())
        assert claim['runner_sha256'] == sha(RUNNER)
        assert claim['command_sha256'] == sha(path.parent/'command.json')
        assert all(sha(p) == digest for p, digest in claim['source_sha256'].items())
        ids = set(claim['task_ids'])
        assert len(ids) == len(claim['task_ids']) == claim['expected']
        group = f"{claim['model']}/round_{claim['round']}"
        row = rounds.setdefault(group, {'model':claim['model'], 'round':claim['round'],
            'expected_round':731, 'declared_tasks':[], 'records':{}, 'shards':[]})
        assert not ids.intersection(row['declared_tasks'])
        row['declared_tasks'] += claim['task_ids']
        records = {}
        run_dir = WORK/'results'/claim['run_id']
        for result_path in sorted(run_dir.glob('*/*/details/*/attempt-1/result.json')):
            try:
                result = json.loads(result_path.read_text())
            except json.JSONDecodeError:
                continue  # A writer has not yet atomically completed its native result.
            task_path = result_path.parent.parent/'task.json'
            task = json.loads(task_path.read_text())['task_id']
            assert task in ids and task not in records and task not in row['records']
            evaluation = ((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {}
            correct = (result.get('metrics') or {}).get('correct')
            graded = evaluation.get('completed') is True and type(correct) is bool
            records[task] = {'result':str(result_path), 'result_sha256':sha(result_path),
                             'task_sha256':sha(task_path), 'graded':graded,
                             'success':correct if graded else None}
        row['records'].update(records)
        service = f"pro-spare-capacity-{claim['allocation']}-20261021.service"
        phase = subprocess.run(['systemctl','--user','is-active',service],
                                capture_output=True,text=True).stdout.strip()
        row['shards'].append({'allocation':claim['allocation'], 'shard':claim['shard'],
            'run_id':claim['run_id'], 'expected':len(ids), 'native_terminal':len(records),
            'service':phase, 'started':(path.parent/'started.json').exists(),
            'exit':json.loads((path.parent/'exit.json').read_text()) if (path.parent/'exit.json').exists() else None,
            'claim_sha256':sha(path)})
        claims.append(claim)
    for row in rounds.values():
        row.update(terminal=len(row['records']), graded=sum(r['graded'] for r in row['records'].values()),
                   success=sum(r['success'] is True for r in row['records'].values()),
                   accuracy=None, status='partial_independent_draw')
    original = json.loads((ROOT/'evidence/muse_nvfp4_pro_r2_shard0_progress.json').read_text())
    original_claim = json.loads((ROOT/'evidence/muse_nvfp4_pro_r2_shard0_claim.json').read_text())
    if 'muse/round_2' in rounds:
        second = rounds['muse/round_2']
        assert not set(original_claim['task_ids']).intersection(second['declared_tasks'])
        assert len(set(original_claim['task_ids'])|set(second['declared_tasks'])) == 731
        second['with_original_shard0'] = {'expected':731, 'terminal':second['terminal']+original['terminal'],
            'graded':second['graded']+original['graded'], 'success':second['success']+original['success'],
            'accuracy':None, 'qualification':'Disjoint task-ID union of the four declared second-round shards; '
                'not a full score until all 731 native grades and released I/O are verified.'}
    output = {'generated_utc':datetime.now(timezone.utc).isoformat(), 'rounds':rounds,
        'qualification':'Independent draws stay separate. Newly started work and model-serving memory '
            'are not evidence of completed grades or sustained GPU utilization.'}
    (ROOT/'evidence/spare_pro_capacity_progress_20261021.json').write_text(json.dumps(output,indent=2)+'\n')
    (ROOT/'evidence/spare_pro_capacity_claims_20261021.json').write_text(json.dumps(claims,indent=2)+'\n')
    print(json.dumps({k:{n:r[n] for n in ('terminal','graded','success')} for k,r in rounds.items()}))


if __name__=='__main__':
    main()
