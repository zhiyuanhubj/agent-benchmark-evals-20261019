"""Pooled latency quantiles and GPU/KV telemetry must match native records."""
import gzip
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bench import summarize


class DetailedReportTest(unittest.TestCase):
    def test_pools_requests_instead_of_averaging_repeat_percentiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = []
            for repeat in range(3):
                d = root / 'nvfp4/cache-off-off/synthetic-8192' / f'c001-r{repeat}'
                d.mkdir(parents=True)
                rows = []
                for i in range(2):
                    e2e = 100 if repeat == 2 and i == 1 else 2
                    rows.append({'started': 11 + i, 'finished': 11 + i + e2e, 'valid': True,
                                 'meta': {'completion_tokens': 1024, 'prompt_tokens': 8192, 'cached_tokens': 0},
                                 'ttft_s': .5, 'tpot_s': .01, 'e2e_s': e2e,
                                 'decode_tokens_per_second': 100.})
                j = summarize(rows, [(12.5, 1024), (13.5, 1024)], 10, 20, 8)
                begin = 100 + repeat * 20
                j.update(measurement_start_unix=begin, measurement_end_unix=begin + 10,
                         precision='nvfp4', gpus=8, concurrency=1, repeat=repeat,
                         scenario={'workload':'synthetic','input_tokens':8192,'cache':False,'speculative':'off'},
                         valid_curve_point=True, cache_hit_rate_tokens=0)
                (d/'summary.json').write_text(json.dumps(j))
                with gzip.open(d/'requests.jsonl.gz','wt') as f:
                    for r in rows:f.write(json.dumps(r)+'\n')
                with gzip.open(d/'backend.jsonl.gz','wt') as f:
                    f.write(json.dumps({'utc_unix':begin+1,'/metrics':{'http':200,'body':'sglang:token_usage{model="muse"} 0.25\nsglang:num_running_reqs 1.0\n'}})+'\n')
                for second in range(10):
                    frames.append({'unix':begin+second+.1,'host':'fixture','fields':['uuid','utilization.gpu','memory.used'],
                                   'rows':[[f'GPU-{i}',str(10*(i+1)),'100000'] for i in range(8)]})
            gpu = root/'nvfp4/gpu';gpu.mkdir()
            with gzip.open(gpu/'fixture.jsonl.gz','wt') as f:
                for r in frames:f.write(json.dumps(r)+'\n')
            bad=root/'bf16/gpu/failed-startup.jsonl.gz';bad.parent.mkdir(parents=True)
            bad.write_bytes(b'corrupt preparation-only trace')
            subprocess.run([sys.executable,str(Path(__file__).with_name('report.py')),'--state',str(root)],check=True)
            import csv
            with (root/'report/detailed_points.csv').open() as f:points=list(csv.DictReader(f))
            self.assertEqual(len(points),1)
            self.assertAlmostEqual(float(points[0]['e2e_s_p95']),75.5)
            self.assertAlmostEqual(float(points[0]['tokens_s_gpu']),6144/30/8)
            self.assertEqual(points[0]['complete'],'True')
            with (root/'report/detailed_rounds.csv').open() as f:rounds=list(csv.DictReader(f))
            self.assertEqual(float(rounds[0]['gpu_utilization.gpu_mean']),45.)
            self.assertEqual(float(rounds[0]['sglang:token_usage_p50']),.25)
            acceptance=json.loads((root/'report/acceptance.json').read_text())
            self.assertIn(str(bad),acceptance['trace_read_errors'])


if __name__=='__main__':unittest.main()
