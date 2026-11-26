import hashlib
import os
import shutil
import ssl
import tempfile
import urllib.request
import zipfile
from pathlib import Path


WHEEL = 'av-16.0.1-cp312-cp312-macosx_14_0_arm64.whl'
URL = 'https://files.pythonhosted.org/packages/27/19/3a4d3882852a0ee136121979ce46f6d2867b974eb217a2c9a070939f55ad/' + WHEEL
SHA256 = '6352a64b25c9f985d4f279c2902db9a92424e6f2c972161e67119616f0796cb9'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def bundle_audio_decoder(project, resources):
    cache = project / 'work/installer-tools'
    cache.mkdir(parents=True, exist_ok=True)
    wheel = cache / WHEEL
    if not wheel.is_file() or digest(wheel) != SHA256:
        cafile = Path('/etc/ssl/cert.pem')
        context = ssl.create_default_context(cafile=str(cafile) if cafile.exists() else None)
        with tempfile.TemporaryDirectory(dir=cache) as pending:
            download = Path(pending) / WHEEL
            with urllib.request.urlopen(URL, timeout=60, context=context) as response, download.open('wb') as target:
                shutil.copyfileobj(response, target)
            if digest(download) != SHA256:
                raise ValueError('Не совпала контрольная сумма аудиодекодера.')
            os.replace(download, wheel)
    decoder = resources / 'MediaDecoder'
    if decoder.exists():
        shutil.rmtree(decoder)
    decoder.mkdir(parents=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(decoder)
    shutil.copyfile(project / 'outputs/recorder/media_decode.py', decoder / 'media_decode.py')
