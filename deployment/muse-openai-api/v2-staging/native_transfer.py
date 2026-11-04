"""Authenticated, resumable native transfer of exactly pinned BF16 files."""
import json,hashlib,hmac,os,time,subprocess,threading,shutil
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import unquote,urlsplit,quote
from concurrent.futures import ThreadPoolExecutor

def source_handler(weights,manifest,token):
 weights=Path(weights).resolve();allowed={x['file']:x for x in manifest['files']}
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*_):pass
  def do_GET(self):
   if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):self.send_error(401);return
   name=unquote(urlsplit(self.path).path.lstrip('/'));p=(weights/name).resolve()
   if name not in allowed or not p.is_relative_to(weights) or not p.is_file():self.send_error(404);return
   size=allowed[name]['bytes']
   if p.stat().st_size!=size:self.send_error(409);return
   offset=0
   if self.headers.get('Range'):
    value=self.headers['Range']
    if not value.startswith('bytes=') or not value.endswith('-'):self.send_error(416);return
    try:offset=int(value[6:-1]);assert 0<=offset<size
    except (ValueError,AssertionError):self.send_error(416);return
   self.send_response(206 if offset else 200);self.send_header('Content-Length',str(size-offset));self.send_header('Accept-Ranges','bytes')
   if offset:self.send_header('Content-Range',f'bytes {offset}-{size-1}/{size}')
   self.end_headers()
   try:
    with p.open('rb') as f:self.connection.sendfile(f,offset=offset,count=size-offset)
   except (BrokenPipeError,ConnectionResetError):pass
 return Handler

def fetch_native(base,target,manifest,token,progress,workers=16,reserve=32*2**30):
 target=Path(target);target.mkdir(parents=True,exist_ok=True);rows=manifest['files'];total=sum(x['bytes'] for x in rows);began=time.time();done=threading.Event();complete=[];lock=threading.Lock()
 config=progress.parent/'peer-curl.conf';config.write_text('header = "Authorization: Bearer '+token+'"\n');config.chmod(0o600)
 def sizes():
  count=0
  for row in rows:
   p=target/row['file'];part=p.with_name(p.name+'.peer-partial')
   count+=min(row['bytes'],p.stat().st_size if p.exists() else part.stat().st_size if part.exists() else 0)
  return count
 initial=sizes();assert shutil.disk_usage(target).free>total-initial+reserve
 def report():
  while not done.wait(2):
   with lock:n=len(complete)
   data={'bytes_received':sizes(),'initial_resumable_bytes':initial,'total_bytes':total,'completed_files':n,'total_files':len(rows),'elapsed_seconds':time.time()-began,'updated_unix':time.time(),'method':'native curl resume + sendfile + SHA-256'}
   t=progress.with_suffix('.tmp');t.write_text(json.dumps(data)+'\n');t.replace(progress)
 reporter=threading.Thread(target=report,daemon=True);reporter.start()
 def verify(p,row):
  h=hashlib.sha256() if row['algorithm']=='sha256' else hashlib.sha1()
  if row['algorithm']=='git-blob-sha1':h.update(('blob '+str(row['bytes'])+'\0').encode())
  with p.open('rb') as f:
   for block in iter(lambda:f.read(16*2**20),b''):h.update(block)
  assert h.hexdigest()==row['expected'],'Pinned checksum mismatch: '+row['file']
 def one(row):
  p=target/row['file'];part=p.with_name(p.name+'.peer-partial');p.parent.mkdir(parents=True,exist_ok=True)
  if not p.exists():
   if not part.exists() or part.stat().st_size<row['bytes']:
    subprocess.run(['curl','--config',str(config),'--fail','--silent','--show-error','--retry','3','--retry-delay','2','--connect-timeout','15','--max-time','1200','--continue-at','-','--output',str(part),base+'/'+quote(row['file'],safe='')],check=True)
   assert part.stat().st_size==row['bytes'];verify(part,row);part.replace(p)
  else:
   assert p.stat().st_size==row['bytes'];verify(p,row)
  with lock:complete.append(row['file'])
 try:
  with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(one,rows))
 finally:done.set();reporter.join()
 result={'valid':True,'bytes_received':total,'total_bytes':total,'initial_resumable_bytes':initial,'verified_files':complete,'elapsed_seconds':time.time()-began,'updated_unix':time.time(),'method':'native curl resume + sendfile + SHA-256'}
 t=progress.with_suffix('.tmp');t.write_text(json.dumps(result,indent=2)+'\n');t.replace(progress);return result
