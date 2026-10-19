"""Audited supplementary selection including verifier-complete Harbor gaps."""
import hashlib
import json
import sys
from pathlib import Path
ROOT = Path('/fsx/home/zhiyuan/.private/muse_spark_open_20261016/review_bench_20261018')
sys.path.insert(0, str(ROOT))
from review_infra import pre_response_infrastructure_failure

NATIVE_AUDIT = Path('/fsx/home/zhiyuan/agent-benchmark-evals-20261019/evidence/swe_review_recovery_control.json')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inspect_canonical_split(split, expected_ids):
    recovery = ROOT / 'review_recovery_20261018'
    plan = json.loads((recovery / 'plan.json').read_text())
    originals = plan['original_results'][split]
    assert set(originals) == set(expected_ids), 'Original task coverage changed'
    eligible = set(plan['recover'][split])
    assert eligible == {name for name, row in originals.items() if row['classification']}
    selected = {}
    pending = set(eligible)
    for name, row in originals.items():
        path = Path(row['path'])
        assert sha(path) == row['sha256'], 'Original result mutated'
        result = json.loads(path.read_text())
        assert result['task_name'] == name and result.get('finished_at')
        assert pre_response_infrastructure_failure(path.parent, result) == row['classification']
        if name not in eligible:
            selected[name] = path
    attempted = set()
    for path in (recovery / 'results' / split).glob('*/*/result.json'):
        result = json.loads(path.read_text())
        if not result.get('finished_at'):
            continue
        name = result['task_name']
        assert name in eligible and name not in attempted, 'Unexpected repeated model attempt'
        attempted.add(name)
        if pre_response_infrastructure_failure(path.parent, result):
            continue
        completions = list((path.parent / 'agent/completions').glob('*.json'))
        if result.get('exception_info') and not completions:
            # An unclassified failure before any saved response needs diagnosis;
            # it cannot silently become a model-failure fallback in RRR.
            continue
        assert name not in selected
        selected[name] = path
        pending.remove(name)
    native_selected = {}
    if pending:
        audited = json.loads(NATIVE_AUDIT.read_text())['original_native_verifier_complete_without_harbor_summary']
        assert len(audited) == 10
        for name in sorted(pending):
            key = split + '/' + name
            if key not in audited:
                continue
            audit = audited[key]
            trial = Path(audit['trial'])
            assert trial.parent.parent == recovery / 'results' / split
            assert trial.name.startswith(name + '__') and not (trial / 'result.json').exists()
            candidates = list((recovery / 'results' / split).glob('*/' + name + '__*'))
            sampled = [candidate for candidate in candidates
                       if list((candidate / 'agent/completions').glob('*.json'))]
            assert sampled == [trial], 'Ambiguous sampled review: ' + key
            config = json.loads((trial / 'config.json').read_text())
            lock = json.loads((trial / 'lock.json').read_text())
            assert Path(config['task']['path']).name == name
            assert lock['task']['name'] == name
            assert lock['agent']['model_name'] == 'openai/muse-spark-open-nvfp4'
            trajectory_path = trial / 'agent/trajectory.json'
            trajectory = json.loads(trajectory_path.read_text())
            assert trajectory['steps'][-1]['tool_calls'][0]['function_name'] == 'finish'
            report_path = trial / 'verifier/review_report.json'
            grade_path = trial / 'verifier/report.json'
            reward_path = trial / 'verifier/reward.txt'
            report = json.loads(report_path.read_text())
            grade = json.loads(grade_path.read_text())
            assert report['decision']['recommendation'] in {'approve', 'request_changes'}
            assert grade['recommendation'] == report['decision']['recommendation']
            assert float(reward_path.read_text().strip()) == grade['reward']
            for label, path in [('review_report', report_path), ('verifier_report', grade_path),
                                ('reward', reward_path), ('trajectory', trajectory_path)]:
                assert sha(path) == audit[label + '_sha256'], key + ': ' + label
            native_selected[name] = trial
            pending.remove(name)
    if pending:
        return None
    assert set(selected) | set(native_selected) == set(expected_ids)
    assert set(selected).isdisjoint(native_selected)
    rows = {}
    for name in expected_ids:
        path = selected.get(name)
        trial = path.parent if path else native_selected[name]
        result = json.loads(path.read_text()) if path else None
        report_path = trial / 'verifier/review_report.json'
        report = json.loads(report_path.read_text()) if report_path.exists() else None
        decision = (report or {}).get('decision')
        if isinstance(decision, dict):
            decision = decision.get('recommendation')
        assert decision in {None, 'approve', 'request_changes'}
        files = [trial / 'config.json']
        if path:
            files.append(path)
        else:
            files.extend([trial / 'lock.json', trial / 'agent/trajectory.json',
                          trial / 'verifier/report.json', trial / 'verifier/reward.txt'])
            files.extend(sorted((trial / 'agent/completions').glob('*.json')))
        if report_path.exists():
            files.append(report_path)
        original = originals[name]
        files.append(Path(original['path']))
        rows[name] = dict(trial=str(trial), decision=decision,
            source_hashes={str(p):sha(p) for p in files},
            exception_type=(result.get('exception_info') or {}).get('exception_type') if result else None,
            original_result=original['path'], original_result_sha256=original['sha256'],
            original_infrastructure_classification=original['classification'],
            used_infrastructure_recovery=name in eligible,
            native_verifier_complete_without_harbor_summary=path is None)
    return rows
