#!/usr/bin/env python3
"""Offline validation: hashes, all profile configs, imports and SSE forwarding."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent


def main():
    manifest=json.loads((ROOT/'WORKSPACE_MANIFEST.json').read_text())
    for name,metadata in [('workspace.tar.zst',manifest),('workspace_supplement.tar.zst',json.loads((ROOT/'SUPPLEMENT_MANIFEST.json').read_text()))]:
        with (ROOT/name).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==metadata['archive_sha256']
    assert manifest['task_counts']['tb21']==89 and manifest['task_counts']['pro']==731
    assert len(set(manifest['deepswe_task_paths']))==113
    pro=ROOT/'workspace/AgentCompass-official-baseline/data/swe_bench_pro_verified/swebench_pro_verified.jsonl'
    assert len({json.loads(line)['instance_id'] for line in pro.read_text().splitlines() if line.strip()})==731
    swr_data=ROOT/'workspace/bench/code-review-eval/data/repos/swrbench/data/swr_datasets_d5c5.jsonl'
    assert len({json.loads(line)['instance_id'] for line in swr_data.read_text().splitlines() if line.strip()})==1000
    from evaluate import directories
    plans=0
    with tempfile.TemporaryDirectory(prefix='benchmark-portability-') as temp:
        for profile in ('muse_nvfp4','muse_bf16','beam','opus47'):
            for bench in ('tb21','pro','deepswe','swe_review'):
                output=Path(temp)/(profile+'-'+bench)
                p=subprocess.run([sys.executable,str(ROOT/'evaluate.py'),bench,'--profile',profile,
                    '--limit','1','--output',str(output)],capture_output=True,text=True)
                assert p.returncode==0,(profile,bench,p.stderr[-3000:])
                entries=json.loads((output/'PLAN.json').read_text());plans+=len(entries)
                for entry in entries:
                    assert entry['tasks']==1 and entry['argv'][1].startswith(str(ROOT))
                    env=dict(os.environ);env.update(entry['env'])
                    if bench=='pro':
                        checked=subprocess.run([sys.executable,entry['argv'][1],'--help'],
                            env=env,capture_output=True,text=True)
                        assert checked.returncode==0,(profile,bench,checked.stderr[-3000:])
                        continue
                    if bench=='tb21':code='import archived_terminus'
                    elif bench=='swe_review':code='import review_agents'
                    else:code='import runpy;runpy.run_path('+repr(entry['argv'][1])+',run_name="portability_import_test")'
                    checked=subprocess.run([sys.executable,'-c',code],env=env,capture_output=True,text=True)
                    assert checked.returncode==0,(profile,bench,checked.stderr[-3000:])
    # No GPU, external API calls or task containers are used for this test.
    import httpx
    from fastapi.testclient import TestClient
    from model_bridge import create_app
    real_client=httpx.AsyncClient
    payload=b'data: {"choices":[{"delta":{"reasoning_content":"test thinking"}}]}\n\ndata: [DONE]\n\n'
    class ByteStream(httpx.AsyncByteStream):
        async def __aiter__(self):yield payload
    observed=[]
    def upstream(request):
        observed.append({'path':request.url.path,'body':request.content})
        assert request.headers['Authorization']=='Bearer private-test-placeholder'
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=ByteStream())
    def factory(*args,**kwargs):
        kwargs['trust_env']=False;kwargs['transport']=httpx.MockTransport(upstream)
        return real_client(*args,**kwargs)
    with patch('model_bridge.httpx.AsyncClient',side_effect=factory):
        with TestClient(create_app('https://unit.test/v1','private-test-placeholder')) as client:
            response=client.post('/v1/chat/completions',json={'model':'fixture','stream':True})
            assert response.status_code==200 and response.content==payload
    assert observed[0]['path']=='/v1/chat/completions'
    assert b'private-test-placeholder' not in observed[0]['body']
    # Import unchanged official prompt/scorer modules with their own transport.
    import run_swrbench as swr
    sys.modules['utils']=swr.module('portable_swr_test_transport',swr.WORK/'swr_utils.py')
    swr.module('portable_official_generation_test',swr.WORK/'vendor/swr_generation.py')
    swr.module('portable_official_evaluation_test',swr.WORK/'vendor/swr_evaluation_struct.py')
    result={'archive_checksums':'passed','profile_task_configs':plans,
        'profile_wrapper_imports':'passed','mock_sse_thinking_forwarding':'passed',
        'upstream_key_excluded_from_request_body':'passed','official_swr_modules':'passed',
        'full_benchmark_executed':False,'external_model_requests':0,'task_containers_started':0}
    print(json.dumps(result))


if __name__=='__main__':main()
