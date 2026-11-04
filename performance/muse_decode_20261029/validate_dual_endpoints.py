"""Validate identical key files and common-model requests against both public versions."""
import asyncio,json,time
from pathlib import Path
import httpx
R=Path(__file__).resolve().parent;private=Path('/fsx/home/zhiyuan/.private/muse_openai_api_20261021');rt1=private/'restore_bf16_20261102';rt2=private/'restore_bf16_v2_20261104'
async def main():
 configs=[json.loads((rt/'gateway-bf16.json').read_text()) for rt in [rt1,rt2]]
 keys=[{row['label']:row['file'] for row in cfg['keys'] if row.get('label') in ['client-01','client-02','client-03']} for cfg in configs];assert keys[0]==keys[1] and len(keys[0])==3
 result={'updated_unix':time.time(),'identical_original_key_files':True,'model_alias':'muse-spark-open','key_checks':[],'generations':[]}
 async with httpx.AsyncClient(trust_env=False,timeout=180) as client:
  async def models(label,path,version):
   response=await client.get('https://muse.zhiyuanllm.com/'+version+'/models',headers={'Authorization':'Bearer '+Path(path).read_text().strip()});response.raise_for_status();assert 'muse-spark-open' in {x['id'] for x in response.json()['data']};return {'label':label,'version':version,'models_http':response.status_code}
  result['key_checks']=await asyncio.gather(*(models(label,path,version) for label,path in keys[0].items() for version in ['v1','v2']))
  body={'model':'muse-spark-open','messages':[{'role':'user','content':'Compute 37 * 43. Give only the product in the final answer.'}],'reasoning_effort':'low','max_tokens':2048,'stream':False}
  secret=Path(keys[0]['client-02']).read_text().strip()
  async def generate(version,precision):
   response=await client.post('https://muse.zhiyuanllm.com/'+version+'/chat/completions',headers={'Authorization':'Bearer '+secret},json=body);response.raise_for_status();reply=response.json();choice=reply['choices'][0];message=choice['message'];assert reply['model']=='muse-spark-open-'+precision;assert choice['finish_reason']=='stop' and '1591' in (message.get('content') or '') and message.get('reasoning_content');return {'version':version,'precision':precision,'response_model':reply['model'],'http':response.status_code,'final_content':message['content'],'reasoning_chars':len(message['reasoning_content']),'finish_reason':choice['finish_reason'],'usage':reply.get('usage')}
  result['generations']=await asyncio.gather(generate('v1','nvfp4'),generate('v2','bf16'))
  result['unauthenticated_http']={}
  for version in ['v1','v2']:
   response=await client.get('https://muse.zhiyuanllm.com/'+version+'/models');assert response.status_code==401;result['unauthenticated_http'][version]=401
 result['passed']=True;(R/'DUAL_ENDPOINT_VALIDATION_20261104.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
asyncio.run(main())
