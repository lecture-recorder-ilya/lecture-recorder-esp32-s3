import sys,tempfile,threading,unittest,wave,io,json,hashlib
from pathlib import Path
from types import SimpleNamespace
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
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.files=self.root/'recordings';self.files.mkdir();self.ledger=self.root/'ledger.json';H.ack=0;H.data=PAYLOAD;H.fail=False;H.cutoff=None;H.ranges=[];self.item={'name':NAME,'bytes':len(PAYLOAD),'sha256':SHA}
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
 def test_two_sources_same_time_keep_both_ids_and_route_their_notes(self):
  import phone_notes,lesson_schedule
  second=PAYLOAD[:44]+b'\x02\x00'*16000
  other_sha=hashlib.sha256(second).hexdigest()
  a='1'*32;b='2'*32
  with patch('phone_sync.queue_pending'),patch('lesson_schedule.organize'):
   def receive(data,device):
    H.data=data
    item=dict(self.item,sha256=hashlib.sha256(data).hexdigest(),started_ms=1791795600000)
    return phone_sync.import_one(item,self.base,'fixture',self.files,self.ledger,device)
   first=receive(PAYLOAD,a);other=receive(second,b)
   self.assertEqual(receive(second,b),other);self.assertEqual(receive(PAYLOAD,a),first)
   self.assertEqual(len(H.ranges),2);self.assertEqual(H.ack,4)
   self.assertEqual(lesson_schedule.recording_time(first),lesson_schedule.recording_time(other))
   self.assertEqual({p.name:phone_sync.digest(p) for p in self.files.glob('*.wav')},{first:SHA,other:other_sha})
   ledger=json.loads(self.ledger.read_text())
   self.assertEqual(phone_notes.recording_targets(ledger,a,()),{first:NAME,other:None})
   self.assertEqual(phone_notes.recording_targets(ledger,b,()),{first:None,other:NAME})
   self.assertEqual(phone_notes.recording_targets(ledger,b,[dict(self.item,sha256='0'*64)]),{first:None,other:None})
   self.assertEqual(receive(second,'3'*32),other)
   self.assertEqual(len(H.ranges),2);self.assertEqual(len(json.loads(self.ledger.read_text())),2)

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
 def test_resume_needs_space_only_for_remaining_bytes(self):
  H.cutoff=len(PAYLOAD)//2
  with self.assertRaises(ConnectionError):self.run_import()
  remaining=len(PAYLOAD)-H.cutoff
  H.cutoff=None
  part=self.files/(NAME+'.phone-part')
  with patch('phone_sync.shutil.disk_usage',return_value=SimpleNamespace(free=100*1024*1024+remaining-1)),self.assertRaises(OSError):
   self.run_import()
  self.assertEqual(part.stat().st_size,len(PAYLOAD)//2);self.assertEqual(H.ack,0)
  with patch('phone_sync.shutil.disk_usage',return_value=SimpleNamespace(free=100*1024*1024+remaining)):
   self.run_import()
  self.assertEqual(H.ranges,[None,'bytes='+str(len(PAYLOAD)//2)+'-'])
  self.assertEqual(phone_sync.digest(self.files/NAME),SHA);self.assertEqual(H.ack,1)

 def test_restart_after_link_cleans_the_partial_without_another_download(self):
  link=phone_sync.os.link
  def interrupted(source,target):
   link(source,target)
   raise InterruptedError('остановка после публикации WAV')
  with patch('phone_sync.os.link',side_effect=interrupted),self.assertRaises(InterruptedError):
   self.run_import()
  part=self.files/(NAME+'.phone-part');meta=self.files/(NAME+'.phone-part.json')
  self.assertTrue(part.samefile(self.files/NAME));self.assertEqual(H.ack,0)
  self.run_import()
  self.assertEqual(H.ranges,[None]);self.assertEqual(H.ack,1)
  self.assertFalse(part.exists());self.assertFalse(meta.exists())
  self.assertEqual(phone_sync.digest(self.files/NAME),SHA)
 def test_chosen_lesson_is_saved_before_phone_ack(self):
  lesson={'date':'2026-10-12','start':'11:55','end':'13:25','subject':'Математический анализ','type':'ЛК','group':'ИКБО-01-26','room':'А-001','source':'mirea'}
  self.item.update(lesson_decided=True,lesson=lesson)
  with patch('study_store.ROOT',self.root):
   self.run_import()
   import study_store
   saved=study_store.overrides()[NAME]
  self.assertEqual(saved['subject'],lesson['subject'])
  self.assertEqual(saved['start'],lesson['start'])
  self.assertTrue((self.root/'lessons'/saved['folder']/NAME).is_file())
  self.assertEqual(H.ack,1)
 def test_invalid_lesson_keeps_phone_recording(self):
  self.item.update(lesson_decided=True,lesson=['wrong type'])
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual(H.ack,0)
 def test_bad_name_never_ack(self):
  self.item['name']='../outside.wav'
  with self.assertRaises(ValueError):self.run_import()
  self.assertEqual(H.ack,0)
if __name__=='__main__':unittest.main()
