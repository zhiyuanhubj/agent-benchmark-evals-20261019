"""Ensure both public API versions authenticate and route to the intended precision."""
import asyncio,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
import httpx
PROJECT=Path(os.environ.get('MUSE_RELAY_PROJECT', str(Path(__file__).resolve().parents[2])))

class SSEStream(httpx.AsyncByteStream):
 async def __aiter__(self):
  yield b'data: {"choices":[{"delta":{"reasoning_content":"thinking"}}]}\n\ndata: {"choices":[{"delta":{"content":"5"}}]}\n\ndata: [DONE]\n\n'

class VersionedRelayTest(unittest.TestCase):
 def test_authentication_aliases_streams_and_precision_are_isolated(self):
  asyncio.run(self.check_versions())
 async def check_versions(self):
  sys.path.insert(0,str(PROJECT))
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);secret=root/'test.key';secret.write_text('fake-test-key')
   old=os.environ.get('MUSE_OPENAI_RELAY_CONFIG')
   try:
    for prefix,precision in [('/v1','nvfp4'),('/v2','bf16')]:
     model='muse-spark-open-'+precision;cfg=root/(precision+'.json');cfg.write_text(json.dumps({'api_prefix':prefix,'upstream_base':'http://backend/v1','models':{'muse-spark-open':model},'keys':[{'label':'client-01','file':str(secret),'models':['muse-spark-open']}],'usage_db':str(root/(precision+'.sqlite3'))}));os.environ['MUSE_OPENAI_RELAY_CONFIG']=str(cfg)
     spec=importlib.util.spec_from_file_location('relay_test_'+precision,PROJECT/'protocol/muse_openai_key_relay_20261021.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
     seen=[]
     def backend(request):
      if request.url.path=='/v1/models':return httpx.Response(200,json={'data':[{'id':model}]})
      body=json.loads(request.content);seen.append(body);self.assertEqual(body['model'],model)
      if body.get('stream'):return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=SSEStream())
      return httpx.Response(200,json={'choices':[{'message':{'content':'5','reasoning_content':'thinking'},'finish_reason':'stop'}]})
     async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as upstream:
      module.app.state.http=upstream
      async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app),base_url='http://test') as client:
       self.assertEqual((await client.get(prefix+'/models')).status_code,401)
       headers={'Authorization':'Bearer fake-test-key'}
       self.assertEqual((await client.get(prefix+'/models',headers={'Authorization':'Bearer wrong'})).status_code,401)
       models=await client.get(prefix+'/models',headers=headers);self.assertEqual(models.status_code,200);self.assertEqual(models.json()['data'][0]['id'],'muse-spark-open')
       other='/v2' if prefix=='/v1' else '/v1';self.assertEqual((await client.get(other+'/models',headers=headers)).status_code,404)
       self.assertEqual((await client.get(prefix+'/healthz')).json()['status'],'ok')
       body={'model':'muse-spark-open','messages':[{'role':'user','content':'2+3?'}],'reasoning_effort':'low','max_tokens':128}
       response=await client.post(prefix+'/chat/completions',headers=headers,json=body);self.assertEqual(response.status_code,200);self.assertEqual(response.json()['choices'][0]['message']['content'],'5')
       response=await client.post(prefix+'/chat/completions',headers=headers,json={**body,'stream':True});self.assertEqual(response.status_code,200);self.assertIn('reasoning_content',response.text);self.assertIn('[DONE]',response.text)
       denied=await client.post(prefix+'/chat/completions',headers=headers,json={**body,'model':'unapproved'});self.assertEqual(denied.status_code,403)
       self.assertEqual(seen[0]['reasoning_effort'],'low')
   finally:
    if old is None:os.environ.pop('MUSE_OPENAI_RELAY_CONFIG',None)
    else:os.environ['MUSE_OPENAI_RELAY_CONFIG']=old

if __name__=='__main__':unittest.main()
