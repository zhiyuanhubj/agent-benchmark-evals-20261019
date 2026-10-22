#!/usr/bin/env python3
"""Host-side OpenAI/SGLang forwarding; upstream keys never enter task configs."""
import argparse
import os
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse,JSONResponse
from starlette.background import BackgroundTask
import uvicorn


def create_app(upstream,key,tokenizer=None):
    upstream=upstream.rstrip('/')
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(3600,connect=30),trust_env=True) as client:
            app.state.client=client
            yield
    app=FastAPI(lifespan=lifespan)

    @app.api_route('/{path:path}',methods=['GET','POST'])
    async def forward(path:str,request:Request):
        if path not in ('tokenize','get_server_info') and not path.startswith('v1/'):
            return JSONResponse({'error':'Unsupported model endpoint'},status_code=404)
        native=path in ('tokenize','get_server_info')
        base=(tokenizer or upstream.removesuffix('/v1')).rstrip('/') if native else upstream
        suffix=path if native else path.removeprefix('v1/')
        headers={}
        if key:headers['Authorization']='Bearer '+key
        if request.headers.get('content-type'):headers['Content-Type']=request.headers['content-type']
        outgoing=app.state.client.build_request(request.method,base+'/'+suffix,
            params=request.query_params,content=await request.body(),headers=headers)
        response=await app.state.client.send(outgoing,stream=True)
        # Forward raw SSE deltas, including reasoning_content and usage, unchanged.
        return StreamingResponse(response.aiter_raw(),status_code=response.status_code,
            headers={k:v for k,v in response.headers.items() if k.lower() in ('content-type','cache-control','content-encoding')},
            background=BackgroundTask(response.aclose))
    return app


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--upstream',default=os.environ.get('MODEL_BASE_URL'))
    p.add_argument('--key-env',default='MODEL_API_KEY')
    p.add_argument('--tokenizer-upstream',default=os.environ.get('TOKENIZER_BASE_URL'))
    p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=31320)
    args=p.parse_args();assert args.upstream,'Set MODEL_BASE_URL or --upstream'
    uvicorn.run(create_app(args.upstream,os.environ.get(args.key_env,''),args.tokenizer_upstream),
                host=args.host,port=args.port,access_log=False)
