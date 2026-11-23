"""Локальная репетиция импорта и прерванного чтения 90-минутного WAV."""
import hashlib
import json
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "outputs/recorder"))
from audio_import import normalize
from media_stream import serve_audio


def run(directory):
    source = directory / "pair.wav"
    target = directory / "normalized.wav"
    clip = Path(__file__).with_name("fleurs-41-room-6db.wav")
    with wave.open(str(clip)) as audio:
        chunk = audio.readframes(audio.getnframes())
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", ""))
        whole, tail = divmod(5400 * 32000, len(chunk))
        for _ in range(whole):
            audio.writeframesraw(chunk)
        audio.writeframesraw(chunk[:tail])

    start = time.monotonic()
    duration = normalize(source, target, ROOT)
    import_seconds = time.monotonic() - start
    assert duration == 5400
    with source.open("rb") as audio:
        expected = hashlib.file_digest(audio, "sha256").hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            serve_audio(self, target)

        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_port}/pair.wav"
        digest = hashlib.sha256()
        offset = 0
        try:
            with urlopen(url, timeout=10) as response:
                assert response.status == 200
                start = time.monotonic()
                while offset < 1024 * 1024:
                    block = response.read(65536)
                    assert block
                    digest.update(block)
                    offset += len(block)
                    time.sleep(max(0, start + offset * 8 / 2_000_000 - time.monotonic()))
            prefix_seconds = time.monotonic() - start
            request = Request(url, headers={"Range": f"bytes={offset}-"})
            with urlopen(request, timeout=10) as response:
                assert response.status == 206
                content_range = response.headers["Content-Range"]
                size = source.stat().st_size
                assert content_range == f"bytes {offset}-{size - 1}/{size}"
                while block := response.read(1 << 20):
                    digest.update(block)
        finally:
            server.shutdown()
            thread.join()
    assert digest.hexdigest() == expected
    return dict(seconds_of_audio=duration, bytes=size, repeated_clip=True,
                normalization_seconds=round(import_seconds, 3),
                capped_prefix_bytes=offset, capped_prefix_seconds=round(prefix_seconds, 3),
                planned_prefix_bits_per_second=2_000_000, resumed_http=206,
                content_range=content_range, complete_sha256=expected)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as folder:
        print(json.dumps(run(Path(folder)), indent=2))
