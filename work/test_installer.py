import fcntl
import hashlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('installer', ROOT / 'installer/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        installer.CANCEL.clear()

    def tearDown(self):
        installer.CANCEL.clear()
        self.temporary.cleanup()

    def archive(self, entries):
        path = self.root / 'payload.zip'
        with zipfile.ZipFile(path, 'w') as bundle:
            for name, content in entries:
                bundle.writestr(name, content)
        return path

    def resources(self):
        resources = self.root / 'resources'
        resources.mkdir()
        (resources / 'python/bin').mkdir(parents=True)
        (resources / 'python/bin/python3.12').write_bytes(b'python fixture')
        (resources / 'uv').write_bytes(b'uv fixture')
        archive = self.archive([('release.json', '{"code":5}'),
                                ('outputs/recorder/app_server.py', 'new source'),
                                ('outputs/Запись лекций.app/Contents/Info.plist', 'fixture')])
        (resources / 'payload.zip').write_bytes(archive.read_bytes())
        for mode in ('recorder', 'ai', 'vision'):
            (resources / ('requirements-' + mode + '.lock')).write_text('fixture==1\n')
        metadata = dict(code=5, version='0.4.0', python_version='3.12.12', required_free_bytes=1,
                        files={p.name: installer.digest(p) for p in resources.iterdir() if p.is_file()})
        installer.atomic(resources / 'manifest.json', metadata)
        return resources

    def test_payload_preserves_audio_private_settings_and_other_files(self):
        root = self.root / 'project'
        for name in ('outputs/recorder/recordings/lecture.wav', 'outputs/recorder/schedule.json',
                     'work/phone-sync.json', 'outputs/recorder/analysis/lecture.json'):
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'private fixture')
        archive = self.archive([('outputs/recorder/app_server.py', 'new source'), ('release.json', '{"code":5}')])
        installer.install_payload(archive, root)
        self.assertEqual((root / 'outputs/recorder/app_server.py').read_text(), 'new source')
        self.assertEqual((root / 'outputs/recorder/recordings/lecture.wav').read_bytes(), b'private fixture')
        self.assertEqual((root / 'work/phone-sync.json').read_bytes(), b'private fixture')
        self.assertEqual((root / 'outputs/recorder/schedule.json').read_bytes(), b'private fixture')
        self.assertEqual((root / 'outputs/recorder/analysis/lecture.json').read_bytes(), b'private fixture')

    def test_invalid_package_is_rejected_before_any_replacement(self):
        root = self.root / 'project'
        root.mkdir()
        (root / 'release.json').write_text('old source')
        for name in ('../escape.py', '/absolute.py', 'outputs/recorder/schedule.json',
                     'work/config.json', 'outputs/recorder/vendor/../escape.py', 'outputs//recorder/test.py'):
            with self.subTest(name=name):
                archive = self.archive([('release.json', 'new source'), (name, 'bad')])
                with self.assertRaises(installer.InstallError):
                    installer.install_payload(archive, root)
                self.assertEqual((root / 'release.json').read_text(), 'old source')

    def test_duplicate_paths_and_archive_symlinks_are_rejected(self):
        root = self.root / 'project'
        duplicate = self.archive([('release.json', 'first'), ('release.json', 'second')])
        with self.assertRaises(installer.InstallError):
            installer.install_payload(duplicate, root)
        link = zipfile.ZipInfo('outputs/recorder/app_server.py')
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        with zipfile.ZipFile(duplicate, 'w') as bundle:
            bundle.writestr(link, '../../private')
        with self.assertRaises(installer.InstallError):
            installer.install_payload(duplicate, root)

    def test_existing_symlink_cannot_redirect_installation(self):
        root = self.root / 'project'
        (root / 'outputs').mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        (root / 'outputs/recorder').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(installer.InstallError):
            installer.install_payload(self.archive([('outputs/recorder/app_server.py', 'bad')]), root)
        self.assertFalse((outside / 'app_server.py').exists())

    def test_atomic_state_is_private_and_leaves_no_temporary_file(self):
        path = self.root / 'state.json'
        installer.atomic(path, {'status': 'first'})
        installer.atomic(path, {'status': 'complete'})
        self.assertEqual(installer.read(path)['status'], 'complete')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_shortcut_preserves_foreign_application(self):
        applications = self.root / 'Applications'
        applications.mkdir()
        foreign = applications / 'Коса.app'
        foreign.mkdir()
        (foreign / 'fixture').write_text('keep')
        target = self.root / 'project/outputs/Запись лекций.app'
        target.mkdir(parents=True)
        result = installer.install_shortcut(self.root / 'project', applications)
        self.assertEqual(result.resolve(), target.resolve())
        self.assertEqual(result.name, 'Коса — локальная.app')
        self.assertEqual((foreign / 'fixture').read_text(), 'keep')
        self.assertEqual(installer.install_shortcut(self.root / 'project', applications), result)

    def test_existing_shortcut_still_opens_same_library(self):
        from app_shortcut import refresh_installed_shortcut
        project = self.root / 'Library/Application Support/Lecture Recorder/project'
        target = project / 'outputs/Запись лекций.app'
        target.mkdir(parents=True)
        applications = self.root / 'Applications'
        applications.mkdir()
        old = applications / 'Диктофон.app'
        old.symlink_to(target)
        alternate = applications / 'На полях.app'
        alternate.symlink_to(self.root / 'другое приложение.app')
        with patch.object(Path, 'home', return_value=self.root):
            refresh_installed_shortcut(self.root / 'test-checkout')
            self.assertEqual(set(applications.iterdir()), {old, alternate})
            refresh_installed_shortcut(project)
            refresh_installed_shortcut(project)
        self.assertTrue(old.samefile(applications / 'Коса.app'))
        self.assertEqual(alternate.readlink(), self.root / 'другое приложение.app')
        self.assertEqual(len(list(applications.iterdir())), 3)

    def test_packaged_installer_starts_in_isolated_python(self):
        for source in (ROOT / 'installer/install.py', ROOT / 'outputs/recorder/app_shortcut.py'):
            shutil.copyfile(source, self.root / source.name)
        result = subprocess.run([sys.executable, '-I', '-B', str(self.root / 'install.py'), '--help'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_both_shortcut_names_taken_opens_installed_bundle(self):
        applications = self.root / 'Applications'
        applications.mkdir()
        project = self.root / 'project'
        target = project / 'outputs/Запись лекций.app'
        target.mkdir(parents=True)
        foreign = applications / 'Коса.app'
        foreign.symlink_to(self.root / 'missing.app')
        (applications / 'Коса — локальная.app').mkdir()
        self.assertEqual(installer.install_shortcut(project, applications), target)
        self.assertFalse(foreign.exists())
        self.assertTrue(foreign.is_symlink())
        legacy = applications / 'Диктофон.app'
        legacy.symlink_to(target)
        self.assertEqual(installer.install_shortcut(project, applications), legacy)

    def test_parallel_shortcut_refresh_creates_one_link(self):
        applications = self.root / 'Applications'
        project = self.root / 'project'
        target = project / 'outputs/Запись лекций.app'
        target.mkdir(parents=True)
        gate = threading.Barrier(8)

        def refresh(_):
            gate.wait(timeout=10)
            return installer.install_shortcut(project, applications)

        with ThreadPoolExecutor(max_workers=8) as workers:
            links = set(workers.map(refresh, range(8)))
        self.assertEqual(links, {applications / 'Коса.app'})
        self.assertEqual(set(applications.iterdir()), links)
        self.assertTrue((applications / 'Коса.app').samefile(target))

    def test_complete_state_requires_all_verifications_and_retry_preserves_data(self):
        resources = self.resources()
        support = self.root / 'support'
        audio = support / 'project/outputs/recorder/recordings/lecture.wav'
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b'audio fixture')
        commands = []
        def command(args, *unused):
            commands.append(args)
            if 'venv' in args:
                path = Path(args[-1]) / 'bin/python'
                path.parent.mkdir(parents=True)
                path.write_bytes(b'python fixture')
            if 'verify.py' in str(args) and 'vision' in args and len(commands) < 20:
                raise installer.InstallError('verification failed')
        with patch.object(installer, 'run', side_effect=command), patch.object(installer, 'download_models'), \
                patch.object(installer, 'stop_managed_services'), patch.object(installer, 'emit'):
            with self.assertRaises(installer.InstallError):
                installer.install(resources, support, self.root / 'Applications')
        self.assertEqual(installer.read(support / 'install-state.json')['status'], 'installing')
        self.assertFalse((self.root / 'Applications/Коса.app').exists())
        with patch.object(installer, 'run', side_effect=lambda args, *unused: commands.append(args)), \
                patch.object(installer, 'download_models'), patch.object(installer, 'stop_managed_services'), patch.object(installer, 'emit'):
            installer.install(resources, support, self.root / 'Applications')
        self.assertEqual(installer.read(support / 'install-state.json')['status'], 'complete')
        self.assertEqual(audio.read_bytes(), b'audio fixture')
        self.assertTrue((support / 'project/work/asr-env').is_symlink())
        sync = next(args for args in commands if 'sync' in args)
        self.assertNotIn('-r', sync)
        self.assertIn('--require-hashes', sync)
        self.assertIn('--only-binary', sync)

    def test_tampering_downgrade_and_disk_full_do_not_change_source(self):
        resources = self.resources()
        support = self.root / 'support'
        support.mkdir()
        root = support / 'project'
        root.mkdir()
        (root / 'release.json').write_text('{"code":6}')
        with self.assertRaises(installer.InstallError):
            installer.install(resources, support, self.root / 'Applications')
        (root / 'release.json').write_text('{"code":4}')
        with patch.object(installer.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            with self.assertRaises(installer.InstallError):
                installer.install(resources, support, self.root / 'Applications')
        (resources / 'payload.zip').write_bytes(b'tampered')
        with self.assertRaises(installer.InstallError):
            installer.install(resources, support, self.root / 'Applications')
        self.assertEqual(installer.read(root / 'release.json')['code'], 4)

    def test_update_lock_prevents_concurrent_replacement(self):
        resources = self.resources()
        support = self.root / 'support'
        updates = support / 'project/work/updates'
        updates.mkdir(parents=True)
        with (updates / 'install.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(installer.InstallError, 'обновление'):
                installer.install(resources, support, self.root / 'Applications')
        self.assertFalse((support / 'project/release.json').exists())

    def test_foreign_running_project_is_never_stopped(self):
        with patch.object(installer.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"project":"/foreign"}')) as request:
            with self.assertRaisesRegex(installer.InstallError, 'другая копия'):
                installer.stop_managed_services(self.root)
        self.assertEqual(request.call_count, 1)

    def test_stopping_services_is_idempotent_and_accepts_closed_connection(self):
        sys.path.insert(0, str(ROOT / 'outputs/recorder'))
        import update_manager
        from urllib.error import HTTPError, URLError
        with patch.object(update_manager, 'urlopen', side_effect=[io.BytesIO(b'{"ok":true}'), http.client.RemoteDisconnected()]):
            update_manager.stop_service('http://127.0.0.1:8765')
        with patch.object(update_manager, 'urlopen', side_effect=URLError('connection refused')) as request:
            update_manager.stop_service('http://127.0.0.1:8765')
            self.assertEqual(request.call_count, 2)
        with patch.object(update_manager, 'urlopen', side_effect=HTTPError('http://fixture', 409, 'busy', {}, None)) as request:
            with self.assertRaises(HTTPError):
                update_manager.stop_service('http://127.0.0.1:8765')
            self.assertEqual(request.call_count, 1)

    def test_recorder_verification_does_not_wait_for_installer_lock(self):
        python = Path(os.environ.get('RECORDER_TEST_PYTHON', ROOT / 'work/installer/Установить Косу.app/Contents/Resources/Setup/python/bin/python3.12'))
        if not python.exists():
            self.skipTest('Bundled Python required')
        root = self.root / 'project'
        shutil.copytree(ROOT / 'outputs/recorder', root / 'outputs/recorder',
                        ignore=shutil.ignore_patterns('recordings', 'analysis', 'study', 'lessons', '__pycache__'))
        (root / 'outputs/recorder/serial.py').write_text('')
        updates = root / 'work/updates'
        updates.mkdir(parents=True)
        with (updates / 'install.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([str(python), '-I', '-B', str(ROOT / 'installer/verify.py'), str(root), 'recorder'],
                                    capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.target = Path(self.temporary.name) / 'model'
        self.content = b'model fixture' * 20000
        self.sha = hashlib.sha256(self.content).hexdigest()
        self.ranges = []
        self.mode = 'normal'
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *unused):
                pass
            def do_GET(self):
                header = self.headers.get('Range')
                owner.ranges.append(header)
                offset = int(header.split('=')[1].split('-')[0]) if header else 0
                if owner.mode == 'ignore-range':
                    offset = 0
                self.send_response(206 if offset else 200)
                if offset:
                    content_range = f'bytes {offset}-{len(owner.content)-1}/{len(owner.content)}'
                    self.send_header('Content-Range', 'invalid' if owner.mode == 'bad-range' else content_range)
                data = b'x' * len(owner.content) if owner.mode == 'bad-hash' else owner.content[offset:]
                if owner.mode == 'interrupted' and len(owner.ranges) == 1:
                    data = data[:100000]
                self.end_headers()
                self.wfile.write(data)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/model'
        installer.CANCEL.clear()

    def tearDown(self):
        installer.CANCEL.clear()
        self.server.shutdown()
        self.server.server_close()
        self.temporary.cleanup()

    def partial(self, size=100000):
        part = self.target.with_name('model.download')
        part.write_bytes(self.content[:size])
        installer.atomic(part.with_name('model.download.json'), dict(bytes=len(self.content), sha256=self.sha))

    def download(self):
        with patch.object(installer.CANCEL, 'wait', return_value=False):
            installer.download(self.url, self.target, len(self.content), self.sha, lambda count: None)

    def test_interrupted_download_resumes_and_is_checked_before_replacement(self):
        self.mode = 'interrupted'
        self.target.write_bytes(b'old valid copy')
        self.download()
        self.assertEqual(self.ranges, [None, 'bytes=100000-'])
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertFalse(self.target.with_name('model.download').exists())
        self.download()
        self.assertEqual(len(self.ranges), 2)

    def test_completed_partial_is_verified_without_network(self):
        self.partial(len(self.content))
        self.download()
        self.assertEqual(self.target.read_bytes(), self.content)
        self.assertFalse(self.ranges)

    def test_server_ignoring_range_restarts_without_duplicate_bytes(self):
        self.partial()
        self.mode = 'ignore-range'
        self.download()
        self.assertEqual(self.target.read_bytes(), self.content)

    def test_wrong_hash_never_replaces_existing_copy(self):
        self.target.write_bytes(b'old valid copy')
        self.mode = 'bad-hash'
        with self.assertRaises(installer.InstallError):
            self.download()
        self.assertEqual(self.target.read_bytes(), b'old valid copy')
        self.assertEqual(len(self.ranges), 4)

    def test_bad_resume_header_does_not_overwrite_previous_copy(self):
        self.partial()
        self.target.write_bytes(b'old valid copy')
        self.mode = 'bad-range'
        with self.assertRaises(installer.InstallError):
            self.download()
        self.assertEqual(self.target.read_bytes(), b'old valid copy')
        self.assertEqual(self.target.with_name('model.download').stat().st_size, 100000)

    def test_cancel_preserves_partial_and_old_copy(self):
        self.partial()
        self.target.write_bytes(b'old valid copy')
        installer.CANCEL.set()
        with self.assertRaises(installer.Cancelled):
            self.download()
        self.assertFalse(self.ranges)
        self.assertEqual(self.target.read_bytes(), b'old valid copy')
        self.assertEqual(self.target.with_name('model.download').stat().st_size, 100000)


class ShutdownTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / 'outputs/recorder'))
        import app_server
        self.module = app_server
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        with patch.object(app_server, 'PROJECT', self.root):
            self.server = app_server.ApplicationServer(('127.0.0.1', 0), 'http://fixture')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.status = {}
        self.urlopen = patch.object(app_server, 'urlopen', side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(self.status).encode()))
        self.stop = patch.object(app_server.update_manager, 'stop_service')
        self.urlopen.start()
        self.stopped = self.stop.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.stop.stop()
        self.urlopen.stop()
        self.module.update_manager.STOP.clear()
        self.temporary.cleanup()

    def request(self, headers=None, path='/quit-for-install', method='POST'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, body=b'{}' if method == 'POST' else None, headers=headers or {})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_host_origin_pairing_and_processing_guards(self):
        self.assertEqual(self.request({'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.request({'Origin': 'https://attacker.example'})[0], 403)
        with patch.object(self.server.pairing, 'public', return_value={'active': True}):
            self.assertEqual(self.request()[0], 409)
        for status in ({'recording': True}, {'busy': True}, {'ai': {'jobs': {'fixture': {'status': 'queued'}}}},
                       {'ai': {'jobs': {'fixture': {'status': 'processing'}}}}):
            self.status = status
            self.assertEqual(self.request()[0], 409)
        self.status = {}
        self.server.reload_requested.set()
        self.assertEqual(self.request()[0], 409)
        self.stopped.assert_not_called()

    def test_shutdown_stops_services_and_reports_owned_project(self):
        with patch.object(self.module, 'PROJECT', self.root):
            status, info = self.request(path='/app-info', method='GET')
        self.assertEqual(status, 200)
        self.assertEqual(info['project'], str(self.root.resolve()))
        status, value = self.request()
        self.assertEqual((status, value['ok']), (200, True))
        self.assertTrue(self.module.update_manager.STOP.is_set())
        self.assertEqual(self.stopped.call_count, 2)
        self.thread.join(2)
        self.assertFalse(self.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
