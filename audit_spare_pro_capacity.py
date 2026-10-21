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


def native_records(run_dir, ids):
    records = {}
    for path in sorted(run_dir.glob('*/*/details/*/attempt-1/result.json')):
        try:
            result = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        task_path = path.parent.parent/'task.json'
        task = json.loads(task_path.read_text())['task_id']
        assert task in ids and task not in records
        evaluation = ((result.get('meta') or {}).get('benchmark') or {}).get('eval_raw_data') or {}
        correct = (result.get('metrics') or {}).get('correct')
        graded = evaluation.get('completed') is True and type(correct) is bool
        turns = [s.get('assistant_content') for s in (result.get('trajectory') or {}).get('steps', [])]
        turns = [turn for turn in turns if isinstance(turn, dict)]
        records[task] = {'result':str(path), 'result_sha256':sha(path),
            'task_sha256':sha(task_path), 'graded':graded, 'success':correct if graded else None,
            'assistant_turns':len(turns), 'nonempty_thinking_turns':sum(
                bool((turn.get('reasoning_content') or '').strip()) for turn in turns)}
    return records


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
        run_dir = WORK/'results'/claim['run_id']
        records = native_records(run_dir, ids)
        assert not records.keys() & row['records'].keys()
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
    recovery = WORK/'recovery-2928'
    if (recovery/'plan.json').exists():
        plan = json.loads((recovery/'plan.json').read_text())
        assert plan['runner_sha256'] == sha(ROOT/'protocol/recover_pro_capacity_timeout_20261021.py')
        assert plan['original_claim_sha256'] == sha(plan['original_claim'])
        assert all(sha(p) == digest for p, digest in plan['native_proof_sha256'].items())
        original_claim = json.loads(Path(plan['original_claim']).read_text())
        pending, started = set(plan['pending_task_ids']), set(plan['started_task_ids'])
        assert not pending & started and pending | started == set(original_claim['task_ids'])
        row = rounds['muse/round_3']
        progress = {'plan_sha256':sha(recovery/'plan.json'), 'never_started':len(pending),
            'interrupted_preserved':plan['interrupted_task_ids'], 'status':'waiting_for_allocation'}
        if (recovery/'started.json').exists():
            receipt = json.loads((recovery/'started.json').read_text())
            assert receipt['plan_sha256'] == sha(recovery/'plan.json')
            assert receipt['command_sha256'] == sha(recovery/'continuation-command.json')
            command = json.loads((recovery/'continuation-command.json').read_text())
            assert set(json.loads(command[command.index('--benchmark-params')+1])['sample_ids']) == pending
            records = native_records(WORK/'results'/receipt['run_id'], pending)
            assert not records.keys() & row['records'].keys()
            row['records'].update(records)
            progress.update(status='started', receipt=receipt, native_terminal=len(records))
        row['allocation_timeout_continuation'] = progress
        (ROOT/'evidence/capacity_timeout_recovery_20261021.json').write_text(
            json.dumps({'plan':plan, 'progress':progress},indent=2)+'\n')
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
