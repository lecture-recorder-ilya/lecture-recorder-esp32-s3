import contextlib
import hashlib
import hmac
import io
import json
import os
import struct
import sys
import tempfile
import time
import threading
import unittest
import zipfile
from pathlib import Path
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError
from unittest.mock import patch, Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'outputs/recorder'))
import update_auth, update_manager, phone_sync, phone_updates
from android_packages import ASSETS, PREVIEW, STABLE, apk_identity, cache_folder, installed_package


def apk_fixture(package=STABLE, code=12, utf8=False):
    strings = ('manifest', 'package', package, 'versionCode', 'http://schemas.android.com/apk/res/android')
    offsets, data = [], bytearray()
    for value in strings:
        offsets.append(len(data))
        if utf8:
            encoded = value.encode('utf-8')
            data.extend(bytes((len(value), len(encoded))) + encoded + b'\0')
        else:
            data.extend(struct.pack('<H', len(value)) + value.encode('utf-16le') + b'\0\0')
    data.extend(b'\0' * (-len(data) % 4))
    start = 28 + 4 * len(strings)
    pool = struct.pack('<HHIIIIII', 1, 28, start + len(data), len(strings), 0, 0x100 if utf8 else 0, start, 0)
    pool += struct.pack('<5I', *offsets) + data
    none = 0xffffffff
    attrs = struct.pack('<IIIHBBI', none, 1, 2, 8, 0, 3, 2)
    attrs += struct.pack('<IIIHBBI', 4, 3, none, 8, 0, 0x10, code)
    root = struct.pack('<HHIII', 0x102, 16, 36 + len(attrs), 1, none)
    root += struct.pack('<IIHHHHHH', none, 0, 20, 20, 2, 0, 0, 0) + attrs
    end = struct.pack('<HHIIIII', 0x103, 16, 24, 1, none, none, 0)
    manifest = struct.pack('<HHI', 3, 8, 8 + len(pool + root + end)) + pool + root + end
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as apk:
        apk.writestr('AndroidManifest.xml', manifest)
    return out.getvalue()

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
   root=Path(d);folder=root/'updates/android';folder.mkdir(parents=True);data=apk_fixture();sha=hashlib.sha256(data).hexdigest()
   (folder/'update.apk').write_bytes(data);(folder/'ready.json').write_text(json.dumps({'tag':'v0.5.1','digest':'sha256:'+sha}))
   for status in ({'installed_tag':'v0.5.1'},{'recording':True},{'sha256':sha},{'rejected_digest':sha}):
    phone_updates.LAST.clear()
    with patch.object(phone_sync,'request',return_value=io.BytesIO(json.dumps(status).encode())),patch.object(phone_sync,'request_file') as send:
     phone_updates.push('http://fixture','fixture',root);send.assert_not_called()
   phone_updates.LAST.clear()
   with patch.object(phone_sync,'request',return_value=io.BytesIO(b'{}')),patch.object(phone_sync,'request_file',return_value={'sha256':sha}) as send:
    phone_updates.push('http://fixture','fixture',root);phone_updates.push('http://fixture','fixture',root);self.assertEqual(send.call_count,1)


class ReleaseAccess(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.installed = dict(version='1.0', code=1, runtime=1, repository=update_manager.REPOSITORY)
        update_manager.atomic(self.project / 'release.json', self.installed)
        self.vault = Vault()
        self.auth = update_auth.Authorization(self.project, self.vault)
        fixtures = contextlib.ExitStack()
        self.addCleanup(fixtures.close)
        fixtures.enter_context(patch.object(update_manager, 'AUTH', self.auth))
        fixtures.enter_context(patch.object(update_manager, 'STATE', {}))
        fixtures.enter_context(patch.dict(os.environ, {'LECTURE_GITHUB_TOKEN': ''}))

    def release(self, runtime=1):
        package = io.BytesIO()
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('release.json', json.dumps(dict(self.installed, version='2.0', code=2, runtime=runtime)))
            for name in ('app_server', 'recorder', 'update_manager'):
                archive.writestr(f'outputs/recorder/{name}.py', 'installed = True\n')
        files = [(ASSETS[STABLE], apk_fixture()), (ASSETS[PREVIEW], apk_fixture(PREVIEW, 23)),
                 ('lecture-mac-update.zip', package.getvalue())]
        rows = [dict(name=name, id=index, size=len(data), digest='sha256:' + hashlib.sha256(data).hexdigest())
                for index, (name, data) in enumerate(files, 1)]
        return [json.dumps(dict(tag_name='v2.0', assets=rows)).encode()] + [data for _, data in files]

    def test_public_scheduler_stages_checked_zip_and_both_apks_without_keychain(self):
        bodies = self.release()
        fetch = Mock(side_effect=map(io.BytesIO, bodies))
        stop = threading.Event()
        intervals = []
        def tick(seconds):
            intervals.append(seconds)
            if len(intervals) == 2:
                stop.set()
        server = SimpleNamespace(service_url='', pairing=SimpleNamespace(public=lambda: {'active': True}))
        self.assertEqual(self.auth.public()['message'], '')
        with patch.object(self.vault, 'read', side_effect=AssertionError('Public check opened Keychain')) as keychain, \
             patch.object(update_manager, 'PROJECT', self.project), patch.object(update_manager, 'fetch', fetch), \
             patch.object(update_manager, 'download_release', partial(update_manager.download_release, self.project)), \
             patch.object(update_manager, 'CHECK', threading.Event()), patch.object(update_manager, 'STOP', stop), \
             patch.object(stop, 'wait', side_effect=tick), \
             patch.object(update_manager.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
            update_manager.start(server)
        keychain.assert_not_called()
        self.assertEqual(intervals, [10, 10])
        requests = [call.args[0] for call in fetch.call_args_list]
        self.assertEqual([req.full_url.rsplit('/', 1)[1] for req in requests], ['latest', '1', '2', '3'])
        self.assertTrue(all(req.get_header('Authorization') is None for req in requests))
        folder = self.project / 'work/updates'
        candidate = folder / 'candidate.zip'
        self.assertEqual(candidate.read_bytes(), bodies[-1])
        self.assertEqual(update_manager.read(folder / 'pending.json')['sha256'], hashlib.sha256(bodies[-1]).hexdigest())
        self.assertEqual(update_manager.inspect_package(candidate, self.project)[0]['code'], 2)
        for package, code in [(STABLE, 12), (PREVIEW, 23)]:
            cached = cache_folder(self.project / 'work', package)
            self.assertEqual(apk_identity(cached / 'update.apk'), (package, code))
            self.assertEqual(update_manager.read(cached / 'ready.json')['tag'], 'v2.0')
        self.assertIn('Обновление скачано', update_manager.STATE['message'])

    def test_private_check_requests_login_only_after_denial(self):
        for code in (401, 404):
            with self.subTest(code=code), \
                 patch.object(update_manager, 'fetch', side_effect=HTTPError('latest', code, 'denied', {}, None)) as fetch:
                self.assertIsNone(update_manager.download_release(self.project))
                self.assertEqual(fetch.call_count, 1)
                self.assertIsNone(fetch.call_args.args[0].get_header('Authorization'))
                self.assertIn('Войди в GitHub', update_manager.STATE['message'])
        self.assertFalse((self.project / 'work/updates/pending.json').exists())

    def test_private_check_restores_keychain_for_metadata_and_assets(self):
        for code in (401, 403, 404, 429):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                self.auth.credentials = None
                self.vault.value = {'access_token': 'fixture', 'expires_at': time.time() + 600}
                project = Path(folder)
                update_manager.atomic(project / 'release.json', self.installed)
                denied = HTTPError('latest', code, 'denied', {}, None)
                replies = [denied, *map(io.BytesIO, self.release())]
                with patch.object(update_manager, 'fetch', side_effect=replies) as fetch:
                    update_manager.download_release(project)
                requests = [call.args[0] for call in fetch.call_args_list]
                self.assertIsNone(requests[0].get_header('Authorization'))
                self.assertEqual([req.get_header('Authorization') for req in requests[1:]], ['Bearer fixture'] * 4)
                self.assertTrue((project / 'work/updates/pending.json').is_file())
        self.assertTrue(self.auth.public()['authorized'])

    def test_public_check_rejects_incompatible_package_before_staging(self):
        with patch.object(update_manager, 'fetch', side_effect=map(io.BytesIO, self.release(runtime=2))):
            with self.assertRaisesRegex(ValueError, 'Несовместимая'):
                update_manager.download_release(self.project)
        folder = self.project / 'work/updates'
        self.assertFalse((folder / 'candidate.zip').exists())
        self.assertFalse((folder / 'pending.json').exists())

    def test_rate_limit_without_credentials_waits_for_next_check(self):
        for code in (403, 429):
            error = HTTPError('latest', code, 'rate limit', {}, None)
            with self.subTest(code=code), patch.object(update_manager, 'fetch', side_effect=error) as fetch:
                update_manager.download_release(self.project)
                self.assertEqual(fetch.call_count, 1)
                self.assertIn('ограничил', update_manager.STATE['message'])
                self.assertNotIn('Войди', update_manager.STATE['message'])

class AndroidChannels(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.work = self.project / 'work'
        self.stable = apk_fixture()
        self.preview = apk_fixture(PREVIEW, 23, utf8=True)
        self.assets = {ASSETS[STABLE]: self.stable, ASSETS[PREVIEW]: self.preview}
        self.addCleanup(phone_updates.LAST.clear)

    def refresh(self, assets, tag='v0.5.5'):
        rows, bodies = [], {}
        for index, (name, body) in enumerate(assets.items(), 1):
            sha = hashlib.sha256(body).hexdigest()
            rows.append(dict(id=index, name=name, size=len(body), digest='sha256:' + sha))
            bodies[str(index)] = body
        def fetch(req, **kwargs):
            return io.BytesIO(bodies[req.full_url.rsplit('/', 1)[1]])
        with patch.object(update_manager, 'fetch', side_effect=fetch) as network:
            message = update_manager.cache_android(dict(assets=rows, tag_name=tag), self.project)
            return message, network.call_count

    def transfer(self, status):
        self.posted = []
        def respond(req, **kwargs):
            self.assertEqual(req.full_url, 'http://fixture/app-update')
            if req.get_method() == 'GET':
                return io.BytesIO(json.dumps(status).encode())
            body = req.data.read()
            self.posted.append(body)
            sha = hashlib.sha256(body).hexdigest()
            self.assertEqual(req.get_header('X-lecture-body-sha256'), sha)
            return io.BytesIO(json.dumps(dict(sha256=sha)).encode())
        phone_updates.LAST.clear()
        with patch.object(phone_sync, 'urlopen', side_effect=respond), patch.dict(phone_sync.state):
            phone_updates.push('http://fixture', 'fixture', self.work)
        return self.posted

    def test_matches_explicit_packages_and_known_legacy_builds(self):
        self.refresh(self.assets)
        for status, expected in [
            ({'installed_package': STABLE}, self.stable),
            ({'installed_package': PREVIEW}, self.preview),
            ({}, self.stable),
            ({'installed_tag': 'v0.5.3', 'installed_code': 10}, self.stable),
            ({'installed_tag': 'v0.5.4', 'installed_code': 11}, self.stable),
            ({'installed_tag': 'v0.5.4', 'installed_code': 22}, self.preview),
            ({'installed_tag': 'v0.5.3-ai.1', 'installed_code': 11}, self.preview),
            ({'installed_tag': 'v0.5.3-ai.11', 'installed_code': 21}, self.preview),
        ]:
            with self.subTest(status=status):
                self.assertEqual(self.transfer(status), [expected])
        self.assertEqual(installed_package(dict(installed_tag='v0.5.3-ai.1', installed_code=10)), STABLE)
        self.assertEqual(installed_package(dict(installed_package=STABLE, installed_tag='v0.5.4', installed_code=22)), STABLE)

    def test_newer_pending_release_and_running_analysis(self):
        self.refresh(self.assets)
        code = apk_identity(io.BytesIO(self.stable))[1]
        for pending in (code, code + 1):
            with self.subTest(pending=pending):
                self.assertEqual(self.transfer(dict(installed_package=STABLE, pending_code=pending)), [])
        self.assertEqual(self.transfer(dict(installed_package=STABLE, analyzing=True)), [])
        self.assertEqual(self.transfer(dict(installed_package=STABLE, pending_code=code - 1)), [self.stable])

    def test_unknown_explicit_package_never_falls_back(self):
        self.refresh(self.assets)
        for package in ('', None, [], STABLE + '.other', '../preview', STABLE.upper()):
            with self.subTest(package=package):
                self.assertEqual(self.transfer(dict(installed_package=package, installed_tag='v0.5.4', installed_code=22)), [])

    def test_stable_cache_from_old_mac_works_offline(self):
        folder = self.work / 'updates/android'
        folder.mkdir(parents=True)
        for body, expected in [(self.stable, [self.stable]), (self.preview, []), (b'bad APK', [])]:
            (folder / 'update.apk').write_bytes(body)
            sha = hashlib.sha256(body).hexdigest()
            (folder / 'ready.json').write_text(json.dumps(dict(tag='v0.5.5', digest='sha256:' + sha)))
            self.assertEqual(self.transfer({}), expected)
            self.assertEqual(self.transfer(dict(installed_package=PREVIEW)), [])

    def test_each_channel_retries_immediately_after_transport_failure(self):
        self.refresh(self.assets)
        for package, payload in ((STABLE, self.stable), (PREVIEW, self.preview)):
            for failed_at in ('status', 'upload'):
                with self.subTest(package=package, failed_at=failed_at):
                    endpoint = 'http://fixture'
                    digest = hashlib.sha256(payload).hexdigest()
                    def status():
                        return io.BytesIO(json.dumps(dict(installed_package=package)).encode())
                    gets = [ConnectionResetError(), status()] if failed_at == 'status' else [status(), status()]
                    uploads = [ConnectionResetError(), {'sha256': digest}] if failed_at == 'upload' else [{'sha256': digest}]
                    phone_updates.LAST.clear()
                    with patch.object(phone_sync, 'request', side_effect=gets) as get, \
                         patch.object(phone_sync, 'request_file', side_effect=uploads) as upload, \
                         patch.object(phone_updates.time, 'monotonic', return_value=100):
                        with self.assertRaises(ConnectionResetError):
                            phone_updates.push(endpoint, 'fixture', self.work)
                        phone_updates.push(endpoint, 'fixture', self.work)
                        phone_updates.push(endpoint, 'fixture', self.work)
                    self.assertEqual(get.call_count, 2)
                    self.assertEqual(upload.call_count, len(uploads))
                    self.assertEqual(upload.call_args.kwargs['expected_digest'], digest)

    def test_absent_channel_is_withdrawn_without_substitution(self):
        self.refresh(self.assets)
        self.refresh({ASSETS[STABLE]: self.stable})
        self.assertEqual(self.transfer(dict(installed_tag='v0.5.4', installed_code=22)), [])
        self.assertEqual(self.transfer(dict(installed_package=PREVIEW)), [])
        self.assertEqual(self.transfer({}), [self.stable])
        self.refresh({ASSETS[PREVIEW]: self.preview})
        self.assertEqual(self.transfer({}), [])
        self.assertEqual(self.transfer(dict(installed_package=PREVIEW)), [self.preview])

    def test_mislabeled_assets_never_replace_verified_apks(self):
        self.refresh({ASSETS[STABLE]: self.stable})
        message, _ = self.refresh({ASSETS[STABLE]: self.preview, ASSETS[PREVIEW]: self.stable}, tag='v0.5.6')
        self.assertIn(ASSETS[STABLE], message)
        self.assertIn(ASSETS[PREVIEW], message)
        self.assertEqual(self.transfer({}), [self.stable])
        self.assertEqual(self.transfer(dict(installed_package=PREVIEW)), [])
        stable = cache_folder(self.work, STABLE)
        self.assertEqual(json.loads((stable / 'ready.json').read_text())['tag'], 'v0.5.5')
        self.assertFalse((stable / 'candidate.apk').exists())

    def test_refresh_reuses_valid_files_and_repairs_corruption(self):
        self.assertEqual(self.refresh(self.assets)[1], 2)
        self.assertEqual(self.refresh(self.assets, tag='v0.5.6')[1], 0)
        for package, code in [(STABLE, 12), (PREVIEW, 23)]:
            folder = cache_folder(self.work, package)
            meta = json.loads((folder / 'ready.json').read_text())
            self.assertEqual((meta['package'], meta['code'], meta['tag']), (package, code, 'v0.5.6'))
            self.assertEqual(apk_identity(folder / 'update.apk'), (package, code))
        (cache_folder(self.work, PREVIEW) / 'update.apk').write_bytes(bytes(len(self.preview)))
        self.assertEqual(self.refresh(self.assets)[1], 1)
        self.assertEqual(self.transfer(dict(installed_package=PREVIEW)), [self.preview])

    def test_version_code_compared_with_actual_apk(self):
        self.refresh(self.assets)
        self.assertEqual(self.transfer(dict(installed_package=STABLE, installed_tag='v0.5.5', installed_code=11)), [self.stable])
        for code in (12, 13):
            self.assertEqual(self.transfer(dict(installed_package=STABLE, installed_code=code)), [])

    def test_replacement_between_selection_and_post_is_never_sent(self):
        self.refresh(self.assets)
        original = phone_sync.request_file
        def replace_file(base, token, route, path, **kwargs):
            path.write_bytes(self.preview)
            return original(base, token, route, path, **kwargs)
        with patch.object(phone_sync, 'request_file', side_effect=replace_file):
            with self.assertRaisesRegex(ValueError, 'APK в кэше изменился'):
                self.transfer(dict(installed_package=STABLE))
        self.assertEqual(self.posted, [])

    def test_interrupted_cache_publication_recovers_on_next_check(self):
        self.refresh({ASSETS[STABLE]: self.stable})
        newer = apk_fixture(STABLE, 13)
        assets = {ASSETS[STABLE]: newer}
        with patch.object(update_manager, 'atomic', side_effect=OSError('disk full')):
            self.assertIn(ASSETS[STABLE], self.refresh(assets, tag='v0.5.6')[0])
        with self.assertRaisesRegex(ValueError, 'APK в кэше изменился'):
            self.transfer({})
        self.assertEqual(self.posted, [])
        self.assertEqual(self.refresh(assets, tag='v0.5.6')[1], 0)
        self.assertEqual(self.transfer({}), [newer])

    def test_invalid_compiled_manifest_is_never_cached(self):
        with zipfile.ZipFile(io.BytesIO(self.stable)) as apk:
            valid = apk.read('AndroidManifest.xml')
        for manifest in (b'', b'<manifest package="ru.ilya.lecturerecorder"/>',
                         valid[:-1], valid[:12] + b'\0\0\0\0' + valid[16:]):
            body = io.BytesIO()
            with zipfile.ZipFile(body, 'w') as apk:
                apk.writestr('AndroidManifest.xml', manifest)
            self.assertIn(ASSETS[STABLE], self.refresh({ASSETS[STABLE]: body.getvalue()})[0])
            self.assertEqual(self.transfer({}), [])


if __name__=='__main__':unittest.main()
