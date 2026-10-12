import http.client
import json
import os
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import phone_pairing as pairing
import phone_sync


class PairingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.manager=pairing.Pairing(self.root,port=0,discovery_port=0);self.manager.name='Fixture Mac'
  self.initial=self.manager.start()
  self.context=ssl.create_default_context(cafile=str(self.manager.directory/'cert.pem'));self.context.check_hostname=False
  self.body={'name':'Fixture Android','device_id':'a'*32,'nonce':'b'*32}
 def tearDown(self):self.manager.close();self.tmp.cleanup()
 def post(self,route,body,headers=None,raw=None):
  data=json.dumps(body).encode() if raw is None else raw
  connection=http.client.HTTPSConnection('127.0.0.1',self.manager.server.server_port,context=self.context,timeout=4)
  connection.request('POST',route,body=data,headers=headers or {'Content-Type':'application/json'})
  response=connection.getresponse();result=response.status,json.loads(response.read());connection.close();return result
 def request(self):
  status,value=self.post('/pair/request',self.body);self.assertEqual(status,200);return value
 def test_no_credentials_before_explicit_mac_confirmation(self):
  value=self.request();status,result=self.post('/pair/status',{'request_id':value['request_id']})
  self.assertEqual(status,200);self.assertEqual(result['status'],'waiting');self.assertNotIn('sync_token',result)
  self.assertFalse(self.manager.config.exists());self.assertNotIn('token',json.dumps(self.manager.public()))
 def test_complete_pairing_saves_private_settings_and_optional_esp(self):
  pairing.save(self.root/'work/recorder-pairing.json',{'ip':'192.168.1.5','token':'esp-fixture','password':'not-for-phone'})
  value=self.request();self.manager.decide(value['request_id'],True)
  _,result=self.post('/pair/status',{'request_id':value['request_id']})
  config=pairing.read(self.manager.config);self.assertEqual(result['sync_token'],config['token'])
  self.assertEqual(config['address'],'127.0.0.1');self.assertEqual(config['device_id'],'a'*32)
  self.assertEqual(stat.S_IMODE(self.manager.config.stat().st_mode),0o600)
  self.assertEqual(result['esp'],{'ip':'192.168.1.5','token':'esp-fixture'})
  self.assertEqual(self.post('/pair/ack',{'request_id':value['request_id']})[0],200)
  self.assertEqual(self.manager.public()['pending']['state'],'complete')
 def test_cancel_and_reject_preserve_previous_pairing(self):
  pairing.save(self.manager.config,{'token':'old-fixture','name':'Old phone'})
  value=self.request();self.assertEqual(self.post('/pair/cancel',{'request_id':value['request_id']})[0],200)
  self.assertEqual(self.post('/pair/status',{'request_id':value['request_id']})[0],403)
  self.assertEqual(pairing.read(self.manager.config)['token'],'old-fixture')
  value=self.request();self.manager.decide(value['request_id'],False)
  self.assertIsNone(self.manager.public()['pending']);self.assertEqual(pairing.read(self.manager.config)['token'],'old-fixture')
 def test_retries_are_idempotent_and_second_phone_cannot_replace_pending(self):
  value=self.request();self.assertEqual(self.request(),value)
  status,_=self.post('/pair/request',dict(self.body,nonce='c'*32));self.assertEqual(status,409)
  with self.assertRaises(pairing.PairingError):self.manager.decide('stale',True)
  self.manager.decide(value['request_id'],True);token=pairing.read(self.manager.config)['token']
  self.manager.decide(value['request_id'],True);self.assertEqual(pairing.read(self.manager.config)['token'],token)
 def test_expiry_cannot_release_credentials(self):
  value=self.request();self.manager.deadline=0
  with self.assertRaises(pairing.PairingError) as error:self.manager.remote('/pair/status',{'request_id':value['request_id']},'127.0.0.1')
  self.assertEqual(error.exception.status,410);self.assertFalse(self.manager.public()['active'])
 def test_hostile_origins_invalid_bodies_and_unknown_requests_are_rejected(self):
  self.assertEqual(self.post('/pair/request',self.body,{'Origin':'https://example.com'})[0],403)
  self.assertEqual(self.post('/pair/request',{},raw=b'[]')[0],400)
  self.assertEqual(self.post('/pair/request',{},raw=b'{')[0],400)
  self.assertEqual(self.post('/pair/request',dict(self.body,name='bad\nname'))[0],400)
  self.assertEqual(self.post('/pair/status',{'request_id':'unknown'})[0],404)
  self.assertEqual(self.post('/pair/request',{},raw=b'x'*2049)[0],413)
 def test_discovery_returns_only_public_identity(self):
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
   udp.settimeout(2);nonce='c'*32;udp.sendto(('LECTUREPAIR1 '+nonce).encode(),('127.0.0.1',self.manager.discovery.getsockname()[1]))
   data,_=udp.recvfrom(1024);value=json.loads(data)
  self.assertEqual(value,{'protocol':'LECTUREPAIR1','nonce':nonce,'name':'Fixture Mac','port':self.manager.server.server_port})
 def test_close_removes_temporary_key_and_new_session_changes_code(self):
  folder=self.manager.directory;old=self.initial['code'];self.manager.close()
  self.assertFalse(folder.exists());self.assertFalse(self.manager.public()['active'])
  self.assertNotEqual(self.manager.start()['code'],old)
 def test_forget_revokes_sync_and_preserves_audio(self):
  value=self.request();self.manager.decide(value['request_id'],True);token=pairing.read(self.manager.config)['token']
  audio=self.root/'lecture.wav';audio.write_bytes(b'fixture audio');self.manager.forget()
  self.assertFalse(self.manager.config.exists());self.assertEqual(audio.read_bytes(),b'fixture audio')
  with patch.object(phone_sync,'urlopen') as remote,self.assertRaises(PermissionError):phone_sync.request('http://phone',token,'/ack',{})
  remote.assert_not_called()
 def test_confirmed_pair_survives_session_close(self):
  value=self.request();self.manager.decide(value['request_id'],True);self.manager.close()
  self.assertTrue(self.manager.public()['paired']);self.assertEqual(self.manager.public()['phone_name'],'Fixture Android')


class PairingHttpTests(unittest.TestCase):
 def test_local_controls_require_local_host_and_reject_other_origins(self):
  import app_server
  with tempfile.TemporaryDirectory() as tmp,patch.object(app_server,'PROJECT',Path(tmp)):
   server=app_server.ApplicationServer(('127.0.0.1',0),'http://127.0.0.1:1');server.pairing.port=0;server.pairing.discovery_port=0
   threading.Thread(target=server.serve_forever,daemon=True).start()
   def request(method,path,headers=None):
    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4);connection.request(method,path,body=b'{}' if method=='POST' else None,headers=headers or {})
    response=connection.getresponse();status,value=response.status,json.loads(response.read());connection.close();return status,value
   try:
    self.assertEqual(request('POST','/phone-pairing/start',{'Origin':'https://example.com'})[0],403)
    self.assertEqual(request('POST','/phone-pairing/start',{'Host':'attacker.example'})[0],403)
    self.assertEqual(request('GET','/phone-pairing',{'Host':'attacker.example'})[0],403)
    status,value=request('POST','/phone-pairing/start');self.assertEqual(status,200);self.assertTrue(value['active'])
    self.assertEqual(request('POST','/reload-app')[0],409);self.assertFalse(server.reload_requested.is_set())
    status,value=request('POST','/phone-pairing/cancel');self.assertEqual(status,200);self.assertFalse(value['active'])
    server.reload_requested.set();self.assertEqual(request('POST','/phone-pairing/start')[0],409)
   finally:server.shutdown();server.server_close()


class UsbTests(unittest.TestCase):
 def test_usb_auto_selects_only_phone_accepting_signed_request(self):
  calls=[]
  def command(args,**kwargs):
   calls.append(args)
   return subprocess.CompletedProcess(args,0,stdout=b'List of devices attached\nwrong\tdevice\nright\tdevice\n',stderr=b'')
  import io
  with patch.object(phone_sync.shutil,'which',return_value='/fixture/adb'),patch.object(phone_sync.Path,'exists',return_value=True),patch.object(phone_sync.subprocess,'run',side_effect=command),patch.object(phone_sync,'request',side_effect=[HTTPError('fixture',403,'forbidden',{},None),io.BytesIO(b'[]')]):
   self.assertEqual(next(phone_sync.candidates({'token':'fixture'})),('http://127.0.0.1:8781','USB'))
  self.assertTrue(any('right' in args for args in calls));self.assertFalse(any('shell' in args for args in calls))
 def test_usb_probe_never_sends_plaintext_key(self):
  with patch.object(phone_sync,'urlopen') as remote:
   phone_sync.request('http://127.0.0.1:8781','fixture-key','/list')
   self.assertNotIn('Authorization',remote.call_args.args[0].headers)


class AndroidProtocolTests(unittest.TestCase):
 setUp=PairingTests.setUp
 tearDown=PairingTests.tearDown
 @classmethod
 def setUpClass(cls):
  java_home=os.environ.get('JAVA_HOME');cls.javac=Path(java_home)/'bin/javac' if java_home else Path(shutil.which('javac') or '/missing')
  cls.java=cls.javac.with_name('java')
  if subprocess.run([str(cls.javac),'-version'],capture_output=True).returncode:raise unittest.SkipTest('JDK required for Android protocol test')
  cls.classes=tempfile.TemporaryDirectory();root=Path(cls.classes.name)
  harness=root/'PairingHarness.java';harness.write_text('''package ru.ilya.lecturerecorder;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
public class PairingHarness {
 public static void main(String[] args)throws Exception {
  if(args[0].equals("code")){System.out.print(PairingProtocol.certificateCode(Files.readAllBytes(Paths.get(args[1]))));return;}
  System.out.print(PairingProtocol.post("127.0.0.1",Integer.parseInt(args[0]),args[1],args[2],new String(Files.readAllBytes(Paths.get(args[3])),StandardCharsets.UTF_8)));
 }
}''')
  protocol=Path('outputs/android/src/ru/ilya/lecturerecorder/PairingProtocol.java')
  subprocess.run([str(cls.javac),'-encoding','UTF-8','-d',str(root),str(protocol),str(harness)],check=True,capture_output=True)
 @classmethod
 def tearDownClass(cls):cls.classes.cleanup()
 def java_call(self,code,route,body):
  path=self.root/'request.json';path.write_text(json.dumps(body))
  return subprocess.run([str(self.java),'-cp',self.classes.name,'ru.ilya.lecturerecorder.PairingHarness',str(self.manager.server.server_port),code,route,str(path)],capture_output=True,text=True,timeout=15)
 def test_android_pinning_matches_mac_code_and_rejects_wrong_code(self):
  wrong='A'*12 if self.initial['code']!='A'*12 else 'B'*12
  result=self.java_call(wrong,'/pair/request',self.body);self.assertNotEqual(result.returncode,0);self.assertIsNone(self.manager.pending)
  result=self.java_call(self.initial['code'],'/pair/request',self.body);self.assertEqual(result.returncode,0,result.stderr)
  self.assertIn('request_id',json.loads(result.stdout))
 def test_android_protocol_completes_real_tls_exchange(self):
  result=self.java_call(self.initial['code'],'/pair/request',self.body);self.assertEqual(result.returncode,0,result.stderr);value=json.loads(result.stdout)
  waiting=self.java_call(self.initial['code'],'/pair/status',{'request_id':value['request_id']});self.assertNotIn('sync_token',json.loads(waiting.stdout))
  self.manager.decide(value['request_id'],True)
  approved=self.java_call(self.initial['code'],'/pair/status',{'request_id':value['request_id']});self.assertEqual(json.loads(approved.stdout)['sync_token'],pairing.read(self.manager.config)['token'])
  ack=self.java_call(self.initial['code'],'/pair/ack',{'request_id':value['request_id']});self.assertTrue(json.loads(ack.stdout)['ok'])


if __name__=='__main__':unittest.main()
