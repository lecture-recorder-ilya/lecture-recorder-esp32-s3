import errno
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
import phone_sync as sync
import phone_updates
import update_manager


class OfflineDiagnostics(unittest.TestCase):
    def setUp(self):
        scope = self.enterContext(ExitStack())
        work = Path(scope.enter_context(tempfile.TemporaryDirectory()))
        self.work = work
        for key, value in dict(WORK=work, CONFIG=work/'phone-sync.json', STATUS=work/'status.json',
                               LEDGER=work/'ledger.json', FILES=work/'recordings', worker_owns_status=False,
                               WAKE=threading.Event(), state={'connected':False,'imported':0}).items():
            scope.enter_context(patch.object(sync, key, value))
        with patch.object(update_manager, 'recover'):
            import app_server
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app_server.Handler)
        self.server.service_url = 'http://127.0.0.1:1'
        self.addCleanup(self.server.server_close)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.fixture = 'synthetic-secret-not-for-diagnostics'

    def http(self, method, path, **headers):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            conn.request(method, path, body=b'{}' if method=='POST' else None, headers=headers)
            reply = conn.getresponse()
            body = reply.read().decode()
            self.assertNotIn(self.fixture, body)
            return reply.status,json.loads(body)
        finally:
            conn.close()

    def pair(self):
        sync.CONFIG.write_text(json.dumps({'token': self.fixture}))

    def test_offline_endpoint_and_legacy_untrusted_status(self):
        code, info = self.http('GET','/phone-sync')
        self.assertEqual(code,200)
        self.assertFalse(info['can_retry'])
        self.assertIsNone(info['last_attempt'])
        self.assertIsNone(info['pending'])
        self.pair()
        sync.STATUS.write_text(json.dumps(dict(connected=False,pending=0,token=self.fixture,
                                    update_message=self.fixture, errors=[self.fixture], message=self.fixture)))
        _, info = self.http('GET','/phone-sync')
        self.assertIsNone(info['pending'])
        self.assertEqual(info['update_message'],'')
        self.assertEqual(self.http('GET','/phone-sync',Host='other.invalid')[0],403)
        self.assertEqual(self.http('POST','/phone-sync/retry',Origin='https://other.invalid')[0],403)
        self.assertEqual(self.http('POST','/phone-sync/retry',Host='other.invalid')[0],403)
        self.assertFalse(sync.WAKE.is_set())
        with patch.object(sync, 'profile_stamp', side_effect=PermissionError(self.fixture)):
            self.assertEqual(self.http('GET','/phone-sync')[0],503)
            self.assertEqual(self.http('POST','/phone-sync/retry')[0],503)

    def test_manual_retry_recovers_before_backoff_and_offline_queue_survives_restart(self):
        self.pair()
        item={'name':'lecture-2026-11-22-22-00-00.wav','sha256':'a'*64}
        retries = sync.RetryQueue()
        def listing(*args):
            return io.BytesIO(json.dumps([item]).encode())
        with patch.object(sync,'queue_pending'), patch('phone_notes.push'), patch('phone_updates.push'), \
             patch.object(sync,'candidates',return_value=[('local','USB')]), patch.object(sync,'request',side_effect=listing), \
             patch.object(sync,'import_one',side_effect=[OSError(errno.ENOSPC,self.fixture),item['name']]) as transfer, \
             patch.object(sync.time,'monotonic',return_value=100):
            sync.poll(retries)
            _, info=self.http('GET','/phone-sync')
            self.assertEqual((info['pending'],info['failed']), (1,1))
            self.assertIn('места',info['reason'])
            self.assertGreater(info['last_attempt'],0)
            self.assertNotIn(self.fixture,sync.STATUS.read_text())
            with patch.object(sync,'request',side_effect=URLError(self.fixture)):
                sync.poll(retries)
            _, offline=self.http('GET','/phone-sync')
            self.assertFalse(offline['connected'])
            self.assertEqual(offline['pending'],1)
            self.assertIn('недоступен',offline['reason'])
            sync.poll(retries)
            transfer.assert_called_once()
            code, requested=self.http('POST','/phone-sync/retry')
            self.assertEqual(code,202)
            self.assertTrue(requested['retry_accepted'] and requested['retry_requested'] and sync.WAKE.is_set())
            sync.poll(retries)
            _, done=self.http('GET','/phone-sync')
            self.assertEqual(transfer.call_count,2)
            self.assertEqual((done['pending'],done['failed'],done['retry_requested']),(0,0,False))
            self.assertIn('перенесено',done['reason'])
            self.assertNotIn(self.fixture,sync.STATUS.read_text())

    def test_auth_error_and_remote_update_text_remain_private(self):
        self.pair()
        unauthorized=HTTPError('http://example.invalid/'+self.fixture,403,self.fixture,{},None)
        with patch.object(sync,'queue_pending'), patch.object(sync,'candidates',return_value=[('local','USB')]), \
             patch.object(sync,'request',side_effect=unauthorized):
            sync.poll(sync.RetryQueue())
        _,info=self.http('GET','/phone-sync')
        self.assertIn('сопряжение',info['reason'])
        self.assertNotIn(self.fixture,sync.STATUS.read_text())
        for remote,expected in (({'sha256':'d'*64},'staged'),({'rejected_digest':'d'*64},'rejected')):
            remote.update(message='Bearer '+self.fixture,installed_code=1)
            with patch.object(phone_updates.Path,'is_file',return_value=True), \
                 patch.object(phone_updates,'cached_update',return_value=(None,'d'*64,2,'vqa')), \
                 patch.object(sync,'request',return_value=io.BytesIO(json.dumps(remote).encode())):
                phone_updates.check_phone('local','fixture',self.work)
                sync.save_status()
                self.assertEqual(sync.status()['update_message'],phone_updates.MESSAGES[expected])
                self.assertNotIn(self.fixture,sync.STATUS.read_text())

    def test_pair_replacement_and_unreadable_status(self):
        self.pair()
        sync.STATUS.write_text(json.dumps(dict(profile_stamp=1,connected=True,pending=7,listed=True,last_attempt=100)))
        self.assertIsNone(sync.status()['pending'])
        for raw in ('[1]', '{', 'null'):
            sync.STATUS.write_text(raw)
            self.assertIsNone(sync.status()['last_attempt'])
        sync.CONFIG.unlink()
        _,info=self.http('POST','/phone-sync/retry')
        self.assertFalse(info['can_retry'] or info['retry_requested'])


if __name__ == '__main__':
    unittest.main()
