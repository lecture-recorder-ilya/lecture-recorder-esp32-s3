from contextlib import nullcontext
from types import SimpleNamespace
import hashlib
import io
import json
import os
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import wave
from http.server import ThreadingHTTPServer
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'outputs/recorder'))
import phone_sync
from work.test_phone_sync import H, NAME, PAYLOAD


def audio(frames):
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setparams((1, 2, 16000, 0, 'NONE', ''))
        wav.writeframes(frames)
    return out.getvalue()


class SpaceAndRestart(unittest.TestCase):
    def test_limited_disk_then_kill_before_ack(self):
        volume = os.environ.get('CLIPMIC_SPACE_TEST_VOLUME')
        if volume:
            self.assertTrue(os.path.ismount(volume))
            self.assertLess(shutil.disk_usage(volume).total, 256 * 1024**2)
        with tempfile.TemporaryDirectory(dir=volume) as tmp, ThreadingHTTPServer(('127.0.0.1', 0), H) as server:
            server_thread = threading.Thread(target=server.serve_forever, daemon=True)
            server_thread.start()
            self.addCleanup(server.shutdown)
            root = Path(tmp)
            files = root / 'recordings'
            files.mkdir()
            old = files / 'lecture-2026-11-18-03-00-01-000001.wav'
            old.write_bytes(PAYLOAD)
            old_sha = phone_sync.digest(old)
            def check_old():
                self.assertEqual(phone_sync.digest(old), old_sha)
                with wave.open(str(old)) as wave_file:
                    self.assertEqual(wave_file.getnframes(), 16000)

            data = audio(b'\x12\x00' * (4 * 1024**2))
            sha = hashlib.sha256(data).hexdigest()
            H.data, H.ack, H.fail, H.cutoff, H.ranges = data, 0, False, None, []
            item = dict(name=NAME, bytes=len(data), sha256=sha)
            url = 'http://127.0.0.1:' + str(server.server_port)
            ledger = root / 'ledger.json'
            reserve = 100 * 1024**2
            filler = root / 'занято'
            if volume:
                amount = shutil.disk_usage(root).free - reserve
                self.assertTrue(0 < amount < 128 * 1024**2)
                with filler.open('wb') as out:
                    block = b'x' * (1024**2)
                    while amount > 0:
                        n = min(amount, len(block))
                        out.write(block[:n])
                        amount -= n
                    out.flush()
                    os.fsync(out.fileno())
                free = shutil.disk_usage(root).free
            else:
                free = reserve
            space = nullcontext() if volume else patch.object(shutil, 'disk_usage', return_value=SimpleNamespace(free=free))
            with space:
                with self.assertRaisesRegex(OSError, 'недостаточно места'):
                    phone_sync.import_one(item, url, 'fixture', files, ledger)
            check_old()
            self.assertEqual((H.ranges, H.ack), ([], 0))
            self.assertFalse((files/NAME).exists())
            filler.unlink(missing_ok=True)
            child_code = """
import json,signal,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,sys.argv[1])
import phone_sync
def pause(*args):
    print('получен',flush=True)
    signal.pause()
with patch.object(phone_sync.os,'link',side_effect=pause):
    phone_sync.import_one(json.loads(sys.argv[2]),sys.argv[3],'fixture',Path(sys.argv[4]),Path(sys.argv[5]))
"""
            child = subprocess.Popen([sys.executable, '-B', '-c', child_code, str(Path(phone_sync.__file__).parent),
                                      json.dumps(item), url, str(files), str(ledger)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([child.stdout], [], [], 15)[0])
                self.assertEqual(child.stdout.readline().strip(), 'получен')
            finally:
                child.kill()
                child.wait(10)
                child.stdout.close()
            check_old()
            part = files / (NAME + '.phone-part')
            self.assertEqual(phone_sync.digest(part), sha)
            self.assertEqual(H.ack, 0)
            self.assertFalse(ledger.exists())
            with patch.object(phone_sync, 'queue_pending'), patch('lesson_schedule.organize'):
                phone_sync.import_one(item, url, 'fixture', files, ledger)
            check_old()
            self.assertFalse(part.exists())
            self.assertEqual((H.ranges, H.ack), ([None], 1))
            self.assertEqual(phone_sync.digest(files / NAME), sha)
            self.assertEqual(len(list(files.glob('*.wav'))), 2)
            if volume:
                print(json.dumps(dict(free_before=free, reserve=reserve, incoming=len(data), sha256=sha,
                                      previous_sha256=old_sha, wav_gets=len(H.ranges), acknowledgements=H.ack,
                                      old_frames=16000), ensure_ascii=False))


if __name__ == '__main__':
    unittest.main()
