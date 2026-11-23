import struct
import zipfile
import zlib

STABLE = 'ru.ilya.lecturerecorder'
PREVIEW = STABLE + '.preview'
ASSETS = {STABLE: 'lecture-recorder.apk', PREVIEW: 'lecture-recorder-android.apk'}


def cache_folder(work, package):
    return work / 'updates/android' / {STABLE: '', PREVIEW: 'preview'}[package]


def installed_package(status):
    if not isinstance(status, dict):
        return None
    if 'installed_package' in status:
        package = status['installed_package']
        return package if isinstance(package, str) and package in ASSETS else None
    tag, code = status.get('installed_tag'), status.get('installed_code')
    if type(code) is int:
        if (tag, code) == ('v0.5.4', 22):
            return PREVIEW
        if 11 <= code <= 21 and tag == f'v0.5.3-ai.{code - 10}':
            return PREVIEW
    return STABLE


_INVALID = 'Некорректный манифест APK'
_NO_INDEX = 0xffffffff
_ANDROID = 'http://schemas.android.com/apk/res/android'


def _length(data, offset, width):
    fmt, high_bit = ('<B', 0x80) if width == 1 else ('<H', 0x8000)
    length, = struct.unpack_from(fmt, data, offset)
    offset += width
    if length & high_bit:
        extra, = struct.unpack_from(fmt, data, offset)
        length = ((length & (high_bit - 1)) << (8 * width)) | extra
        offset += width
    return length, offset


def _string(pool, index):
    _, header, size, count, styles, flags, start, end = struct.unpack_from('<HHIIIIII', pool)
    end = end or size
    if index >= count or header < 28 or not header + 4 * (count + styles) <= start <= end <= size:
        raise ValueError(_INVALID)
    relative, = struct.unpack_from('<I', pool, header + index * 4)
    width = 1 if flags & 0x100 else 2
    length, offset = _length(pool, start + relative, width)
    if width == 1:
        length, offset = _length(pool, offset, width)
    stop = offset + width * length
    if stop + width > end or any(pool[stop:stop + width]):
        raise ValueError(_INVALID)
    return bytes(pool[offset:stop]).decode('utf-8' if width == 1 else 'utf-16le')


def _manifest_identity(data):
    kind, pos, size = struct.unpack_from('<HHI', data)
    if kind != 3 or not 8 <= pos <= size or size != len(data):
        raise ValueError(_INVALID)
    pool = None
    while pos < size:
        kind, header, length = struct.unpack_from('<HHI', data, pos)
        if not 8 <= header <= length <= size - pos:
            raise ValueError(_INVALID)
        chunk = memoryview(data)[pos:pos + length]
        pos += length
        if kind == 1:
            if pool is not None or header < 28:
                raise ValueError(_INVALID)
            pool = chunk
        if kind != 0x102:
            continue
        ns, name, start, stride, count = struct.unpack_from('<IIHHH', chunk, header)
        if (pool is None or ns != _NO_INDEX or _string(pool, name) != 'manifest'
                or header < 16 or start < 20 or stride < 20 or header + start + count * stride > length):
            raise ValueError(_INVALID)
        package = code = None
        for index in range(count):
            offset = header + start + stride * index
            ns, name, raw, value_size, _, value_type, value = struct.unpack_from('<IIIHBBI', chunk, offset)
            name = _string(pool, name)
            if value_size != 8:
                raise ValueError(_INVALID)
            if ns == _NO_INDEX and name == 'package':
                if package is not None or value_type != 3:
                    raise ValueError(_INVALID)
                package = _string(pool, value)
                if raw != _NO_INDEX and _string(pool, raw) != package:
                    raise ValueError(_INVALID)
            elif name == 'versionCode' and ns != _NO_INDEX and _string(pool, ns) == _ANDROID:
                if code is not None or value_type not in (0x10, 0x11) or not 0 < value <= 0x7fffffff:
                    raise ValueError(_INVALID)
                code = value
        if package and code is not None:
            return package, code
        break
    raise ValueError(_INVALID)


def apk_identity(path):
    try:
        with zipfile.ZipFile(path) as apk:
            manifests = [entry for entry in apk.infolist() if entry.filename == 'AndroidManifest.xml']
            if len(manifests) != 1 or not 0 < manifests[0].file_size <= 1024 * 1024:
                raise ValueError(_INVALID)
            return _manifest_identity(apk.read(manifests[0]))
    except (zipfile.BadZipFile, struct.error, UnicodeError, EOFError, RuntimeError, zlib.error) as error:
        raise ValueError(_INVALID) from error
