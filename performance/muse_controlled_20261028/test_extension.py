"""A fixed-cap offered-load extension must repeat and stop at measured saturation."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch

from bench import extend_saturation


class ExtensionTest(unittest.IsolatedAsyncioTestCase):
    async def test_three_repeats_and_real_plateau_resolve_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);corpus=root/'corpus.jsonl';corpus.write_text('{"id":"fixture","prompt":"fixture"}\n')
            for rep in range(3):
                d=root/f'c256-r{rep}';d.mkdir()
                (d/'summary.json').write_text(json.dumps({'valid_curve_point':True,'output_tokens_per_second_per_gpu':100}))
            (root/'FOLLOWUP_REQUIRED.json').write_text('{"reason":"not saturated"}')
            tested=[]
            class FakeRound:
                def __init__(self,args,scenario,c,rep,d):self.c=c;self.rep=rep
                async def run(self,client,prompts):
                    tested.append((self.c,self.rep))
                    return {'valid_curve_point':True,'failed_arrivals_after_drain':0,
                            'output_tokens_per_second_per_gpu':102,'ttft_s':{'p95':1},'e2e_s':{'p95':10}}
            class Client:
                async def __aenter__(self):return self
                async def __aexit__(self,*_):pass
                async def get(self,*_):return SimpleNamespace(json=lambda:{'disable_radix_cache':True,'max_running_requests':256,'speculative_algorithm':None,'kv_cache_dtype':'fp8_e4m3'})
            args=SimpleNamespace(base='http://fixture',corpus=corpus,request_timeout=600,server_cap=256,
                                 seed=1,ttft_limit=60,e2e_limit=300)
            with patch('bench.httpx.AsyncClient',return_value=Client()),patch('bench.Round',FakeRound),patch('bench.Prompts.build',new=AsyncMock(return_value=SimpleNamespace(sequence=0))):
                await extend_saturation(args,root)
            self.assertEqual(tested,[(512,0),(512,1),(512,2)])
            self.assertFalse((root/'FOLLOWUP_REQUIRED.json').exists())
            j=json.loads((root/'EXTENSION_RESOLUTION.json').read_text())
            self.assertTrue(j['saturation_or_latency_limit_observed'])
            self.assertEqual(j['stop_reason'],'less_than_5_percent_throughput_gain')


if __name__=='__main__':unittest.main()
