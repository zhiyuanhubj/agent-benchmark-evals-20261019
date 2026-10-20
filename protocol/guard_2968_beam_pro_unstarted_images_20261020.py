#!/usr/bin/env python3
"""Free CPU 2968 disk only from terminal Beam Pro continuation task images."""

import json
from pathlib import Path

import guard_2922_completed_muse_pro_images_20261020 as guard

BASE = Path('/fsx/home/zhiyuan')
RESULTS = BASE / '.private/beam_20261018/legacy_bench_20261018/remaining_pro/pro-results'
SLUG = 'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent'
SOURCES = [RESULTS / f'beam_full_remaining603_unstarted_{node}_20261020' / SLUG /
           f'beam-pro-r1-unstarted-{node}-20261020/details' for node in ('2733', '2887')]
TERMINAL = {'completed', 'run_error', 'eval_error', 'run_error_or_eval_error'}

guard.JOB_ID = '2968'
guard.NODE_NAME = 'ip-10-1-100-204'
guard.LOG = (BASE / '.private/beam_20261018/legacy_bench_20261018/remaining_pro/'
             'handoff_unstarted_20261020/image-guard.jsonl')
guard.TRIGGER = 100 * 2**30
guard.TARGET = 160 * 2**30


def candidates():
    terminal = {}
    for source in SOURCES:
        for path in source.glob('*/attempt-1/result.json'):
            result = json.loads(path.read_text())
            if result.get('status') not in TERMINAL:
                continue
            task = json.loads((path.parent.parent / 'task.json').read_text())['task_id']
            assert task not in terminal, 'Duplicate continuation task: ' + task
            terminal[task] = (path, guard.digest(path))
    images = guard.docker('image', 'ls', '--no-trunc', '--format', '{{json .}}')
    images.check_returncode()
    eligible = []
    for line in images.stdout.splitlines():
        image = json.loads(line)
        if image['Repository'] != 'jefzda/sweap-images':
            continue
        matches = [task for task in terminal if task.removeprefix('instance_') in image['Tag']]
        if len(matches) != 1:
            continue
        task = matches[0]
        path, result_sha = terminal[task]
        eligible.append((image['Repository'] + ':' + image['Tag'], image['ID'], task, path, result_sha))
    return eligible


guard.candidates = candidates

if __name__ == '__main__':
    guard.main()
