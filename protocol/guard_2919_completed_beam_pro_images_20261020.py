#!/usr/bin/env python3
"""Guard CPU 2919 Docker disk with native-graded Beam Pro R1 handoff images."""

from pathlib import Path

import guard_2922_completed_muse_pro_images_20261020 as guard

guard.JOB_ID = '2919'
guard.NODE_NAME = 'ip-10-1-30-147'
guard.SOURCE = (Path('/fsx/home/zhiyuan/.private/beam_20261018/legacy_bench_20261018') /
                'remaining_pro/pro-results/beam_full_remaining603_handoff_20261020/'
                'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent/'
                'beam-pro-r1-handoff-unattempted/details')
guard.LOG = (Path('/fsx/home/zhiyuan/.private/beam_20261018/legacy_bench_20261018') /
             'remaining_pro/handoff_20261020/cpu-2919-image-guard.jsonl')
guard.TRIGGER = 60 * 2**30
guard.TARGET = 90 * 2**30


if __name__ == '__main__':
    guard.main()
