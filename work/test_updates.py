import hashlib,io,json,os,struct,sys,tempfile,threading,unittest,wave,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import update_manager as u
import wav_recovery,phone_notes,lesson_schedule

class Updates(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  (self.root/'release.json').write_text(json.dumps(dict(version='1.0',code=1,runtime=1,repository=u.REPOSITORY)))
  (self.root/'outputs/recorder').mkdir(parents=True)
  (self.root/'outputs/recorder/recorder.py').write_text('old = True\n')
  self.data=self.root/'outputs/recorder/recordings';self.data.mkdir();(self.data/'lecture.wav').write_bytes(b'personal audio')
 def tearDown(self):self.tmp.cleanup()
 def package(self,extra=None,meta=None):
  files={'release.json':json.dumps(meta or dict(version='2.0',code=2,runtime=1,repository=u.REPOSITORY)),
   'outputs/recorder/app_server.py':'new = True\n','outputs/recorder/recorder.py':'new = True\n','outputs/recorder/update_manager.py':'new = True\n'}
  files.update(extra or {});folder=self.root/'work/updates';folder.mkdir(parents=True,exist_ok=True);p=folder/'candidate.zip'
  with zipfile.ZipFile(p,'w') as z:
   for n,v in files.items():z.writestr(n,v)
  u.atomic(folder/'pending.json',{'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  return p
 def test_redirect_strips_token_on_another_host(self):
  req=u.Request('https://api.github.com/asset',headers={'Authorization':'Bearer fixture'})
  redirect=u.ReleaseRedirect().redirect_request(req,None,302,'',{},'https://release-assets.githubusercontent.com/file')
  self.assertIsNone(redirect.get_header('Authorization'))
  with self.assertRaises(ValueError):u.ReleaseRedirect().redirect_request(req,None,302,'',{},'http://example.com/file')
 def test_download_checks_digest(self):
  archive=self.package().read_bytes();digest=hashlib.sha256(archive).hexdigest()
  def responses(correct):
   release={'tag_name':'v2.0','assets':[{'name':'lecture-mac-update.zip','id':123,'digest':'sha256:'+correct,'size':len(archive)}]}
   return [io.BytesIO(json.dumps(release).encode()),io.BytesIO(archive)]
  with patch.object(u,'fetch',side_effect=responses('0'*64)),self.assertRaises(ValueError):u.download_release(self.root)
  with patch.object(u,'fetch',side_effect=responses(digest)):u.download_release(self.root)
  self.assertEqual(u.read(self.root/'work/updates/pending.json')['sha256'],digest)
  u.install(self.root);self.assertEqual(u.read(self.root/'release.json')['code'],2)
 def test_startup_waits_for_active_install(self):
  attempted=threading.Event();done=threading.Event()
  def startup():attempted.set();u.recover(self.root);done.set()
  with u.install_lock(self.root):
   thread=threading.Thread(target=startup);thread.start();self.assertTrue(attempted.wait(1));self.assertFalse(done.wait(.1))
  thread.join(2);self.assertTrue(done.is_set())
 def test_update_waits_for_pairing_before_restarting(self):
  for active in (True,False):
   server=SimpleNamespace(service_url='http://fixture',pairing=SimpleNamespace(public=lambda:{'active':active}),install_requested=False,shutdown=Mock())
   stop=Mock();stop.is_set.side_effect=[False,True]
   def read(path):return {'version':'2.0'} if path.name=='pending.json' else {}
   def thread(target,**kwargs):return SimpleNamespace(start=target)
   with patch.object(u,'STOP',stop),patch.object(u,'read',side_effect=read),patch.object(u,'download_release'),patch.object(u,'idle',return_value=True),patch.object(u.threading,'Thread',side_effect=thread):u.start(server)
   self.assertEqual(server.install_requested,not active)
   self.assertEqual(server.shutdown.call_count,0 if active else 1)
 def test_install_preserves_data(self):
  self.package();u.install(self.root)
  self.assertEqual((self.data/'lecture.wav').read_bytes(),b'personal audio')
  self.assertEqual(u.read(self.root/'release.json')['code'],2)
  self.assertEqual((self.root/'work/updates/backup/outputs/recorder/recorder.py').read_text(),'old = True\n')
  self.assertFalse((self.root/'work/updates/transaction.json').exists())
 def test_partial_install_rolls_back(self):
  self.package();real=os.replace
  def fail(src,dest):
   if str(dest).endswith('/app_server.py'):raise OSError('simulated disk failure')
   return real(src,dest)
  with patch.object(u.os,'replace',side_effect=fail),self.assertRaises(OSError):u.install(self.root)
  self.assertEqual(u.read(self.root/'release.json')['code'],1)
  self.assertFalse((self.root/'outputs/recorder/app_server.py').exists())
  self.assertEqual((self.root/'outputs/recorder/recorder.py').read_text(),'old = True\n')
 def test_startup_rolls_back_interrupted_transaction(self):
  folder=self.root/'work/updates';backup=folder/'backup/outputs/recorder';backup.mkdir(parents=True)
  (backup/'recorder.py').write_text('old = True\n')
  (self.root/'outputs/recorder/recorder.py').write_text('partial = True\n')
  u.atomic(folder/'transaction.json',{'files':{'outputs/recorder/recorder.py':True}});u.recover(self.root)
  self.assertEqual((self.root/'outputs/recorder/recorder.py').read_text(),'old = True\n')
 def test_reject_data_and_traversal(self):
  for n in ['../outside.py','outputs/recorder/recordings/lecture.wav','outputs/recorder/schedule.json','work/token.json','/release.json','outputs/recorder/../recorder/evil.py']:
   with self.subTest(n=n),self.assertRaises(ValueError):u.inspect_package(self.package({n:'data'}),self.root)
 def test_reject_invalid_code(self):
  with self.assertRaises(SyntaxError):u.inspect_package(self.package({'outputs/recorder/recorder.py':'def bad('}),self.root)
 def test_reject_old_or_incompatible(self):
  for m in [dict(code=1,runtime=1),dict(code=2,runtime=2),dict(code=True,runtime=1)]:
   with self.subTest(m=m),self.assertRaises(ValueError):u.inspect_package(self.package(meta=dict(m,version='x',repository=u.REPOSITORY)),self.root)
 def test_reject_changed_archive(self):
  p=self.package();p.write_bytes(p.read_bytes()+b'changed')
  with self.assertRaises(ValueError):u.install(self.root)
 def test_reject_symlink_destination(self):
  outside=self.root/'other';outside.write_text('preserve');(self.root/'outputs/recorder/recorder.py').unlink();(self.root/'outputs/recorder/recorder.py').symlink_to(outside)
  with self.assertRaises(ValueError):u.inspect_package(self.package(),self.root)
  self.assertEqual(outside.read_text(),'preserve')
 def test_reject_duplicate_entry(self):
  p=self.package()
  import warnings
  with warnings.catch_warnings():
   warnings.simplefilter('ignore')
   with zipfile.ZipFile(p,'a') as z:z.writestr('release.json','{}')
  with self.assertRaises(ValueError):u.inspect_package(p,self.root)
 def test_wait_while_recording_or_ai_busy(self):
  for data in [{'recording':True},{'busy':True},{'ai':{'jobs':{'x':{'status':'processing'}}}}]:
   with patch.object(u,'urlopen',return_value=io.BytesIO(json.dumps(data).encode())):self.assertFalse(u.idle('http://fixture'))
  with patch.object(u,'urlopen',return_value=io.BytesIO(b'{}')):self.assertTrue(u.idle('http://fixture'))

class Recovery(unittest.TestCase):
 def test_killed_writer_recovers_all_physical_frames(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'lecture-fixture.wav';raw=p.open('w+b');w=wave.open(raw,'wb');w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframesraw(b'\x01\x00'*256);w.writeframesraw(b'\x02\x00'*1024);raw.flush()
   self.assertEqual(wav_recovery.recover(Path(d)),[p.name])
   w._file=None;raw.close()
   with wave.open(str(p)) as audio:self.assertEqual(audio.getnframes(),1280);self.assertEqual(audio.readframes(1280),b'\x01\x00'*256+b'\x02\x00'*1024)
   self.assertEqual(wav_recovery.recover(Path(d)),[])
 def test_valid_metadata_is_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'lecture-fixture.wav'
   with wave.open(str(p),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*30)
   with p.open('r+b') as f:f.seek(0,2);f.write(b'LIST'+struct.pack('<I',4)+b'INFO');size=f.tell();f.seek(4);f.write(struct.pack('<I',size-8))
   original=p.read_bytes();self.assertEqual(wav_recovery.recover(Path(d)),[]);self.assertEqual(p.read_bytes(),original)
   with wave.open(str(p)) as w:self.assertEqual(w.getnframes(),30)
 def test_unreadable_file_does_not_prevent_startup(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'lecture-fixture.wav';p.write_bytes(b'fixture')
   with patch.object(Path,'open',side_effect=PermissionError):self.assertEqual(wav_recovery.recover(Path(d)),[])
 def test_riff_size_and_incomplete_sample(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'lecture-fixture.wav'
   with wave.open(str(p),'wb') as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*30)
   with p.open('r+b') as f:f.seek(4);f.write(struct.pack('<I',0));f.seek(0,2);f.write(b'\x01')
   self.assertEqual(wav_recovery.recover(Path(d)),[p.name]);self.assertEqual(p.stat().st_size,104)

class Notes(unittest.TestCase):
 def test_incremental_transfer_and_final_text(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'analysis').mkdir();name='lecture-2026-10-12-12-00-00-123000.wav';p=root/'analysis'/(Path(name).stem+'.live.json')
   p.write_text(json.dumps({'segments':[{'text':'начало','start':0,'end':1,'private':'excluded'}],'secret':'excluded'}))
   known={};calls=[]
   def request(base,token,route,data=None):
    if route=='/notes-index':return io.BytesIO(json.dumps(known).encode())
    self.assertEqual(route,'/notes');calls.append(data);digest=hashlib.sha256(json.dumps(data).encode()).hexdigest();known[data['file']]=digest;return io.BytesIO(json.dumps({'sha256':digest}).encode())
   with patch('phone_sync.request',side_effect=request):
    self.assertEqual(phone_notes.push('fixture','token',root),1);self.assertEqual(phone_notes.push('fixture','token',root),0)
    self.assertTrue(calls[0]['report']['draft']);self.assertNotIn('secret',calls[0]['report']);self.assertNotIn('private',calls[0]['report']['segments'][0])
    final=p.with_name(p.name.replace('.live.json','.json'));final.write_text(json.dumps({'segments':[{'text':'готовый текст'}],'summary':['тема']}))
    self.assertEqual(phone_notes.push('fixture','token',root),1);self.assertFalse(calls[-1]['report']['draft'])
 def test_newer_draft_cannot_replace_final(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'analysis').mkdir();stem='lecture-2026-10-12-12-00-00-123000'
   final=root/'analysis'/(stem+'.json');draft=root/'analysis'/(stem+'.live.json')
   final.write_text(json.dumps({'segments':[{'text':'готовый текст'}]}));draft.write_text(json.dumps({'segments':[{'text':'черновик'}]}));os.utime(draft,ns=(final.stat().st_mtime_ns+1000000,final.stat().st_mtime_ns+1000000))
   values=list(phone_notes.documents(root));self.assertEqual(len(values),1);self.assertFalse(values[0][0]['report']['draft']);self.assertEqual(values[0][0]['report']['segments'][0]['text'],'готовый текст')
 def test_broken_file_does_not_block_other_lectures(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'analysis').mkdir();(root/'analysis/lecture-2026-10-12-11-00-00-123000.json').write_text('{invalid')
   (root/'analysis/lecture-2026-10-12-12-00-00-123000.json').write_text(json.dumps({'segments':[None,{'text':'сохранённый текст'}]}))
   calls=[]
   def request(base,token,route,data=None):
    if route=='/notes-index':return io.BytesIO(b'{}')
    calls.append(data);return io.BytesIO(json.dumps({'sha256':hashlib.sha256(json.dumps(data).encode()).hexdigest()}).encode())
   with patch('phone_sync.request',side_effect=request),self.assertRaisesRegex(ValueError,'Пропущено файлов: 1'):phone_notes.push('fixture','token',root)
   self.assertEqual(len(calls),1);self.assertEqual([row['text'] for row in calls[0]['report']['segments']],['сохранённый текст']);self.assertNotIn('start',calls[0]['report']['segments'][0])
 def test_empty_default_schedule(self):
  with patch.object(lesson_schedule,'DATA',{'group':'','entries':[],'timezone':'Europe/Moscow'}):
   value=lesson_schedule.current();self.assertIsNone(value['first']);self.assertIsNone(value['next'])

class RecorderCommands(unittest.TestCase):
 def test_invalid_requests_are_rejected(self):
  import recorder,http.client
  server=recorder.ThreadingHTTPServer(('127.0.0.1',0),recorder.Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   for length,body,expected in [('bad',b'',400),('-1',b'',413),('2',b'[]',400)]:
    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2);conn.request('POST','/ai-settings',body=body,headers={'Content-Length':length});response=conn.getresponse();self.assertEqual(response.status,expected);response.read();conn.close()
  finally:server.shutdown();server.server_close()
 def test_no_new_jobs_after_shutdown_accepted(self):
  import recorder,ai_service,http.client
  server=recorder.ThreadingHTTPServer(('127.0.0.1',0),recorder.Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   with patch.dict(recorder.state,{'recording':False,'busy':False,'updating':False}),patch.object(ai_service,'stopping',False),patch.object(ai_service,'pending',set()),patch.object(ai_service,'file_path'),patch.object(ai_service,'status',return_value={'ready':True}):
    conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=2);conn.request('POST','/shutdown-for-update',body=b'{}');response=conn.getresponse();self.assertEqual(response.status,200);response.read();conn.close()
    with self.assertRaises(RuntimeError):ai_service.submit('fixture.wav')
    self.assertFalse(ai_service.pending);self.assertTrue(recorder.state['updating'])
  finally:server.shutdown();thread.join(2);server.server_close()

if __name__=='__main__':unittest.main()
