"""Read the ordered GitHub Release chain used for native I/O archives."""

import json
import subprocess

REPO = 'zhiyuanhubj/agent-benchmark-evals-20261019'
BASE_TAG = '2026-10-19-snapshot'
MAX_ASSETS_PER_RELEASE = 1000


def tag_for_part(number):
    assert number >= 1
    return BASE_TAG if number == 1 else f'{BASE_TAG}-part{number}'


def release_tags():
    listed = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{REPO}/releases?per_page=100'], text=True))
    assert len(listed) < 100, 'Release list may be truncated'
    names = {row['tag_name'] for row in listed}
    assert BASE_TAG in names, 'Original archive release is missing'
    numbers = {1}
    for tag in names:
        if tag.startswith(BASE_TAG + '-part'):
            suffix = tag.removeprefix(BASE_TAG + '-part')
            assert suffix.isdecimal() and int(suffix) >= 2, f'Invalid archive release tag: {tag}'
            numbers.add(int(suffix))
    assert numbers == set(range(1, max(numbers) + 1)), 'Archive Release chain has a missing part'
    return [tag_for_part(number) for number in sorted(numbers)]


def release_assets():
    releases = []
    for tag in release_tags():
        payload = json.loads(subprocess.check_output(
            ['gh', 'api', f'repos/{REPO}/releases/tags/{tag}'], text=True))
        assert len(payload['assets']) <= MAX_ASSETS_PER_RELEASE
        releases.append((tag, payload['assets']))
    return releases
