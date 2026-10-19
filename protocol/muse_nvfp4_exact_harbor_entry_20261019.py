from pathlib import Path
import asyncio,json,re,sys,time
E=Path(__file__).resolve().parent
sys.path.insert(0,'/fsx/home/zhiyuan/bench/tb21_v1_four_models_20261012')
import os, hashlib, fcntl
config_path = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None
extra_owner = None
if config_path and re.fullmatch(r'r[23]-completion-2866-b\d{2}\.json', config_path.name):
    from route_future_rounds import original_entry_claim
    original_entry_claim(config_path)
if config_path and re.fullmatch(r'r[123]-completion-2866-b\d{2}\.json', config_path.name):
    state = E / 'state'
    extra_marker = state / (config_path.stem + '-extra-owner.json')
    if extra_marker.exists():
        extra_owner = json.loads(extra_marker.read_text())
        assert extra_owner['config_sha256'] == hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert extra_owner['lane'] in (2, 3, 4, 5, 6, 7, 8, 9)
        if os.environ.get('MUSE_TB_EXTRA_LANE') != str(extra_owner['lane']):
            exit_file = state / (config_path.stem + '-extra-exit.json')
            owner_lock_path = state / f'extra-lane{extra_owner["lane"]}-2866-controller.lock'
            def owner_alive():
                with owner_lock_path.open('a') as owner_lock:
                    try:
                        fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return True
                    return False
            if os.environ.get('MUSE_TB_PARALLEL_OWNER') == '1':
                assert exit_file.exists() or owner_alive(), 'Extra lane stopped; preserve outputs and audit'
                if exit_file.exists():
                    assert json.loads(exit_file.read_text())['returncode'] == 0
                print(f'Extra lane owns {config_path.stem}; primary parallel lane skips duplicate draw', flush=True)
                raise SystemExit(0)
            assert os.environ.get('SLURM_JOB_ID') == '2922'
            while not exit_file.exists():
                assert owner_alive(), 'Extra lane stopped; preserve outputs and audit'
                time.sleep(15)
            status = json.loads(exit_file.read_text())
            assert status['returncode'] == 0 and status['config_sha256'] == extra_owner['config_sha256']
            config = json.loads(config_path.read_text())
            expected = {Path(task['path']).name for task in config['tasks']}
            found = set()
            for result_path in (Path(config['jobs_dir']) / config['job_name']).glob('*/result.json'):
                result = json.loads(result_path.read_text())
                if result.get('finished_at'):
                    task = Path(result['config']['task']['path']).name
                    assert task in expected and task not in found
                    found.add(task)
            assert found == expected, f'Extra lane missing terminal tasks: {expected - found}'
            print(f'Extra lane completed {config["job_name"]}: {len(found)} terminal tasks', flush=True)
            raise SystemExit(0)
if config_path and config_path.name.startswith('r1-completion-2866-b') and os.environ.get('MUSE_TB_PARALLEL_OWNER') != '1' and extra_owner is None:
    state = E / 'state'
    marker = state / (config_path.stem + '-parallel-owner.json')
    if marker.exists():
        assert os.environ.get('SLURM_JOB_ID') == '2922'
        owner = json.loads(marker.read_text())
        assert owner['config_sha256'] == hashlib.sha256(config_path.read_bytes()).hexdigest()
        exit_file = state / (config_path.stem + '-parallel-exit.json')
        while not exit_file.exists():
            with (state / 'parallel-2866-controller.lock').open('a') as owner_lock:
                try:
                    fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass
                else:
                    raise AssertionError('Parallel owner stopped; preserve outputs and audit')
            time.sleep(15)
        status = json.loads(exit_file.read_text())
        assert status['returncode'] == 0 and status['config_sha256'] == owner['config_sha256']
        config = json.loads(config_path.read_text())
        expected = {Path(task['path']).name for task in config['tasks']}
        found = set()
        for result_path in (Path(config['jobs_dir']) / config['job_name']).glob('*/result.json'):
            result = json.loads(result_path.read_text())
            if result.get('finished_at'):
                task = Path(result['config']['task']['path']).name
                assert task in expected and task not in found
                found.add(task)
        assert found == expected, f'Parallel owner missing terminal tasks: {expected - found}'
        print(f'Parallel owner completed {config["job_name"]}: {len(found)} terminal tasks', flush=True)
        raise SystemExit(0)
if len(sys.argv) == 2 and Path(sys.argv[1]).resolve() in {E/'configs/tb-r2.json', E/'configs/tb-r3.json'}:
    config_path = Path(sys.argv[1]).resolve()
    if os.environ.get('SLURM_JOB_ID') == '2675':
        (E/'state/tb23-original-worker-delegated.json').write_text(json.dumps({'config': config_path.name, 'destination_job': 2733}))
        print('PLANNED TB rounds 2/3 delegation to allocation 2733', flush=True)
        raise SystemExit(75)
    assert os.environ.get('SLURM_JOB_ID') == '2733' and os.environ.get('MUSE_TB23_HANDOFF') == '1'
    plan = json.loads((E/'state/future-tb-endpoint-handoff.json').read_text())
    expected = plan['configs'][config_path.name]['effective_sha256']
    assert hashlib.sha256(config_path.read_bytes()).hexdigest() == expected
    claim = json.loads((E/'state'/f'{config_path.stem}-2733-claim.json').read_text())
    assert claim['config_sha256'] == expected and claim['job'] == 2733
    os.environ['MIX_SERVER_IP'] = plan['destination_ip']
if config_path and config_path.name == 'r1-completion-2866-b05.json' and os.environ.get('MUSE_TB_EXTRA_LANE') == '3':
    from early_b05 import coordinate
    if not coordinate(config_path):
        print('Early b05 owner completed; sequential lane 3 skips duplicate draw', flush=True)
        raise SystemExit(0)
if config_path and config_path.name in ('r1-completion-2866-b03.json', 'r1-completion-2866-b05.json') and os.environ.get('MUSE_TB_EXTRA_LANE'):
    from route_2812 import route_for_extra_lane
    config_path = route_for_extra_lane(config_path, os.environ['MUSE_TB_EXTRA_LANE'])
    sys.argv[1] = str(config_path)
from harbor.job import Job
from harbor.models.job.config import JobConfig
async def main():
 c=JobConfig.model_validate(json.loads(Path(sys.argv[1]).read_text()));job=await Job.create(c);r=await job.run()
 (E/'state'/f'{c.job_name}-done.json').write_text(r.model_dump_json(indent=2))
asyncio.run(main())
if config_path and os.environ.get('MUSE_TB_B05_EARLY_OWNER') == '1':
    from early_b05 import coverage
    expected, found = coverage(json.loads(config_path.read_text()))
    assert found == expected, f'Early b05 missing terminal tasks: {expected - found}'
