"""Prebuild unchanged official revision images; one original-generator attempt per rejection.

Some prepared source tasks pin a frozen Docker image; others retain the original
Dockerfile setting. Replace or add only the local image pin as appropriate,
while preserving the earlier queue failures and original source tasks.
"""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib

PLAN = Path(sys.argv[1])
AUDIT_ONLY = '--audit-resume' in sys.argv[2:]
spec = json.loads(PLAN.read_text())
ROOT = Path(spec['queue_root'])
ROOT.mkdir(exist_ok=True)
assert socket.gethostname() == spec['sandbox_hostname']
lock = (ROOT / 'queue.lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
BUILD_LIMIT = threading.Semaphore(4)
HPY = '/fsx/home/zhiyuan/.local/share/uv/tools/harbor/bin/python'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(dict(utc=time.time(), **data), indent=2) + '\n')
    temp.replace(path)

def tree(path):
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}

def _prepared_task(split, task):
    source = Path(spec['splits'][split]['source_tasks']) / task
    original = tree(source)
    fingerprint = hashlib.sha256(json.dumps(original, sort_keys=True).encode()).hexdigest()
    tag = 'zhiyuan-review-frozen:' + fingerprint[:40]
    receipt = ROOT / 'images' / (split + '--' + task + '.json')
    log_path = receipt.with_suffix('.log')
    receipt.parent.mkdir(exist_ok=True)
    previous = json.loads(receipt.read_text()) if receipt.exists() else None
    info = subprocess.run(['docker', 'image', 'inspect', tag], capture_output=True, text=True)
    if previous and previous.get('phase') == 'image_ready' and info.returncode == 0:
        assert json.loads(info.stdout)[0]['Id'] == previous['image_id']
        assert original == previous['original_file_sha256']
    else:
        attempt = 0
        while True:
            attempt += 1
            disk = os.statvfs('/opt/dlami/nvme')
            assert disk.f_bavail * disk.f_frsize > 40 * 2**30, 'Preserving sandbox disk headroom'
            with BUILD_LIMIT:
                result = subprocess.run(['docker', 'build', '--pull=false', '--progress=plain',
                    '-t', tag, str(source / 'environment')], capture_output=True, text=True, timeout=900)
            text = result.stdout + result.stderr
            with log_path.open('a') as log:
                log.write('\nBUILD ATTEMPT ' + str(attempt) + '\n' + text)
            if result.returncode == 0:
                break
            quota = 'registry-1.docker.io' in text and ('429' in text or 'toomanyrequests' in text.lower())
            save(receipt, dict(phase='registry_quota_wait_before_model' if quota else 'image_build_failed',
                task=task, source=str(source), original_file_sha256=original,
                build_attempt=attempt, model_attempt_started=False, build_log=str(log_path)))
            assert quota, 'Image preparation failed; inspect preserved build log before continuing'
            time.sleep(180)
        info = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag], text=True))[0]
        previous = dict(phase='image_ready', task=task, source=str(source),
            original_file_sha256=original, image_tag=tag, image_id=info['Id'],
            build_log=str(log_path), model_attempt_started=False)
        save(receipt, previous)
    target = ROOT / 'tasks' / split / task
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    config = target / 'task.toml'
    source_config = tomllib.loads((source / 'task.toml').read_text())
    old_tag = source_config['environment'].get('docker_image')
    assert old_tag is None or old_tag.startswith(('zhiyuan-review-frozen:',
                                                  'zhiyuan-review-parallel-frozen:'))
    text = config.read_text()
    existing_tag = tomllib.loads(text)['environment'].get('docker_image')
    assert existing_tag in (old_tag, tag), (task, existing_tag, old_tag, tag)
    if existing_tag == old_tag:
        if old_tag is None:
            assert text.count('[environment]') == 1
            config.write_text(text.replace('[environment]',
                '[environment]\ndocker_image = ' + json.dumps(tag), 1))
        else:
            old_line = 'docker_image = ' + json.dumps(old_tag)
            assert text.count(old_line) == 1
            config.write_text(text.replace(old_line, 'docker_image = ' + json.dumps(tag), 1))
    observed = tree(target)
    actual = tomllib.loads((target / 'task.toml').read_text())
    expected = tomllib.loads((source / 'task.toml').read_text())
    assert actual['environment'].pop('docker_image') == tag
    assert expected['environment'].pop('docker_image', None) == old_tag
    assert actual == expected
    assert {k:v for k,v in observed.items() if k != 'task.toml'} == {k:v for k,v in original.items() if k != 'task.toml'}
    save(ROOT / 'task-receipts' / (split + '--' + task + '.json'),
         dict(source=str(source), original_file_sha256=original, task=str(target),
              prepared_file_sha256=observed, image_tag=tag, image_id=previous['image_id'],
              only_change='Add or replace only the image pin with the successfully rebuilt exact official Dockerfile image'))
    return target

def prepared_task(split, task):
    source = Path(spec['splits'][split]['source_tasks']) / task
    key = hashlib.sha256(str(source.resolve()).encode()).hexdigest()
    directory = Path('/opt/dlami/nvme/zhiyuan-review-image-locks-20261018')
    directory.mkdir(exist_ok=True)
    with (directory / key).open('a') as image_lock:
        fcntl.flock(image_lock, fcntl.LOCK_EX)
        return _prepared_task(split, task)

def prepare_batch(split, batch):
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(lambda task: prepared_task(split, task), batch))

def wait_for_gate():
    for value in spec['required_gate_files']:
        path = Path(value)
        while not path.exists():
            time.sleep(15)
    assert subprocess.check_output(['squeue','-h','-j',str(spec['model_allocation']),'-o','%T'],text=True).strip() == 'RUNNING'

def completed_batch(split, index, batch):
    config_path = ROOT / 'configs' / (split + '-' + str(index) + '.json')
    claim = ROOT / 'claims' / (split + '-' + str(index) + '.json')
    exit_path = ROOT / 'exits' / (split + '-' + str(index) + '.json')
    if not any(path.exists() for path in (config_path, claim, exit_path)):
        return False
    assert all(path.exists() for path in (config_path, claim, exit_path)), \
        'Partial prior batch requires manual review; never replay claimed tasks'
    recorded = json.loads(claim.read_text())
    config = json.loads(config_path.read_text())['config']
    assert recorded['tasks'] == batch
    assert recorded['config_sha256'] == sha(config_path)
    assert recorded['model_id'] == spec['model_id']
    assert config['job_name'] == spec['job_prefix'] + '-' + split + '-batch' + str(index)
    assert [Path(row['path']).name for row in config['tasks']] == batch
    assert json.loads(exit_path.read_text())['returncode'] == 0
    results = list((Path(config['jobs_dir']) / config['job_name']).glob('*/result.json'))
    assert len(results) == len(batch), 'Finished batch lacks a native result for every task'
    completed = [json.loads(path.read_text()) for path in results]
    assert all(row.get('finished_at') for row in completed)
    recorded_tasks = [Path(row['config']['task']['path']).name for row in completed]
    assert sorted(recorded_tasks) == sorted(batch)
    return True

def split_queue(split):
    source_config = Path(spec['splits'][split]['source_config'])
    assert sha(source_config) == spec['splits'][split]['source_config_sha256']
    base = json.loads(source_config.read_text())
    tasks = spec['splits'][split]['tasks']
    assert len(tasks) == len(set(tasks))
    batches = [tasks[i:i+16] for i in range(0, len(tasks), 16)]
    start = 0
    while start < len(batches) and completed_batch(split, start, batches[start]):
        start += 1
    for index in range(start + 1, len(batches)):
        assert not any((ROOT / folder / (split + '-' + str(index) + '.json')).exists()
                       for folder in ('configs', 'claims', 'exits')), \
            'Noncontiguous prior batch requires manual review'
    if AUDIT_ONLY:
        return dict(split=split, completed_batches=start, total_batches=len(batches),
                    remaining_tasks=len(tasks) - sum(len(batch) for batch in batches[:start]))
    old_exit = ROOT / 'queue-exit.json'
    old_exit_snapshot = (ROOT / ('queue-exit-pre-resume-' + sha(old_exit)[:16] + '.json')
                         if old_exit.exists() else None)
    if old_exit.exists():
        if old_exit_snapshot.exists():
            assert sha(old_exit_snapshot) == sha(old_exit), 'Earlier queue exit changed after preservation'
        else:
            shutil.copyfile(old_exit, old_exit_snapshot)
        assert sha(old_exit_snapshot) == sha(old_exit)
    save(ROOT / 'resume-audit.json', dict(split=split, completed_batches=start,
        completed_task_count=sum(len(batch) for batch in batches[:start]),
        remaining_task_count=len(tasks) - sum(len(batch) for batch in batches[:start]),
        prior_queue_exit_sha256=sha(old_exit_snapshot) if old_exit_snapshot else None,
        prior_queue_exit_snapshot=str(old_exit_snapshot) if old_exit_snapshot else None,
        policy='Verified exit-zero batches and their exact native task results are skipped; only never-claimed batches run'))
    with ThreadPoolExecutor(1) as preparation:
        pending = preparation.submit(prepare_batch, split, batches[start]) if start < len(batches) else None
        for index in range(start, len(batches)):
            batch = batches[index]
            ready = pending.result()
            pending = preparation.submit(prepare_batch, split, batches[index+1]) if index+1 < len(batches) else None
            wait_for_gate()
            config = json.loads(json.dumps(base))
            job = config['config']
            job['job_name'] = spec['job_prefix'] + '-' + split + '-batch' + str(index)
            job['jobs_dir'] = str(ROOT / 'results' / split)
            job.pop('datasets', None)
            job['tasks'] = [{'path': str(path)} for path in ready]
            job['n_concurrent_trials'] = 4
            agent = job['agents'][0]
            agent['model_name'] = 'hosted_vllm/' + spec['model_id']
            agent['env']['LLM_BASE_URL'] = spec['api_base']
            config_path = ROOT / 'configs' / (split + '-' + str(index) + '.json')
            config_path.parent.mkdir(exist_ok=True)
            assert not config_path.exists(), 'Existing batch requires reconciliation; model attempts cannot restart automatically'
            config_path.write_text(json.dumps(config, indent=2) + '\n')
            claim = ROOT / 'claims' / (split + '-' + str(index) + '.json')
            assert not claim.exists()
            command = [HPY, str(Path(spec['harness_root']) / 'swe_entry.py'), str(config_path)]
            save(claim, dict(tasks=batch, command=command, config_sha256=sha(config_path),
                model_id=spec['model_id'], model_allocation=spec['model_allocation'],
                sandbox_allocation=spec['sandbox_allocation'], model_attempt_started=True))
            env = dict(os.environ)
            for inherited in ['LITELLM_EXTRA_BODY', 'LLM_TEMPERATURE']:
                env.pop(inherited, None)
            env.update(OPENAI_API_KEY='dummy-key', LLM_API_KEY='dummy-key', LLM_BASE_URL=spec['api_base'],
                MIX_SERVER_IP=spec['model_host'], OPENHANDS_LLM_NATIVE_TOOL_CALLING='true', LLM_LOG_COMPLETIONS='1',
                PYTHONPATH=spec['harness_root'] + ':/fsx/home/zhiyuan/bench/strict_four_models_20261008',
                HF_HOME='/fsx/home/zhiyuan/bench/hf_home', UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
            save(ROOT / 'state' / (split + '.json'), dict(phase='running', batch=index, tasks=batch))
            with (ROOT / 'state' / (split + '-batch' + str(index) + '.log')).open('a') as log:
                result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            save(ROOT / 'exits' / (split + '-' + str(index) + '.json'), dict(returncode=result.returncode))
            assert result.returncode == 0, 'Model batch stopped; original attempts preserved for inspection'
    save(ROOT / 'state' / (split + '.json'), dict(phase='scheduled_attempts_finished', expected=len(tasks)))

with ThreadPoolExecutor(3) as pool:
    futures = {split: pool.submit(split_queue, split) for split in spec['splits']}
    errors = {}
    for split, future in futures.items():
        try:
            result = future.result()
            if AUDIT_ONLY:
                print(json.dumps(result), flush=True)
        except Exception as error:
            errors[split] = repr(error)
            if not AUDIT_ONLY:
                save(ROOT / 'state' / (split + '.json'), dict(phase='stopped_requires_review', error=repr(error)))
if not AUDIT_ONLY:
    save(ROOT / 'queue-exit.json', dict(errors=errors, scheduled_attempts_finished=not errors))
assert not errors, errors
