#!/usr/bin/env python3
"""Guard CPU 2968 disk using only native-graded Beam Pro correction image tags."""

from pathlib import Path

import guard_2922_completed_muse_pro_images_20261020 as guard

guard.JOB_ID = '2968'
guard.NODE_NAME = 'ip-10-1-100-204'
guard.SOURCE = (Path('/fsx/home/zhiyuan/.private/beam_20261018/legacy_bench_20261018') /
                'disk_correction_results/beam_pro_r1_pre_model_disk_correction_2968_20261020/'
                'Beam-1.0-501B-A23B_swebench_pro_verified_mini_swe_agent/'
                'beam-pro-r1-pre-model-disk-2968-20261020/details')
guard.LOG = (Path('/fsx/home/zhiyuan/.private/beam_20261018/legacy_bench_20261018') /
             'remaining_pro/disk_correction_2968_20261020/image-guard.jsonl')
guard.TRIGGER = 80 * 2**30
guard.TARGET = 160 * 2**30


if __name__ == '__main__':
    guard.main()
