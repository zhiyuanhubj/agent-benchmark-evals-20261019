"""Continue exact-image Muse NVFP4 TB without replaying graded task draws."""
import fcntl
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / 'muse_nvfp4'
STATE = WORK / 'state'
RESULTS = ROOT / 'results/muse_nvfp4'
PYTHON = '/fsx/home/zhiyuan/AgentCompass/.venv/bin/python'
ENDPOINT = 'http://10.1.95.27:31320/v1'
JOB = '2922'


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n')


def scored_original(round_number):
    scored = {}
    for shard in (1, 2, 3):
        job = json.loads((WORK / 'configs' / f'r{round_number}-shard{shard}.json').read_text())['job_name']
        for result in (RESULTS / job).glob('*/result.json'):
            data = json.loads(result.read_text())
            if not data.get('finished_at'):
                continue
            task = Path(data['config']['task']['path']).name
            reward = ((data.get('verifier_result') or {}).get('rewards') or {}).get('reward')
            if reward in (0, 1):
                assert task not in scored
                scored[task] = {'result': str(result), 'sha256': hashlib.sha256(result.read_bytes()).hexdigest(), 'reward': reward}
    return scored


def make_plan():
    assert os.environ.get('SLURM_JOB_ID') == JOB
    assert json.loads((ROOT / 'allocation-2922/official-policy-preflight-ready.json').read_text())['no_extra_offline_firewall']
    model = subprocess.run(['curl', '-fsS', '--max-time', '10', ENDPOINT + '/models'], capture_output=True, text=True, check=True)
    assert any(row.get('id') == 'muse-spark-open-nvfp4' for row in json.loads(model.stdout).get('data', []))
    cutover = json.loads(Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/manual_pair_2865_2869_20261019/cutover-intent.json').read_text())
    interrupted = {}
    for row in cutover['unfinished_exact_tb_trials_before_cutover']:
        trial = Path(row['trial'])
        source = json.loads((trial / 'config.json').read_text())
        task = Path(source['task']['path']).name
        assert task not in interrupted and row['raw_model_responses'] > 0
        interrupted[task] = row
    assert len(interrupted) == 8
    configs = []
    previous_scored = {}
    for round_number in (1, 2, 3):
        original = {}
        source_hashes = {}
        for shard in (1, 2, 3):
            path = WORK / 'configs' / f'r{round_number}-shard{shard}.json'
            source_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            data = json.loads(path.read_text())
            for task in data['tasks']:
                name = Path(task['path']).name
                assert name not in original
                original[name] = task
        assert len(original) == 89
        scored = scored_original(round_number)
        previous_scored[str(round_number)] = scored
        if round_number == 1:
            assert len(scored) == 11 and not (set(scored) & set(interrupted))
            assert len(original.keys() - scored.keys()) == 78
        else:
            assert not scored
        pending = [original[name] for name in sorted(original.keys() - scored.keys())]
        for idx in range(0, len(pending), 10):
            chunk = pending[idx:idx + 10]
            template = json.loads((WORK / 'configs' / f'r{round_number}-shard2.json').read_text())
            assert template['retry']['max_retries'] == 0 and template['n_attempts'] == 1
            assert template['agents'][0]['kwargs']['api_base'] == ENDPOINT
            template['job_name'] = f'muse-nvfp4-tb-v1-exact-r{round_number}-completion-2866-b{idx // 10:02d}'
            template['tasks'] = chunk
            template['n_concurrent_trials'] = 2
            path = WORK / 'configs' / f'r{round_number}-completion-2866-b{idx // 10:02d}.json'
            assert not path.exists(), 'Previous completion config exists; audit before relaunch'
            save(path, template)
            configs.append({'round': round_number, 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'job_name': template['job_name'], 'tasks': [Path(t['path']).name for t in chunk]})
    plan = {'utc': time.time(), 'profile': 'user-supplied exact prebuilt TB2.1 images', 'model': 'Muse NVFP4', 'endpoint': ENDPOINT, 'cpu_allocation': 2922, 'model_allocation': 2866, 'existing_scored_results': previous_scored, 'user_cutover_interrupted_ungraded_trials': interrupted, 'configurations': configs, 'qualification': 'No graded task replay. Eight ungraded tasks interrupted by user BF16 node cutover receive explicitly identified infrastructure replacement attempts; their original partial responses remain archived. Remaining 70 r1 tasks were never sampled. Rounds 2 and 3 use original tasks/images and generation settings. No best-of selection.'}
    save(STATE / 'completion-2866-plan.json', plan)
    return plan


def main():
    lock = (STATE / 'completion-2866-controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    plan = make_plan()
    os.environ.update(OPENAI_API_KEY='EMPTY', HF_HOME='/fsx/home/zhiyuan/bench/hf_home', UV_CACHE_DIR='/fsx/home/zhiyuan/bench/uv_cache')
    for item in plan['configurations']:
        claim = STATE / (item['job_name'] + '-launch.json')
        assert not claim.exists(), 'Previous batch claim exists; inspect before retry'
        save(claim, {'utc': time.time(), **item})
        log = STATE / (item['job_name'] + '.log')
        with log.open('a') as stream:
            result = subprocess.run([PYTHON, str(WORK / 'harbor_entry.py'), item['path']], stdout=stream, stderr=subprocess.STDOUT)
        save(STATE / (item['job_name'] + '-exit.json'), {'utc': time.time(), 'returncode': result.returncode})
        assert result.returncode == 0, 'Batch stopped; preserve outputs and audit before continuation'
    save(STATE / 'completion-2866-finished.json', {'utc': time.time(), 'rounds': 3, 'fourth_round_scheduled': False})


if __name__ == '__main__':
    main()
