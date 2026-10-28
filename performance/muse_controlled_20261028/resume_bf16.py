#!/usr/bin/env python3
"""Preserve allocation, repair rank 1, then resume the same experiment."""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    a = p.parse_args()
    root = a.state / 'bf16'
    pause = json.loads((root / 'paused-controller.json').read_text())
    status = {'job': 3121, 'precision': 'bf16', 'hosts': ['ip-10-1-112-220', 'ip-10-1-114-210'],
              'phase': 'resuming_rank1_download_on_nvme_after_cache_cleanup', 'utc_unix': time.time(),
              'note': 'Original controller paused to retain allocation; rank-0 download continues.'}
    (root / 'status.json').write_text(json.dumps(status, indent=2) + '\n')
    prefix = ['srun', '--jobid=3121', '--overlap', '--exact', '--gres=none', '-N1', '-n1', '-c8', '--immediate=30']
    subprocess.run([*prefix, '--nodelist=ip-10-1-114-210', sys.executable,
                    str(a.state / 'repair_bf16_download.py'), '--state', str(a.state)], check=True)
    while not (root / 'rank0/weights.json').exists():
        time.sleep(10)
    subprocess.run([*prefix, '--nodelist=ip-10-1-112-220', sys.executable,
                    str(a.state / 'orchestrate.py'), '--state', str(a.state),
                    '--precision', 'bf16', '--reuse-prepared'], check=True)
    subprocess.run([*prefix, '--nodelist=ip-10-1-112-220', 'bash', '-c',
                    f'kill -CONT {int(pause["pid"])}; kill -TERM {int(pause["pid"])}'], check=False)


if __name__ == '__main__':
    main()
