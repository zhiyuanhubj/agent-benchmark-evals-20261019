"""Authenticated, manifest-limited local weight transfer inside an owned allocation."""
import argparse
import fcntl
import hashlib
import hmac
import json
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, quote

import httpx


def digest(row):
    assert row['algorithm'] in ('sha256','git-blob-sha1')
    h=hashlib.sha256() if row['algorithm']=='sha256' else hashlib.sha1()
    if row['algorithm']=='git-blob-sha1':h.update(('blob '+str(row['bytes'])+'\0').encode())
    return h


def handler(weights,manifest,token):
    weights=Path(weights).resolve();allowed={r['file']:r for r in manifest['files']}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*_):pass
        def do_GET(self):
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                self.send_error(401);return
            name=unquote(urlsplit(self.path).path.lstrip('/'))
            target=(weights/name).resolve()
            if name not in allowed or not target.is_relative_to(weights) or not target.is_file():
                self.send_error(404);return
            row=allowed[name]
            if target.stat().st_size!=row['bytes']:
                self.send_error(409);return
            self.send_response(200);self.send_header('Content-Length',str(row['bytes']));self.end_headers()
            try:
                with target.open('rb') as f:shutil.copyfileobj(f,self.wfile,16*2**20)
            except (BrokenPipeError,ConnectionResetError):pass
    return Handler


def fetch(base,target,manifest,token,progress,workers=8,reserve=32*2**30):
    target=Path(target);target.mkdir(parents=True,exist_ok=True)
    with (target/'.peer-transfer.lock').open('a') as transfer_lock:
        fcntl.flock(transfer_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _fetch_locked(base,target,manifest,token,progress,workers,reserve)


def _fetch_locked(base,target,manifest,token,progress,workers,reserve):
    total=sum(r['bytes'] for r in manifest['files']);received=0;complete=[];lock=threading.Lock();done=threading.Event()
    remaining=[];reused_bytes=0
    for row in manifest['files']:
        path=target/row['file'];partial=path.with_name(path.name+'.peer-partial')
        if partial.exists():partial.unlink()  # Only our incomplete transfer scratch file.
        if path.is_file() and path.stat().st_size==row['bytes']:
            h=digest(row)
            with path.open('rb') as f:
                for block in iter(lambda:f.read(16*2**20),b''):h.update(block)
            if h.hexdigest()==row['expected']:
                reused_bytes+=row['bytes'];complete.append(row['file']);continue
        remaining.append(row)
    assert shutil.disk_usage(target).free>total-reused_bytes+reserve, 'Insufficient space for direct-copy bytes plus bounded scratch reserve'
    began=time.time()
    def report():
        while not done.wait(2):
            with lock:d=dict(bytes_received=received,reused_verified_bytes=reused_bytes,total_bytes=total,completed_files=len(complete),total_files=len(manifest['files']),updated_unix=time.time(),elapsed_seconds=time.time()-began)
            tmp=progress.with_suffix('.tmp');tmp.write_text(json.dumps(d)+'\n');os.replace(tmp,progress)
    reporter=threading.Thread(target=report,daemon=True);reporter.start()
    try:
        with httpx.Client(trust_env=False,timeout=httpx.Timeout(300,connect=20),limits=httpx.Limits(max_connections=workers)) as client:
            def one(row):
                nonlocal received
                path=target/row['file'];path.parent.mkdir(parents=True,exist_ok=True)
                tmp=path.with_name(path.name+'.peer-partial');h=digest(row);count=0
                with client.stream('GET',base+'/'+quote(row['file'],safe=''),headers={'Authorization':'Bearer '+token}) as response:
                    response.raise_for_status();assert int(response.headers['Content-Length'])==row['bytes']
                    with tmp.open('wb') as out:
                        for block in response.iter_bytes(16*2**20):
                            out.write(block);h.update(block);count+=len(block)
                            with lock:
                                received+=len(block)
                                assert shutil.disk_usage(target).free>total-reused_bytes-received+reserve, 'Concurrent disk use exhausted direct-copy reserve'
                assert count==row['bytes'] and h.hexdigest()==row['expected'], 'Pinned checksum mismatch: '+row['file']
                os.replace(tmp,path)
                with lock:complete.append(row['file'])
            with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,remaining))
    finally:
        done.set();reporter.join()
    result=dict(valid=True,bytes_received=received,reused_verified_bytes=reused_bytes,total_bytes=total,verified_files=complete,elapsed_seconds=time.time()-began,updated_unix=time.time(),source='owned_peer_cache',reserve_bytes=reserve)
    tmp=progress.with_suffix('.tmp');tmp.write_text(json.dumps(result,indent=2)+'\n');os.replace(tmp,progress);return result


def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['serve','fetch']);p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--weights',type=Path,required=True);p.add_argument('--token-file',type=Path,required=True)
    p.add_argument('--bind');p.add_argument('--port',type=int,default=31480);p.add_argument('--base');p.add_argument('--progress',type=Path)
    a=p.parse_args();manifest=json.loads(a.plan.read_text())['models']['bf16'];token=a.token_file.read_text().strip()
    if a.action=='serve':ThreadingHTTPServer((a.bind,a.port),handler(a.weights,manifest,token)).serve_forever()
    else:fetch(a.base,a.weights,manifest,token,a.progress)


if __name__=='__main__':main()
