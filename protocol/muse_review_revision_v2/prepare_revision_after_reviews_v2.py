"""Prepare Muse revisions from the complete audited native reviewer outcomes."""
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
sys.path.insert(0, '/fsx/home/zhiyuan/agent-benchmark-evals-20261019')
from review_native_selection import inspect_canonical_split

ROOT = Path(__file__).resolve().parent
REVISION = ROOT / 'revision'
plan_bytes = (REVISION / 'task-preparation-plan-v2.json').read_bytes()
PLAN = json.loads(plan_bytes)
LOCK = (REVISION / 'task-preparation-controller.lock').open('a')
fcntl.flock(LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
STATE = {'plan_sha256': hashlib.sha256(plan_bytes).hexdigest(), 'phase': 'starting',
         'splits': {}, 'complete': False, 'model_generation_started': False}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def save():
    STATE['utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    write(REVISION / 'task-preparation-current.json', STATE)


def unit_state(unit):
    text = subprocess.check_output(['systemctl', '--user', 'show', unit,
        '-p', 'MainPID', '-p', 'ActiveState', '-p', 'Result'], text=True)
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def verify_sources():
    for path, expected in {**PLAN['source_files_sha256'], **PLAN['dataset_cache_sha256']}.items():
        assert sha(path) == expected, 'Official source or frozen dataset cache changed: ' + path
    assert sha(ROOT / 'state/swe-task-preparation.json') == PLAN['source_task_preparation_sha256']
    assert sha(REVISION / 'prep-environment-freeze.txt') == PLAN['prep_environment_freeze_sha256']


def check_grader_control(folder_name, unit, job_name, replay_name):
    folder = REVISION / folder_name
    state = unit_state(unit)
    if state.get('MainPID') != '0' or state.get('ActiveState') in {'active', 'activating'}:
        return False
    claim = json.loads((folder / 'plan.json').read_text())
    job = folder / 'results' / job_name
    paths = list(job.glob('*/result.json'))
    assert len(paths) == 1, 'Terminated grader preflight has no unique trial result'
    result_path = paths[0]
    result = json.loads(result_path.read_text())
    assert result.get('finished_at') and not result.get('exception_info'), 'Grader preflight failed'
    assert result['verifier_result']['rewards']['reward'] == claim['expected_reward']
    report_path = result_path.parent / 'verifier/report.json'
    report = json.loads(report_path.read_text())[claim['instance_id']]
    assert report['resolved'] is bool(claim['expected_reward'])
    f2p = report['tests_status']['FAIL_TO_PASS']
    expected_category = 'success' if claim['expected_reward'] else 'failure'
    assert f2p[expected_category], 'Expected F2P tests did not execute'
    assert not report['tests_status']['PASS_TO_PASS']['failure'], 'P2P regression in grader control'
    replay_path = result_path.parent / 'agent' / replay_name
    replay = json.loads(replay_path.read_text())
    assert replay['returncode'] == 0
    if claim['expected_reward']:
        replay_output = json.loads(replay['stdout'])
        assert replay_output['candidate_patch_sha256'] == claim['candidate_patch_sha256']
    else:
        assert replay['stdout'].strip() == claim['expected_base_commit']
    assert not list((result_path.parent / 'agent/completions').glob('*.json'))
    receipt = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'passed': True, 'purpose': 'Original-candidate grader validation only; excluded from model metrics.',
        'expected_reward': claim['expected_reward'], 'actual_reward': result['verifier_result']['rewards']['reward'],
        'instance_id': claim['instance_id'], 'no_model_generation_requested': True,
        'sources_sha256': {str(p): sha(p) for p in [folder / 'plan.json', result_path, report_path, replay_path]},
        'fail_to_pass_success_count': len(f2p['success']),
        'fail_to_pass_failure_count': len(f2p['failure'])}
    path = folder / 'receipt.json'
    if path.exists():
        previous = json.loads(path.read_text())
        assert previous['passed'] and previous['sources_sha256'] == receipt['sources_sha256']
    else:
        write(path, receipt)
    return True


def preflight_ready():
    positive = check_grader_control('grader-preflight', PLAN['grader_preflight_unit'],
        'swe-review-original-candidate-grader-preflight', 'candidate-replay.json')
    negative = check_grader_control('grader-negative-preflight', PLAN['grader_negative_preflight_unit'],
        'swe-review-unmodified-base-grader-preflight', 'unmodified-base.json')
    return positive and negative


def inspect_split(split, spec):
    folder = ROOT / 'swe_review' / split
    exit_path = folder / 'controller-exit.json'
    if not exit_path.exists():
        return None
    assert json.loads(exit_path.read_text())['returncode'] == 0, 'Review controller needs inspection: ' + split
    state = unit_state(spec['review_unit'])
    if state.get('MainPID') != '0' or state.get('ActiveState') in {'active', 'activating'}:
        return None
    # Raw original coverage includes registry/allocation failures that never
    # sampled a response. Wait for their one declared infrastructure recovery;
    # preserve every actual original outcome, including genuine model failures.
    rows = inspect_canonical_split(split, spec['expected_ids'])
    if rows is None:
        return None
    assert len(rows) == spec['expected']
    return rows


def validate_receipt(receipt):
    assert receipt['plan_sha256'] == (PLAN['supersedes_plan_sha256']
        if receipt['split'] == 'qwen3_30b_instruct2507_500' else STATE['plan_sha256'])
    for row in receipt['reviews'].values():
        for path, expected in row['source_hashes'].items():
            assert sha(path) == expected
    for path, expected in receipt['prepared_files_sha256'].items():
        assert sha(path) == expected
    for path, expected in receipt.get('input_adapters_sha256', {}).items():
        assert sha(path) == expected


def prepare(split, reviews):
    verify_sources()
    folder = REVISION / 'prepared' / split
    assert not folder.exists(), 'Inspect partial preparation before resuming: ' + str(folder)
    inputs = folder / 'review-input'
    inputs.mkdir(parents=True)
    input_adapters = {}
    for name, row in sorted(reviews.items()):
        trial = Path(row['trial'])
        target = inputs / trial.name
        if row.get('native_verifier_complete_without_harbor_summary'):
            # The official generator requires result.json only to identify a
            # task. This adapter is a task-generation input, never a Harbor
            # result or a model metric. The actual decision stays symlinked
            # to the original native verifier report.
            target.mkdir()
            (target / 'verifier').mkdir()
            report = trial / 'verifier/review_report.json'
            assert report.is_file() and not (trial / 'result.json').exists()
            write(target / 'result.json', {'task_name': name,
                '_task_generation_adapter_only': True,
                '_native_trial': str(trial),
                '_native_review_report_sha256': sha(report)})
            (target / 'config.json').symlink_to(trial / 'config.json')
            (target / 'verifier/review_report.json').symlink_to(report)
            for path in (target / 'result.json', target / 'config.json',
                         target / 'verifier/review_report.json'):
                input_adapters[str(path)] = sha(path)
        else:
            target.symlink_to(trial, target_is_directory=True)
    rejected = {name for name, row in reviews.items() if row['decision'] == 'request_changes'}
    claim = {'plan_sha256': STATE['plan_sha256'], 'split': split, 'reviews': reviews,
             'expected_rejected': sorted(rejected)}
    write(folder / 'preparation-claim.json', claim)
    script = Path(PLAN['official_repo']) / 'scripts/data_pipeline/generate_review_tasks.py'
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location('official_revision_task_generator', script)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    tasks = folder / 'tasks'
    # The old datasets client cannot resolve this parquet-only Hub repo offline.
    # Feed the exact, checksum-pinned Arrow cache produced by the official loader.
    # The official task builder, metadata preparation, prompts and grader stay real.
    import datasets
    arrow_path, = [path for path in PLAN['dataset_cache_sha256'] if path.endswith('.arrow')]
    frozen = datasets.Dataset.from_file(arrow_path)
    assert len(frozen) == 500 and set(frozen['instance_id']) == set(PLAN['splits']['glm5_500']['expected_ids'])
    original_loader = datasets.load_dataset

    def load_frozen_verified(name, *, split, cache_dir):
        assert name == 'princeton-nlp/SWE-bench_Verified' and split == 'test'
        assert Path(cache_dir).resolve() == Path(PLAN['official_repo']) / 'datasets'
        return frozen

    datasets.load_dataset = load_frozen_verified
    try:
        generator.run_revision_mode(SimpleNamespace(review_dir=str(inputs), revision_split=split,
            output_dir=str(tasks), clean=False))
    finally:
        datasets.load_dataset = original_loader
    generated = {p.name: p for p in tasks.iterdir() if p.is_dir()}
    assert set(generated) == {generator.sanitize_task_id(name) for name in rejected}
    url = 'git+https://github.com/SWE-rebench/SWE-bench-fork.git'
    pins = []
    for name in sorted(rejected):
        task = generated[generator.sanitize_task_id(name)]
        assert (task / 'environment/Dockerfile').is_file() and (task / 'instruction.md').is_file()
        config = json.loads((task / 'tests/config.json').read_text())
        assert config['instance_id'] == name
        f2p = config.get('FAIL_TO_PASS')
        if isinstance(f2p, str):
            f2p = json.loads(f2p)
        assert f2p, 'Missing F2P grading metadata'
        for path in (task / 'environment/data').glob('*.json'):
            data = json.loads(path.read_text())
            assert not ({'resolved', 'candidate_resolved', 'test_patch', 'FAIL_TO_PASS', 'PASS_TO_PASS'} & set(data))
        test = task / 'tests/test.sh'
        original = test.read_text()
        assert original.count(url) == 1 and (url + '@') not in original
        pinned = original.replace(url, url + '@' + PLAN['verifier_fork_commit'])
        assert pinned.replace(url + '@' + PLAN['verifier_fork_commit'], url) == original
        test.write_text(pinned)
        pins.append({'task': name, 'original_sha256': hashlib.sha256(original.encode()).hexdigest(),
                     'pinned_sha256': sha(test)})
    verify_sources()
    receipt = {**claim, 'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'prepared_tasks': len(rejected), 'generator_task_ids': sorted(generated),
        'frozen_metadata_arrow': arrow_path, 'frozen_metadata_arrow_sha256': sha(arrow_path),
        'verifier_dependency_revision_pins': pins,
        'prepared_files_sha256': {str(p): sha(p) for p in tasks.rglob('*') if p.is_file()},
        'input_adapters_sha256': input_adapters,
        'task_generation_adapter_count': len(input_adapters) // 3,
        'model_generation_started': False, 'included_in_model_metrics': False,
        'qualification': 'Official task generation using the same frozen Arrow metadata and a pinned verifier dependency git revision. '
                         'Native-only reviewer reports use clearly marked task-generation adapters with no finished_at or verifier_result; '
                         'these are excluded from model metrics. No revision sampled yet.'}
    validate_receipt(receipt)
    write(folder / 'receipt.json', receipt)
    return receipt


try:
    verify_sources()
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    os.environ['HF_HUB_OFFLINE'] = '1'
    STATE['phase'] = 'waiting_for_grader_preflight'
    save()
    while not preflight_ready():
        time.sleep(60)
        save()
    STATE['grader_preflight_passed'] = True
    STATE['phase'] = 'waiting_for_completed_review_splits'
    for split in PLAN['splits']:
        receipt_path = REVISION / 'prepared' / split / 'receipt.json'
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
            if split == 'qwen3_30b_instruct2507_500':
                assert sha(receipt_path) == PLAN['legacy_instruct_receipt_sha256']
            validate_receipt(receipt)
            STATE['splits'][split] = {'status': 'tasks_prepared', 'count': receipt['prepared_tasks'],
                                      'receipt': str(receipt_path), 'sha256': sha(receipt_path)}
    save()
    while len(STATE['splits']) < len(PLAN['splits']):
        for split, spec in PLAN['splits'].items():
            if split in STATE['splits']:
                continue
            reviews = inspect_split(split, spec)
            if reviews is None:
                continue
            STATE['phase'] = 'preparing_' + split
            save()
            receipt = prepare(split, reviews)
            receipt_path = REVISION / 'prepared' / split / 'receipt.json'
            STATE['splits'][split] = {'status': 'tasks_prepared', 'count': receipt['prepared_tasks'],
                                      'receipt': str(receipt_path), 'sha256': sha(receipt_path)}
        STATE['phase'] = 'waiting_for_completed_review_splits'
        save()
        if len(STATE['splits']) < len(PLAN['splits']):
            time.sleep(60)
    STATE['phase'] = 'all_revision_tasks_prepared'
    STATE['complete'] = True
    save()
except BaseException as error:
    STATE['phase'] = 'preparation_requires_review'
    STATE['error_type'] = type(error).__name__
    STATE['error_summary'] = str(error)[:500]
    save()
    raise
