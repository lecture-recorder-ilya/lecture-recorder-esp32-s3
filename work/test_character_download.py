import hashlib
import io
import json
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'outputs/recorder'))
import character_download as download
import character_weights as weights
import quality_asr


class Clock:
    def __init__(self):
        self.seconds = 0

    def __call__(self):
        self.seconds += 1
        return self.seconds


class Response(io.BytesIO):
    def __init__(self, body, status=200, headers=None, on_read=None):
        super().__init__(body)
        self.status = status
        self.headers = {'Content-Length': str(len(body))} if headers is None else headers
        self.on_read = on_read

    def read1(self, n):
        if self.on_read:
            self.on_read()
        return self.read(n)


class Delivery(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name)
        self.refresh = download.ModelRefresh(self.project)
        self.folder = self.refresh.folder
        self.folder.mkdir(parents=True)
        self.full = self.folder / 'v3_ctc.onnx'
        self.full.write_bytes(b'working full graph')
        (self.folder.parent / 'gigaam-beam-manifest.json').write_text('{}')
        self.fast = self.folder / weights.FILENAME
        self.data = b'checked test graph'
        self.clock = Clock()
        for mocked in [patch.multiple(weights, SIZE=len(self.data), SHA256=hashlib.sha256(self.data).hexdigest()),
                       patch.object(download, 'BLOCK', 4), patch('character_download.time.monotonic', self.clock)]:
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_signed_in_current_release_and_idle_are_required(self):
        fetch = Mock(side_effect=lambda *_a, **_kw: Response(self.data))
        for state in (None, False):
            self.refresh.after_check(state)
            self.refresh.poll(fetch, lambda: True)
        self.refresh.after_check(True)
        self.refresh.poll(fetch, lambda: False)
        fetch.assert_not_called()
        self.clock.seconds += 12
        self.refresh.poll(fetch, lambda: True)
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, download.URL)
        self.assertNotIn('authorization', {key.lower() for key, _ in request.header_items()})
        self.assertEqual(self.fast.read_bytes(), self.data)
        self.refresh.after_check(True)
        self.refresh.poll(fetch, lambda: True)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(self.full.read_bytes(), b'working full graph')

    def test_starts_recording_then_resumes_once_using_range(self):
        active = []
        self.refresh.after_check(True)
        fetch = Mock(return_value=Response(self.data, on_read=lambda: active.append(True)))
        self.refresh.poll(fetch, lambda: not active)
        part, = self.folder.glob('*.part')
        prefix = part.read_bytes()
        self.assertEqual(prefix, self.data[:4])
        self.assertFalse(self.fast.exists())
        self.assertEqual(self.refresh.attempts, 2)
        self.clock.seconds += 12
        fetch = Mock(return_value=Response(self.data[4:], 206, {'Content-Range': f'bytes 4-{weights.SIZE-1}/{weights.SIZE}'}))
        self.refresh.poll(fetch, lambda: True)
        self.assertEqual(fetch.call_args.args[0].get_header('Range'), 'bytes=4-')
        self.assertEqual(self.fast.read_bytes(), self.data)
        self.assertFalse(part.exists())

    def test_logout_interrupts_the_transfer_until_the_next_authenticated_check(self):
        import update_manager as updates
        from update_auth import Authorization

        auth = Authorization(self.project, vault=Mock())
        auth.credentials = {'access_token': 'fixture'}
        auth.poll = Mock()
        checks, requests, snapshots = [], [], []
        check = threading.Event()
        server = SimpleNamespace(service_url='unused', install_requested=False)

        def release():
            checks.append(bool(auth.credentials))
            return checks[-1]

        def fetch(request, **options):
            offset = request.get_header('Range')
            requests.append(offset)
            if offset:
                return Response(self.data[4:], 206, {'Content-Range': f'bytes 4-{weights.SIZE-1}/{weights.SIZE}'})
            return Response(self.data, on_read=auth.disconnect)

        def next_tick(_seconds):
            snapshots.append((self.fast.exists(), len(requests)))
            if len(snapshots) == 2:
                auth.credentials = {'access_token': 'fixture'}
                check.set()

        stop = SimpleNamespace(is_set=lambda: len(snapshots) >= 3, wait=next_tick)
        with patch.object(updates, 'PROJECT', self.project), patch.object(updates, 'AUTH', auth), \
             patch.object(updates, 'STOP', stop), patch.object(updates, 'CHECK', check), \
             patch.object(updates, 'download_release', side_effect=release), patch.object(updates, 'fetch', fetch), \
             patch.object(updates, 'idle', return_value=True), \
             patch.object(updates.threading, 'Thread', side_effect=lambda target, **_: SimpleNamespace(start=target)):
            updates.start(server)
        self.assertEqual(checks, [True, False, True])
        self.assertEqual(snapshots, [(False, 1), (False, 1), (True, 2)])
        self.assertEqual(requests, [None, 'bytes=4-'])
        self.assertEqual(self.fast.read_bytes(), self.data)

    def test_refuses_oversized_responses_before_publication(self):
        for response in (Response(self.data + b'x'), Response(self.data + b'x', headers={})):
            self.refresh.after_check(True)
            self.refresh.poll(Mock(return_value=response), lambda: True)
            self.assertFalse(self.fast.exists())
            self.assertEqual(self.full.read_bytes(), b'working full graph')

    def test_bad_hash_is_bounded_and_keeps_full_graph(self):
        fetch = Mock(side_effect=lambda *_a, **_kw: Response(b'x' * len(self.data)))
        self.refresh.after_check(True)
        self.refresh.poll(fetch, lambda: True)
        self.refresh.poll(fetch, lambda: True)
        self.assertEqual(fetch.call_count, 1)
        self.clock.seconds += download.RETRY_SECONDS
        self.refresh.poll(fetch, lambda: True)
        self.clock.seconds += 3600
        self.refresh.poll(fetch, lambda: True)
        self.assertEqual(fetch.call_count, 2)
        self.assertFalse(self.fast.exists())
        self.assertFalse(list(self.folder.glob('*.part')))
        self.assertEqual(self.full.read_bytes(), b'working full graph')

    def test_incomplete_response_wrong_range_and_ignored_range(self):
        fetch = Mock(side_effect=lambda *_a, **_kw: Response(self.data[:5], headers={}))
        self.refresh.after_check(True)
        self.refresh.poll(fetch, lambda: True)
        part, = self.folder.glob('*.part')
        self.assertEqual(part.read_bytes(), self.data[:5])
        self.clock.seconds += download.RETRY_SECONDS
        self.refresh.poll(Mock(return_value=Response(self.data, 206, {'Content-Range': 'bytes 0-1/2'})), lambda: True)
        self.assertEqual(part.read_bytes(), self.data[:5])
        self.assertFalse(self.fast.exists())
        self.refresh.after_check(True)
        self.refresh.poll(Mock(return_value=Response(self.data)), lambda: True)
        self.assertEqual(self.fast.read_bytes(), self.data)

    def test_partial_link_cannot_redirect_resumed_data(self):
        part = self.folder / f'.{weights.FILENAME}.{weights.SHA256[:12]}.part'
        part.symlink_to(self.full)
        self.refresh.after_check(True)
        fetch = Mock(return_value=Response(self.data))
        self.refresh.poll(fetch, lambda: True)
        self.assertIsNone(fetch.call_args.args[0].get_header('Range'))
        self.assertEqual(self.full.read_bytes(), b'working full graph')
        self.assertEqual(self.fast.read_bytes(), self.data)

    def test_concurrent_checks_only_fetch_once(self):
        entered, go = threading.Event(), threading.Event()
        def fetch(_request, **_options):
            entered.set()
            if not go.wait(3):
                raise AssertionError('Параллельная проверка не освободила тест')
            return Response(self.data)
        self.refresh.after_check(True)
        first = threading.Thread(target=self.refresh.poll, args=(fetch, lambda: True))
        first.start()
        try:
            self.assertTrue(entered.wait(2))
            other = download.ModelRefresh(self.project)
            other.after_check(True)
            forbidden = Mock(side_effect=AssertionError('Вторая загрузка'))
            other.poll(forbidden, lambda: True)
            forbidden.assert_not_called()
        finally:
            go.set()
            first.join(4)
        self.assertFalse(first.is_alive())
        self.assertEqual(self.fast.read_bytes(), self.data)

    def test_live_preview_changes_mode_only_for_the_next_recording(self):
        import study_service
        with patch.object(quality_asr, 'CHAR', self.folder):
            decoder = quality_asr.Decoder(threads=2)
            with patch.object(study_service, 'QUALITY_DECODER', decoder), \
                 patch.object(study_service, 'QUALITY_CURSOR', {'file': None, 'end': 0}), \
                 patch.object(study_service, 'quality_ready', return_value=True):
                first = study_service.monitor_quality('first.wav', 800)
                self.fast.write_bytes(self.data)
                same = study_service.monitor_quality('first.wav', 1600)
                second = study_service.monitor_quality('second.wav', 800)
            self.assertEqual(first['model'], quality_asr.BASE_ENGINE)
            self.assertEqual(same['model'], first['model'])
            self.assertEqual(second['model'], quality_asr.engine_for(True))

    def test_release_gate_requires_the_current_published_release(self):
        import update_manager as updates
        (self.project / 'release.json').write_text(json.dumps({'version': '1.0.0'}))
        with patch.object(updates, 'cache_android', return_value=''), \
             patch.object(updates, 'fetch', side_effect=[Response(b'{"tag_name":"v1.0.0","draft":true}'),
                                                        Response(b'{"tag_name":"v1.0.0"}')]):
            self.assertFalse(updates.download_release(self.project))
            self.assertIs(updates.download_release(self.project), True)


if __name__ == '__main__':
    unittest.main()
