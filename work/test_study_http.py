import json,sys,tempfile,threading,wave
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import study_store as store
import study_service as study
import app_server as application
import board_photos as board

with tempfile.TemporaryDirectory() as directory:
 store.ROOT=Path(directory);study.ROOT=store.ROOT
 (store.ROOT/'recordings').mkdir();(store.ROOT/'analysis').mkdir()
 names=['lecture-2026-10-07-01-00-00-000001.wav','lecture-2026-10-07-01-00-00-000002.wav']
 for name in names:
  with wave.open(str(store.audio(name)) if (store.ROOT/'recordings'/name).exists() else str(store.ROOT/'recordings'/name),'wb') as out:
   out.setparams((1,2,16000,0,'NONE','none'));out.writeframes(b'\x7b\x00'*32000)
 status={'recording':False,'file':names[0],'seconds':2,'samples':32000,'files':names,'lessons':{},'ai':{'auto':False}}
 class Recorder(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   body=json.dumps(status).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
 recorder=ThreadingHTTPServer(('127.0.0.1',0),Recorder);threading.Thread(target=recorder.serve_forever,daemon=True).start()
 app=application.ApplicationServer(('127.0.0.1',0),'http://127.0.0.1:'+str(recorder.server_port));threading.Thread(target=app.serve_forever,daemon=True).start()
 base='http://127.0.0.1:'+str(app.server_port)
 def call(path,body=None,raw=False,origin=None):
  headers={'Content-Type':'application/json'}
  if origin:headers['Origin']=origin
  payload=body if raw else json.dumps(body).encode() if body is not None else None
  try:
   with urlopen(Request(base+path,data=payload,headers=headers),timeout=10) as response:return response.status,json.load(response)
  except HTTPError as error:return error.code,json.load(error)
 try:
  from unittest.mock import patch
  with patch.object(application,'DOWNLOADS',store.ROOT/'exports'):
   text='📚 Лекция\n\nПолный текст без обрезки.'
   code,exported=call('/telegram-export',{'file':names[0],'text':text});assert code==200
   assert (store.ROOT/'exports'/exported['filename']).read_text()==text
   assert call('/telegram-export',{'file':names[0],'text':text})[1]['filename']!=exported['filename']
   assert call('/telegram-export',{'file':names[0],'text':text},origin='https://evil.test')[0]==403
   assert call('/telegram-export',{'file':'../secret.wav','text':text})[0]==400
   assert call('/telegram-export',{'file':names[0],'text':''})[0]==400
  print('PASS: complete Telegram export, unique files, origin and path guards')
  with patch.object(board,'ROOT',store.ROOT):
   ident='a'*32;board.folder().mkdir(parents=True);board.image(ident).write_bytes(b'fixture')
   store.save(board.job_path(ident),{'id':ident,'captured_ms':1791817260000,'state':'queued'})
   assert call('/board-photos')[1]['photos'][0]['id']==ident
   assert call('/board-photo-assign',{'id':ident,'file':names[0],'start':1.5})[0]==200
   assert store.notes(names[0])['photos'][0]['start']==1.5
   assert call('/board-photo-assign',{'id':ident,'file':names[0],'start':3})[0]==400
   assert call('/board-photo-assign',{'id':'../secret','file':names[0]})[0]==400
   assert call('/board-photo-assign',{'id':ident,'file':'../secret.wav'})[0]==400
   assert call('/board-photo-assign',{'id':ident,'file':names[0]},origin='https://evil.test')[0]==403
   assert call('/board-photo-image/..%2Fsecret')[0]==400
  print('PASS: board inbox, manual placement, bounds, origin and path guards')

  assert call('/marker',{'file':names[0],'start':.5})[0]==200
  assert call('/marker',{'file':names[0],'start':.5},origin='https://evil.test')[0]==403
  assert call('/notes?file=..%2Fsecret.wav')[0]==400
  assert call('/photo?file='+names[0]+'&start=.8',b'\xff\xd8\xfffixture',True)[0]==200
  photo=store.notes(names[0])['photos'][-1]
  assert call('/photo-time',{'file':names[0],'id':photo['id'],'start':1.2})[0]==200
  assert call('/photo?file='+names[0]+'&start=0',b'<svg><script>bad</script></svg>',True)[0]==400
  assert call('/move',{'file':names[0],'folder':'Моя пара'})[0]==200
  code,data=call('/merge',{'files':names});assert code==200,(code,data)
  assert store.duration(data['file'])==4
  assert call('/status')[1]['lessons'][names[0]]['folder']=='Моя пара'
  status['recording']=True
  assert call('/merge',{'files':names})[0]==400
  study.recorder_status=lambda:status
  data=study.monitor_frame(0);assert data['to_frame']-data['from_frame']==16000
  store.save(store.ROOT/'study'/(Path(names[1]).stem+'.speakers.json'),{'segments':[{'start':0,'end':1,'speaker':0},{'start':1,'end':2,'speaker':1}]})
  output=study.speaker_track(names[1],0)
  import io
  with wave.open(io.BytesIO(output)) as wav:
   assert wav.getnframes()==32000;assert wav.readframes(16000)==b'\x7b\x00'*16000;assert wav.readframes(16000)==b'\0\0'*16000
  application.ROOT=store.ROOT
  sample={'moments':[{'kind':'date','date':'1380','title':'Куликовская битва','description':'Событие','quote':'В 1380 году была Куликовская битва.','start':10,'end':15,'segment_id':0,'image_query':'Куликовская битва'}]}
  sample['segments']=[{'id':0,'start':10,'end':15,'text':sample['moments'][0]['quote'],'reviewed':True}]
  store.save(store.ROOT/'analysis'/(Path(names[1]).stem+'.json'),sample)
  code,value=call('/learning-moments?file='+names[1]);assert code==200 and value['moments'][0]['date']=='1380'
  from unittest.mock import patch
  with patch.object(application.illustrations,'lookup',return_value={'status':'ready','license':'Public domain'}):
   assert call('/illustration?file='+names[1]+'&moment=0')[1]['status']=='ready'
  assert call('/illustration?file='+names[1]+'&moment=99')[0]==400
  store.save(store.ROOT/'study'/(Path(names[1]).stem+'.monitor-voices.json'),{'speakers':[{'id':0,'sample_start':0,'sample_end':2}]})
  sample=study.voice_sample(names[1],0,True)
  with wave.open(io.BytesIO(sample)) as wav:
   assert wav.getnframes()==32000 and wav.readframes(32000)==b'\x7b\x00'*32000
  try:study.voice_sample(names[1],99,True);raise AssertionError('unknown voice accepted')
  except ValueError:pass
  print('PASS: short speaker WAV and unknown voice rejection')
  print('PASS: dated moments and bounded illustration route')
  print('PASS: HTTP markers/photo time/folder/merge/origin/traversal; raw monitoring; synchronized speaker WAV')
 finally:
  app.shutdown();app.server_close();recorder.shutdown();recorder.server_close()
