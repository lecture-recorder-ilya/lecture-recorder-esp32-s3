import hashlib
import os
import stat
from functools import lru_cache

FILENAME = 'v3_ctc.int8.onnx'
SIZE = 224721181
SHA256 = 'ceb61454e2e1a2dec5872cbac1de0fe0a4271d1148f6b26b5bda53ff30a12acd'
REVISION = '322c3b29492673eb7d0b434bfa9dfb8653e34d02'


def signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@lru_cache(maxsize=4)
def _verified(path, expected_stat):
    with path.open('rb') as source:
        if signature(os.fstat(source.fileno())) != expected_stat:
            return False
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
        return digest == SHA256 and signature(os.fstat(source.fileno())) == expected_stat


def available(folder):
    return valid_file(folder / FILENAME)


def valid_file(path):
    try:
        info = path.stat()
        return (stat.S_ISREG(info.st_mode) and info.st_size == SIZE
                and _verified(path, signature(info)))
    except OSError:
        return False
