#!/usr/bin/env python3
"""Sample every physical GPU once per second on each allocated host."""
import argparse
import gzip
import json
import signal
import socket
import subprocess
import time
import os
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
running = True


def stop(*_):
    global running
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
fields = ['index', 'uuid', 'utilization.gpu', 'memory.used', 'memory.total', 'power.draw', 'clocks.sm']
with gzip.open(args.output / (socket.gethostname() + '-' + str(time.time_ns()) + '-' + str(os.getpid()) + '.jsonl.gz'), 'wt') as stream:
    while running:
        start = time.time()
        try:
            r = subprocess.run(['nvidia-smi', '--query-gpu=' + ','.join(fields),
                                '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=10)
            record = {'unix': start, 'host': socket.gethostname(), 'fields': fields,
                      'rows': [x.split(', ') for x in r.stdout.splitlines()],
                      'returncode': r.returncode, 'stderr': r.stderr[:200]}
        except subprocess.TimeoutExpired:
            record = {'unix':start,'host':socket.gethostname(),'fields':fields,'rows':[],
                      'returncode':124,'stderr':'nvidia-smi timed out; sampler continues'}
        stream.write(json.dumps(record) + '\n')
        stream.flush()
        time.sleep(max(0, 1 - (time.time() - start)))
