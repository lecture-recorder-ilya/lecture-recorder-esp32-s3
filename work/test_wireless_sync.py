import unittest,sys,json,hashlib,hmac
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('work').resolve()))
from test_phone_sync import Tests,H,PAYLOAD,SHA,NAME
import phone_sync
class WirelessTests(Tests):
 def test_resume_partial_copy_ignoring_range_is_safe(self):
  part=self.files/(NAME+'.phone-part');part.write_bytes(PAYLOAD[:1000]);phone_sync.atomic(self.files/(NAME+'.phone-part.json'),{'bytes':len(PAYLOAD),'sha256':SHA})
  self.run_import();self.assertEqual(phone_sync.digest(self.files/NAME),SHA);self.assertEqual(H.ack,1)
 def test_other_partial_identity_is_discarded(self):
  (self.files/(NAME+'.phone-part')).write_bytes(b'wrong old bytes');phone_sync.atomic(self.files/(NAME+'.phone-part.json'),{'bytes':999,'sha256':'f'*64})
  self.run_import();self.assertEqual(phone_sync.digest(self.files/NAME),SHA)
 def test_signed_request_binds_path_body_and_range(self):
  with patch('phone_sync.time.time',return_value=1234567890),patch('phone_sync.secrets.token_hex',return_value='a'*32):
   headers=phone_sync.auth_headers('key','POST','/ack',b'body',{'Range':'bytes=1000-'})
  canonical='POST\n/ack\n1234567890\n'+'a'*32+'\nbytes=1000-\n'+hashlib.sha256(b'body').hexdigest()
  self.assertEqual(headers['X-Lecture-Signature'],hmac.new(b'key',canonical.encode(),hashlib.sha256).hexdigest());self.assertNotIn('Authorization',headers)
if __name__=='__main__':unittest.main()
