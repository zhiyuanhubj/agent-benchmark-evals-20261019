"""Protect resumable weight transfers against unauthorized reads and bad hashes."""
import hashlib,json,tempfile,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from native_transfer import source_handler,fetch_native

class NativeTransferTest(unittest.TestCase):
 def test_resume_authentication_and_exact_metadata(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source';target=root/'target';source.mkdir();target.mkdir();payload=bytes(range(256))*16384;name='weights.bin';(source/name).write_bytes(payload)
   manifest={'files':[{'file':name,'bytes':len(payload),'algorithm':'sha256','expected':hashlib.sha256(payload).hexdigest()}]}
   server=ThreadingHTTPServer(('127.0.0.1',0),source_handler(source,manifest,'fake-transfer-key'));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start();base='http://127.0.0.1:'+str(server.server_port)
   try:
    with self.assertRaises(HTTPError) as error:urlopen(base+'/'+name)
    self.assertEqual(error.exception.code,401)
    initial=123456;(target/(name+'.peer-partial')).write_bytes(payload[:initial])
    result=fetch_native(base,target,manifest,'fake-transfer-key',root/'progress.json',workers=2,reserve=0)
    self.assertTrue(result['valid']);self.assertEqual(result['initial_resumable_bytes'],initial);self.assertEqual((target/name).read_bytes(),payload)
    st=(target/name).stat();self.assertEqual(result['file_metadata'][name],{'size':st.st_size,'mtime_ns':st.st_mtime_ns,'ctime_ns':st.st_ctime_ns,'inode':st.st_ino,'device':st.st_dev})
   finally:server.shutdown();server.server_close();worker.join()
 def test_checksum_failure_never_publishes_weight(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source';source.mkdir();payload=b'corrupted-content';(source/'weights.bin').write_bytes(payload)
   manifest={'files':[{'file':'weights.bin','bytes':len(payload),'algorithm':'sha256','expected':'0'*64}]}
   server=ThreadingHTTPServer(('127.0.0.1',0),source_handler(source,manifest,'fake-transfer-key'));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
   try:
    with self.assertRaisesRegex(AssertionError,'Pinned checksum mismatch'):fetch_native('http://127.0.0.1:'+str(server.server_port),root/'target',manifest,'fake-transfer-key',root/'progress.json',workers=1,reserve=0)
    self.assertFalse((root/'target/weights.bin').exists())
   finally:server.shutdown();server.server_close();worker.join()

if __name__=='__main__':unittest.main()
