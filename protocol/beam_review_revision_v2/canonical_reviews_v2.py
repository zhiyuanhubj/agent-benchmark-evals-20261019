"""Select Beam reviews, treating malformed agent reports as missing decisions."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inspect_canonical_split(split, expected_ids):
    queue = ROOT / 'queue'
    plan = json.loads((queue / 'queue-plan.json').read_text())
    assert set(plan['splits'][split]['tasks']) == set(expected_ids)
    rows = {}
    for path in (queue / 'results' / split).glob('*/*/result.json'):
        result = json.loads(path.read_text())
        if not result.get('finished_at'):
            continue
        name = result['task_name']
        assert name in expected_ids and name not in rows
        completions = list((path.parent / 'agent/completions').glob('*.json'))
        if result.get('exception_info') and not completions:
            # Diagnose rather than convert an unexecuted task to model failure.
            return None
        report_path = path.parent / 'verifier/review_report.json'
        report_parse_error = None
        if report_path.exists():
            try:
                report = json.loads(report_path.read_text())
            except json.JSONDecodeError as error:
                # The official revision generator skips an unparseable review
                # report. Preserve the original bytes and score it as a model
                # failure; never recover a leading JSON object from extra text.
                report = None
                report_parse_error = str(error)
        else:
            report = None
        decision = (report or {}).get('decision')
        if isinstance(decision, dict):
            decision = decision.get('recommendation')
        assert decision in {None,'approve','request_changes'}
        files = [path, path.parent / 'config.json']
        if report_path.exists():
            files.append(report_path)
        rows[name] = dict(trial=str(path.parent), decision=decision,
            source_hashes={str(p):sha(p) for p in files},
            exception_type=(result.get('exception_info') or {}).get('exception_type'),
            report_parse_error=report_parse_error)
    return rows if set(rows) == set(expected_ids) else None
