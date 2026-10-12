import sys,tempfile,threading,unittest,wave,io,json,hashlib
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import phone_sync
b=io.BytesIO()
with wave.open(b,'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\x01\x00'*16000)
PAYLOAD=b.getvalue();SHA=hashlib.sha256(PAYLOAD).hexdigest();NAME='lecture-2026-10-12-12-00-00-123000.wav'
class H(BaseHTTPRequestHandler):
 data=PAYLOAD;ack=0;fail=False;cutoff=None;ranges=[]
 def log_message(self,*_):pass
 def do_GET(self):
  requested=self.headers.get('Range');H.ranges.append(requested);offset=int(requested.removeprefix('bytes=').removesuffix('-')) if requested else 0
  self.send_response(206 if requested else 200);self.send_header('Content-Length',str(len(self.data)-offset))
  if requested:self.send_header('Content-Range','bytes '+str(offset)+'-'+str(len(self.data)-1)+'/'+str(len(self.data)))
  self.end_headers();self.wfile.write(self.data[offset:H.cutoff] if H.cutoff is not None else self.data[offset:])
 def do_POST(self):
  H.ack+=1;self.rfile.read(int(self.headers['Content-Length']));self.send_response(500 if H.fail else 200);self.end_headers();self.wfile.write(b'{"ok":true}')
class Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.server=ThreadingHTTPServer(('127.0.0.1',0),H);threading.Thread(target=cls.server.serve_forever,daemon=True).start();cls.base='http://127.0.0.1:'+str(cls.server.server_port)
 @classmethod
 def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.files=self.root/'files';self.files.mkdir();self.ledger=self.root/'ledger.json';H.ack=0;H.data=PAYLOAD;H.fail=False;H.cutoff=None;H.ranges=[];self.item={'name':NAME,'bytes':len(PAYLOAD),'sha256':SHA}
 def tearDown(self):self.tmp.cleanup()
 def run_import(self):
  with patch('phone_sync.queue_pending'),patch('lesson_schedule.organize'):
   return phone_sync.import_one(self.item,self.base,'token',self.files,self.ledger)
 def test_verified_import_ack_after_disk_copy(self):
  self.run_import();self.assertEqual(phone_sync.digest(self.files/NAME),SHA);self.assertEqual(H.ack,1);self.assertTrue(self.ledger.exists())
 def test_corrupted_download_never_ack(self):
  H.data=PAYLOAD[:-1]+b'\xff'
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual(H.ack,0);self.assertFalse((self.files/NAME).exists())
 def test_ack_failure_retries_without_duplicate(self):
  H.fail=True
  with self.assertRaises(Exception):self.run_import()
  self.assertTrue((self.files/NAME).exists());H.fail=False;self.run_import();self.assertEqual(H.ack,2);self.assertEqual(len(list(self.files.glob('*.wav'))),1)
 def test_collision_preserves_both(self):
  (self.files/NAME).write_bytes(b'existing')
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual((self.files/NAME).read_bytes(),b'existing');self.assertEqual(H.ack,0)
 def test_truncated_wav_never_ack(self):
  H.data=PAYLOAD[:-100];self.item['bytes']=len(H.data);self.item['sha256']=hashlib.sha256(H.data).hexdigest()
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual(H.ack,0)
 def test_interrupted_download_resumes_verified_partial_copy(self):
  H.cutoff=10000
  with self.assertRaises(ConnectionError):self.run_import()
  self.assertEqual(H.ack,0);self.assertEqual((self.files/(NAME+'.phone-part')).stat().st_size,10000)
  H.cutoff=None;self.run_import()
  self.assertEqual(H.ranges,[None,'bytes=10000-']);self.assertEqual(H.ack,1)
  self.assertEqual(phone_sync.digest(self.files/NAME),SHA)
 def test_bad_name_never_ack(self):
  self.item['name']='../outside.wav'
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual(H.ack,0)
if __name__=='__main__':unittest.main()
