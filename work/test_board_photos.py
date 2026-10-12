import hashlib,json,sys,tempfile,threading,unittest,wave
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import board_photos as board
import study_store as store
from board_match import locate,start_ms
from board_vision import clean
from PIL import Image
import io

ID='a'*32;CAPTURED=1791817260000;NAME=f'board-{CAPTURED}-{ID}.jpg'
image=io.BytesIO();Image.new('RGB',(120,80),'white').save(image,format='JPEG');PAYLOAD=image.getvalue();SHA=hashlib.sha256(PAYLOAD).hexdigest()

class BoardTests(unittest.TestCase):
 def test_clock_timezone_and_milliseconds(self):
  from datetime import datetime
  from zoneinfo import ZoneInfo
  expected=datetime(2026,10,12,16,20,59,tzinfo=ZoneInfo('Europe/Moscow')).timestamp()*1000+716
  self.assertEqual(start_ms('lecture-2026-10-12-16-20-59-716000.wav'),expected)
  self.assertEqual(start_ms('x.wav',{'started_ms':12}),12)
 def test_recording_identity_and_visible_content_refine_anchor(self):
  lecture={'file':'lecture-1.wav','duration':700,'started_ms':CAPTURED-300000,'segments':[{'start':50,'end':60,'text':'Начинаем обсуждать историю.'},{'start':170,'end':180,'text':'Найдем предел синуса трех икс.'},{'start':220,'end':230,'text':'Теперь новая тема о производной.'}]}
  photo={'captured_ms':CAPTURED,'source_recording':'lecture-1.wav','offset_seconds':190,'analysis':{'visible_text':r'Предел sin(3x)'}}
  match=locate(photo,[lecture]);self.assertEqual(match['file'],'lecture-1.wav');self.assertEqual(match['method'],'recording+content');self.assertEqual(match['start'],170)
 def test_clock_fallback_no_content_invention_or_cross_lecture_guess(self):
  lecture={'file':'lecture-1.wav','duration':700,'started_ms':CAPTURED-300000,'segments':[]}
  photo={'captured_ms':CAPTURED,'analysis':{'visible_text':'Неразборчивая доска'}}
  self.assertEqual(locate(photo,[lecture])['start'],300)
  self.assertIsNone(locate(photo,[lecture,dict(lecture,file='lecture-2.wav')]))
  self.assertIsNone(locate(dict(photo,captured_ms=CAPTURED+10000000),[lecture]))
 def test_visual_formula_safety_and_uncertainty(self):
  formulas=[{'latex':r'y=x^2','confidence':.95},{'latex':r'\href{https://x}{a}','confidence':1},{'latex':'{x','confidence':1},{'latex':'x=...','confidence':1},{'latex':'x=3','confidence':.4}]
  value=clean({'visible_text':'y=x²','formulas':formulas});self.assertEqual(value['formulas'],[{'latex':'y=x^2','confidence':.95,'source':'board-photo'}])
  self.assertEqual(clean({'formulas':[{'latex':r'\\frac{\\sin(3x)}{x}','confidence':.95}]})['formulas'][0]['latex'],r'\frac{\sin(3x)}{x}')
 def test_verified_import_ack_duplicate_and_conflict(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);item={'name':NAME,'bytes':len(PAYLOAD),'sha256':SHA,'kind':'board_photo','captured_ms':CAPTURED,'source_recording':'lecture-1.wav','offset_seconds':6}
   class Handler(BaseHTTPRequestHandler):
    ack=0
    def log_message(self,*a):pass
    def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(PAYLOAD)
    def do_POST(self):
     body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));assert body['sha256']==SHA
     assert board.image(ID,root).read_bytes()==PAYLOAD
     assert json.loads(board.job_path(ID,root).read_text())['captured_ms']==CAPTURED
     Handler.ack+=1;self.send_response(200);self.end_headers();self.wfile.write(b'{"ok":true}')
   server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
   try:
    base='http://127.0.0.1:'+str(server.server_port);board.import_one(item,base,'test',root);board.import_one(item,base,'test',root)
    self.assertEqual(Handler.ack,2);self.assertEqual(len(list(board.folder(root).glob('*.jpg'))),1)
    with self.assertRaises(ValueError):board.import_one(dict(item,sha256='f'*64),base,'test',root)
    self.assertEqual(Handler.ack,2)
    for change in [dict(name='../photo.jpg'),dict(bytes=True),dict(bytes=13*1024*1024),dict(sha256='bad')]:
     with self.assertRaises(ValueError):board.import_one(dict(item,**change),base,'test',root)
   finally:server.shutdown();server.server_close()
 def test_partial_or_corrupt_jpeg_is_not_acknowledged(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'bad.jpg'
   for data in [b'<svg>bad</svg>',PAYLOAD[:-20],b'\xff\xd8\xff\xd9']:
    path.write_bytes(data)
    with self.assertRaises(ValueError):board.validate_jpeg(path)
 def test_attach_repeatedly_and_manual_position_is_preserved(self):
  with tempfile.TemporaryDirectory() as directory,patch.object(board,'ROOT',Path(directory)),patch.object(store,'ROOT',Path(directory)):
   root=Path(directory);(root/'recordings').mkdir();name='lecture-1.wav'
   with wave.open(str(root/'recordings'/name),'wb') as audio:audio.setparams((1,2,16000,0,'NONE','none'));audio.writeframes(b'\0\0'*320000)
   board.folder().mkdir(parents=True);board.image(ID).write_bytes(PAYLOAD)
   job={'id':ID,'captured_ms':CAPTURED,'analysis':{'visible_text':'y=x²','formulas':[{'latex':'y=x^2'}]}}
   match={'file':name,'start':6,'method':'clock'};board.attach(job,match);board.attach(job,match)
   self.assertEqual(len(store.notes(name)['photos']),1);self.assertEqual(store.notes(name)['photos'][0]['analysis']['visible_text'],'y=x²')
   store.photo_time({'file':name,'id':ID+'.jpg','start':10});board.attach(job,dict(match,start=2,method='clock+content'))
   self.assertEqual(store.notes(name)['photos'][0]['start'],10);self.assertEqual(job['matching']['method'],'manual')

 def test_stale_inference_respects_new_manual_assignment(self):
  with tempfile.TemporaryDirectory() as directory,patch.object(board,'ROOT',Path(directory)),patch.object(store,'ROOT',Path(directory)):
   root=Path(directory);(root/'recordings').mkdir();name='lecture-1.wav'
   with wave.open(str(root/'recordings'/name),'wb') as audio:audio.setparams((1,2,16000,0,'NONE','none'));audio.writeframes(b'\0\0'*320000)
   board.folder().mkdir(parents=True);board.image(ID).write_bytes(PAYLOAD)
   old={'id':ID,'captured_ms':CAPTURED,'analysis':{}};board.attach(dict(old),{'file':name,'start':2,'method':'clock'})
   board.assign(ID,name,11);board.assign(ID,name,12)
   self.assertEqual(store.notes(name)['photos'][0]['start'],12)
   stale=dict(old,analysis={'visible_text':'y=x²'})
   board.save_job(stale);board.attach(stale,{'file':name,'start':3,'method':'clock+content'})
   self.assertEqual(store.notes(name)['photos'][0]['start'],12)
   self.assertEqual(store.notes(name)['photos'][0]['analysis']['visible_text'],'y=x²')

if __name__=='__main__':unittest.main()
