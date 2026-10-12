import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
sys.path.insert(0,str(Path('outputs/recorder').resolve()))
import phone_sync


class SyncTests(unittest.TestCase):
 def setUp(self):
  self.first={'name':'lecture-2026-10-12-10-00-00.wav','sha256':'a'*64,'bytes':32044}
  self.second=dict(self.first,name='lecture-2026-10-12-11-00-00.wav',sha256='b'*64)
  self.retries=phone_sync.RetryQueue();phone_sync.state.update(imported=0)
 def cycle(self,items,importer,now=0):
  with patch.object(phone_sync,'candidates',return_value=[('http://phone','Wi-Fi')]),patch.object(phone_sync,'request',side_effect=lambda *_:io.BytesIO(json.dumps(items).encode())),patch.object(phone_sync,'import_one',side_effect=importer),patch.object(phone_sync,'atomic'),patch('phone_notes.push',return_value=0) as notes:
   result=phone_sync.sync_once({'token':'fixture'},self.retries,now)
  return result,notes.call_count
 def test_bad_file_does_not_block_other_audio_or_text(self):
  copied=[]
  def transfer(item,*_):
   if item==self.first:raise ValueError('Конфликт имени')
   copied.append(item['name'])
  result,notes=self.cycle([self.first,self.second],transfer)
  self.assertTrue(result);self.assertEqual(copied,[self.second['name']]);self.assertEqual(notes,2)
  self.assertEqual(phone_sync.state['pending'],1);self.assertEqual(phone_sync.state['failed'],1)
 def test_retry_delays_then_recovers_without_losing_file(self):
  self.cycle([self.first],lambda *_:(_ for _ in ()).throw(ValueError('fixture')),100)
  with patch.object(phone_sync,'import_one') as transfer:
   self.cycle([self.first],transfer,109);transfer.assert_not_called()
   self.cycle([self.first],transfer,110);transfer.assert_called_once()
  self.assertFalse(self.retries.entries);self.assertEqual(phone_sync.state['pending'],0)
 def test_changed_file_bypasses_previous_backoff(self):
  self.retries.failed(self.first,ValueError('fixture'),100)
  changed=dict(self.first,sha256='c'*64);copied=[]
  self.cycle([changed],lambda item,*_:copied.append(item),101)
  self.assertEqual(copied,[changed]);self.assertFalse(self.retries.entries)
 def test_connection_failure_tries_next_transport_immediately(self):
  with patch.object(phone_sync,'candidates',return_value=[('http://usb','USB'),('http://wifi','Wi-Fi')]),patch.object(phone_sync,'request',side_effect=lambda *_:io.BytesIO(json.dumps([self.first]).encode())),patch.object(phone_sync,'import_one',side_effect=[URLError('disconnected'),self.first['name']]) as transfer,patch.object(phone_sync,'atomic'),patch('phone_notes.push',return_value=0):
   self.assertTrue(phone_sync.sync_once({'token':'fixture'},self.retries,0))
  self.assertEqual(transfer.call_count,2);self.assertEqual(phone_sync.state['transport'],'Wi-Fi');self.assertFalse(self.retries.entries)
 def test_wifi_does_not_require_usb_serial(self):
  with patch.object(phone_sync.Path,'exists',return_value=False),patch.object(phone_sync,'discover_wifi',return_value='http://phone'),patch.object(phone_sync.subprocess,'run') as command:
   self.assertEqual(next(phone_sync.candidates({'token':'fixture'})),('http://phone','Wi-Fi'))
   command.assert_not_called()
 def test_retry_delay_is_bounded_and_stale_errors_are_removed(self):
  for _ in range(20):self.retries.failed(self.first,ValueError('fixture'),100)
  self.assertEqual(self.retries.entries[self.retries.key(self.first)]['after'],400)
  self.retries.retain([]);self.assertFalse(self.retries.entries)


if __name__=='__main__':unittest.main()
