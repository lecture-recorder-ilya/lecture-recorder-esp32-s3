import json
import os
import struct


def trailing_chunks(stream, offset, size):
    found = False
    while offset < size:
        stream.seek(offset)
        header = stream.read(8)
        if len(header) != 8 or not all(32 <= b <= 126 for b in header[:4]):
            return False
        length = struct.unpack('<I', header[4:])[0]
        offset += 8 + length + length % 2
        if offset > size:
            return False
        found = True
    return found and offset == size


def recover(folder):
    repaired = []
    for path in folder.glob('lecture-*.wav'):
        try:
            with path.open('r+b') as f:
                header = f.read(44)
                if (len(header) != 44 or header[:4] != b'RIFF' or header[8:16] != b'WAVEfmt '
                        or header[36:40] != b'data' or struct.unpack('<IHHIIHH', header[16:36])
                        != (16, 1, 1, 16000, 32000, 2, 16)):
                    continue
                size = os.fstat(f.fileno()).st_size
                length = size - 44
                if length > 0xffffffff - 36:
                    continue
                declared = struct.unpack('<I', header[40:44])[0]
                riff = struct.unpack('<I', header[4:8])[0]
                if (riff + 8 == size and declared < length
                        and trailing_chunks(f, 44 + declared + declared % 2, size)):
                    continue
                length -= length % 2
                if declared == length and riff == length + 36 and size == 44 + length:
                    continue
                f.truncate(44 + length)
                f.seek(4); f.write(struct.pack('<I', 36 + length))
                f.seek(40); f.write(struct.pack('<I', length))
                f.flush(); os.fsync(f.fileno())
            repaired.append(path.name)
            path.with_suffix('.recovery.json').write_text(json.dumps({'repaired_header': True, 'frames': length // 2}))
        except OSError:
            continue
    return repaired
