import hashlib
import hmac
import io
import json
import sys
import tempfile
import time
import threading
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import update_auth, update_manager, phone_sync, phone_updates

class Vault:
 def __init__(self):self.value={}
 def read(self):return dict(self.value)
 def write(self,value):self.value=dict(value)
 def delete(self):self.value={}

class Authentication(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  (self.root/'release.json').write_text(json.dumps({'updates':{'client_id':'public-fixture','repository_id':42}}))
  self.now=1000;self.vault=Vault();self.send=Mock()
  self.auth=update_auth.Authorization(self.root,self.vault,self.send,lambda:self.now)
 def tearDown(self):self.temp.cleanup()
 def begin(self):
  self.send.return_value=dict(device_code='secret-device',user_code='TEST-CODE',verification_uri='https://github.com/login/device',expires_in=900,interval=5)
  return self.auth.begin()
 def test_public_state_never_exposes_credentials(self):
  state=self.begin();self.assertEqual(state['user_code'],'TEST-CODE');self.assertNotIn('secret-device',json.dumps(state))
  self.send.return_value={'access_token':'secret-access','refresh_token':'secret-refresh','expires_in':28800}
  self.auth.poll();self.assertTrue(self.auth.public()['authorized'])
  self.assertNotIn('secret-',json.dumps(self.auth.public()));self.assertEqual(self.auth.token(),'secret-access')
  self.assertEqual(self.send.call_args.args[1]['repository_id'],42)
 def test_pending_and_slow_down_respect_intervals(self):
  self.begin();self.send.return_value={'error':'authorization_pending'};self.auth.poll();count=self.send.call_count
  self.auth.poll();self.assertEqual(self.send.call_count,count)
  self.now+=5;self.send.return_value={'error':'slow_down'};self.auth.poll()
  self.assertEqual(self.auth.pending['interval'],10);self.now+=5;self.auth.poll();self.assertEqual(self.send.call_count,count+1)
  self.now+=5;self.auth.poll();self.assertEqual(self.send.call_count,count+2)
 def test_expired_cancelled_and_denied_codes_do_not_authorize(self):
  self.begin();self.now+=901;self.auth.poll();self.assertFalse(self.auth.public()['pending']);self.assertFalse(self.vault.value)
  self.begin();self.auth.cancel();self.auth.poll();self.assertFalse(self.vault.value)
  self.begin();self.send.return_value={'error':'access_denied'};self.auth.poll();self.assertFalse(self.auth.public()['authorized'])
 def test_refresh_rotates_and_persists_without_client_secret(self):
  self.vault.value={'access_token':'old','refresh_token':'refresh','expires_at':1001,'refresh_expires_at':2000}
  self.send.return_value={'access_token':'new','refresh_token':'rotated','expires_in':28800}
  self.assertEqual(self.auth.token(),'new');self.assertEqual(self.vault.value['refresh_token'],'rotated')
  self.assertEqual(self.send.call_args.args[1],dict(client_id='public-fixture',grant_type='refresh_token',refresh_token='refresh'))
  self.auth.disconnect();self.assertFalse(self.auth.token());self.assertFalse(self.auth.public()['authorized'])
 def test_restart_reuses_keychain_and_shows_connected(self):
  self.vault.value={'access_token':'saved','expires_at':99999,'refresh_expires_at':999999}
  self.assertEqual(self.auth.token(),'saved');self.assertIn('подключён',self.auth.public()['message']);self.send.assert_not_called()
 def test_network_failure_does_not_lose_pending_login(self):
  self.begin();self.send.side_effect=OSError('sensitive remote details');self.auth.poll()
  self.assertTrue(self.auth.public()['pending']);self.assertNotIn('sensitive',self.auth.public()['message'])
 def test_untrusted_verification_url_rejected(self):
  self.send.return_value=dict(device_code='secret',user_code='code',verification_uri='https://evil.example')
  with self.assertRaises(ValueError):self.auth.begin()

class Transfer(unittest.TestCase):
 def test_streamed_apk_body_matches_signed_digest(self):
  data=b'APK-fixture\0'*100000;expected=hashlib.sha256(data).hexdigest();captured=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*_):pass
   def do_POST(self):
    size=int(self.headers['Content-Length']);body=self.rfile.read(size);digest=hashlib.sha256(body).hexdigest()
    canonical='\n'.join(('POST','/app-update',self.headers['X-Lecture-Time'],self.headers['X-Lecture-Nonce'],'',digest))
    valid=hmac.compare_digest(self.headers['X-Lecture-Signature'],hmac.new(b'fixture',canonical.encode(),hashlib.sha256).hexdigest())
    captured.append((body==data,valid,self.headers['X-Lecture-Body-SHA256']==digest,self.headers.get('Transfer-Encoding')))
    self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'sha256':digest}).encode())
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   with tempfile.TemporaryDirectory() as d:
    apk=Path(d)/'update.apk';apk.write_bytes(data)
    result=phone_sync.request_file('http://127.0.0.1:'+str(server.server_port),'fixture','/app-update',apk)
    self.assertEqual(result['sha256'],expected);self.assertEqual(captured,[(True,True,True,None)])
  finally:server.shutdown();server.server_close()
 def test_phone_skip_current_busy_rejected_and_already_received(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);folder=root/'updates/android';folder.mkdir(parents=True);data=b'fixture';sha=hashlib.sha256(data).hexdigest()
   (folder/'update.apk').write_bytes(data);(folder/'ready.json').write_text(json.dumps({'tag':'v0.5.1','digest':'sha256:'+sha}))
   for status in ({'installed_tag':'v0.5.1'},{'recording':True},{'sha256':sha},{'rejected_digest':sha}):
    phone_updates.LAST.clear()
    with patch.object(phone_sync,'request',return_value=io.BytesIO(json.dumps(status).encode())),patch.object(phone_sync,'request_file') as send:
     phone_updates.push('http://fixture','fixture',root);send.assert_not_called()
   phone_updates.LAST.clear()
   with patch.object(phone_sync,'request',return_value=io.BytesIO(b'{}')),patch.object(phone_sync,'request_file',return_value={'sha256':sha}) as send:
    phone_updates.push('http://fixture','fixture',root);phone_updates.push('http://fixture','fixture',root);self.assertEqual(send.call_count,1)
 def test_anonymous_private_check_requests_login(self):
  with patch.object(update_manager,'headers',return_value={}),patch.object(update_manager,'fetch') as fetch:
   update_manager.download_release();fetch.assert_not_called();self.assertIn('GitHub',update_manager.STATE['message'])

if __name__=='__main__':unittest.main()
