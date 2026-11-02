import hashlib
import httpx
import tempfile
import threading
import unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from peer_weights import handler,fetch


class PeerWeightsTest(unittest.TestCase):
    def test_only_authenticated_manifest_files_are_served_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'source';src.mkdir();(src/'model').write_bytes(b'weights');(src/'secret').write_text('not in manifest')
            manifest={'files':[dict(file='model',bytes=7,algorithm='sha256',expected=hashlib.sha256(b'weights').hexdigest())]}
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(src,manifest,'test-token'))
            t=threading.Thread(target=server.serve_forever);t.start();base='http://127.0.0.1:'+str(server.server_port)
            try:
                with httpx.Client(trust_env=False) as c:
                    self.assertEqual(c.get(base+'/model').status_code,401)
                    self.assertEqual(c.get(base+'/secret',headers={'Authorization':'Bearer test-token'}).status_code,404)
                    self.assertEqual(c.get(base+'/%2e%2e%2fsecret',headers={'Authorization':'Bearer test-token'}).status_code,404)
                result=fetch(base,root/'target',manifest,'test-token',root/'progress.json',workers=1,reserve=0)
                self.assertTrue(result['valid']);self.assertEqual((root/'target/model').read_bytes(),b'weights')
                reused=fetch(base,root/'target',manifest,'test-token',root/'progress.json',workers=1,reserve=0)
                self.assertEqual(reused['bytes_received'],0);self.assertEqual(reused['reused_verified_bytes'],7)
                manifest['files'][0]['expected']='0'*64
                with self.assertRaises(AssertionError):fetch(base,root/'bad',manifest,'test-token',root/'bad.json',workers=1,reserve=0)
                self.assertFalse((root/'bad/model').exists())
            finally:server.shutdown();server.server_close();t.join()


if __name__=='__main__':unittest.main()
