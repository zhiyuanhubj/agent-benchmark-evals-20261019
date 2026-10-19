"""Read-only accounting for supplied-image TB rounds, disjoint from legacy tags."""
from pathlib import Path
from collections import Counter
import datetime
import hashlib
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent
MUSE_BF16_CUTOVER = Path('/fsx/home/zhiyuan/.private/muse_bf16_20261018/manual_pair_2865_2869_20261019')

def read(path):
    return json.loads(path.read_text()) if path.exists() else None

def summarize(model, round_number):
    work = ROOT / ('beam' if model == 'beam_bf16' else model)
    pattern = f'r{round_number}-shard[123].json' if model == 'muse_nvfp4' else f'r{round_number}*.json'
    configs = sorted((work / 'configs').glob(pattern))
    expected = {}
    for path in configs:
        config = read(path)
        assert config['retry']['max_retries'] == 0
        for task in config['tasks']:
            name = Path(task['path']).name
            assert name not in expected
            expected[name] = config['job_name']
    assert len(expected) == 89, (model, round_number, len(expected))
    records = {}
    cutover = read(MUSE_BF16_CUTOVER / 'cutover-intent.json') if model == 'muse_nvfp4' else None
    interrupted = {row['trial'] for row in cutover.get('unfinished_exact_tb_trials_before_cutover', [])} if cutover else set()
    excluded_interrupted = []
    raw_response_files = 0
    active_trial_dirs = 0
    for job in sorted(set(expected.values())):
        root = ROOT / 'results' / model / job
        if not root.exists():
            continue
        for trial in root.iterdir():
            if not trial.is_dir():
                continue
            active_trial_dirs += 1
            raw_response_files += len(list((trial / 'agent/raw_responses').glob('*.json')))
            path = trial / 'result.json'
            if not path.exists():
                continue
            data = read(path)
            if not data.get('finished_at'):
                continue
            if str(trial) in interrupted:
                excluded_interrupted.append(str(trial))
                continue
            name = Path(data['config']['task']['path']).name
            assert expected.get(name) == job, (model, job, name)
            assert name not in records, (model, round_number, 'duplicate', name)
            reward = ((data.get('verifier_result') or {}).get('rewards') or {}).get('reward')
            records[name] = dict(reward=reward, exception=(data.get('exception_info') or {}).get('exception_type'))
    graded = sum(row['reward'] in [0, 1] for row in records.values())
    successes = sum(row['reward'] == 1 for row in records.values())
    return dict(expected=89, terminal=len(records), graded=graded, success=successes,
        active_trial_dirs=active_trial_dirs, archived_actual_model_responses=raw_response_files,
        ungraded=len(records)-graded, exceptions=dict(Counter(row['exception'] for row in records.values() if row['exception'])),
        excluded_user_reassignment_trials=excluded_interrupted,
        complete=graded==89, accuracy=successes/89 if graded==89 else None,
        legacy_cached_tag_scores_included=False)

def main():
    plan = read(ROOT / 'image-identity-plan.json')
    assert plan['image_count'] == 89 and len(plan['images']) == 89
    models = {}
    units = dict(beam_bf16='beam-tb-supplied-images-three-rounds-20261019',
                 opus47='opus47-tb-supplied-images-three-rounds-20261019',
                 muse_nvfp4='muse-nvfp4-tb-supplied-images-three-rounds-recovered-20261019')
    for name, allocation in [('beam_bf16', 2919), ('opus47', 2919), ('muse_nvfp4', 2922)]:
        ready = read(ROOT / f'allocation-{allocation}/images-ready.json')
        rounds = {str(n): summarize(name, n) for n in [1, 2, 3]}
        unit_rows = subprocess.check_output(['systemctl', '--user', 'show', units[name], '-p', 'MainPID', '-p', 'ActiveState', '-p', 'Result'], text=True).splitlines()
        unit = {key: value for key, value in (line.split('=', 1) for line in unit_rows)}
        models[name] = dict(rounds=rounds, unit=unit, exact_supplied_images_ready=bool(ready and ready['count']==89 and ready['all_archive_identities_verified']),
                            cpu_allocation=allocation, all_three_complete=all(x['complete'] for x in rounds.values()),
                            three_round_mean=sum(x['accuracy'] for x in rounds.values())/3 if all(x['complete'] for x in rounds.values()) else None,
                            user_authorized_bf16_reassignment=bool(name == 'muse_nvfp4' and (MUSE_BF16_CUTOVER / 'cutover-intent.json').exists()))
    receipt = dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), source_image_plan=str(ROOT / 'image-identity-plan.json'),
        source_image_plan_sha256=hashlib.sha256((ROOT / 'image-identity-plan.json').read_bytes()).hexdigest(),
        models=models, qualification='Independent user-supplied prebuilt-image profile. Cached-tag legacy outcomes are retained separately; never merged into this mean. Partial success counts are not final accuracy.')
    state = ROOT / 'status-current.json'
    temp = state.with_name(state.name + '.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(receipt, indent=2) + '\n')
    temp.replace(state)
    print(json.dumps({model: {'images_ready': value['exact_supplied_images_ready'], 'rounds': {n:{k:v[k] for k in ['terminal','graded','success','archived_actual_model_responses']} for n,v in value['rounds'].items()}} for model,value in models.items()}))
    assert all(x['all_three_complete'] or x['unit']['ActiveState'] == 'active' or x['user_authorized_bf16_reassignment'] for x in models.values()), 'Unfinished supplied-image profile has no active controller'

if __name__ == '__main__':
    main()
