import math
import re
import struct
import wave
from urllib.parse import parse_qs, quote, urlsplit


def serve_fragment(handler, path, query):
    try:
        if any(len(query.get(key, [])) != 1 for key in ('start', 'end')):
            raise ValueError('Укажи начало и конец фрагмента.')
        start, end = (float(query[key][0]) for key in ('start', 'end'))
        if not all(map(math.isfinite, (start, end))) or not 0 <= start < end:
            raise ValueError('Конец фрагмента должен быть позже начала.')
    except ValueError:
        return handler.reply({'error': 'Проверь границы фрагмента.'}, 400)
    try:
        source = wave.open(str(path), 'rb')
    except (wave.Error, EOFError):
        return handler.reply({'error': 'Не удалось прочитать WAV.'}, 422)
    with source:
        rate, total = source.getframerate(), source.getnframes()
        if rate <= 0 or end > total / rate + 0.0005:
            return handler.reply({'error': 'Фрагмент выходит за пределы записи.'}, 400)
        first, last = round(start * rate), min(total, round(end * rate))
        if first >= last:
            return handler.reply({'error': 'Фрагмент слишком короткий.'}, 400)
        channels, width = source.getnchannels(), source.getsampwidth()
        alignment = channels * width
        size = (last - first) * alignment
        padding = size % 2
        if size + padding > 0xffffffff - 36:
            return handler.reply({'error': 'Фрагмент слишком длинный для WAV.'}, 413)
        if alignment > 0xffff or width * 8 > 0xffff or rate * alignment > 0xffffffff:
            return handler.reply({'error': 'Не поддерживается формат WAV.'}, 422)
        source.setpos(last - 1)
        if len(source.readframes(1)) != alignment:
            return handler.reply({'error': 'В записи отсутствует часть звука.'}, 422)
        source.setpos(first)
        header = struct.pack('<4sI4s4sIHHIIHH4sI', b'RIFF', 36 + size + padding,
                             b'WAVE', b'fmt ', 16, 1, channels, rate, rate * alignment,
                             alignment, width * 8, b'data', size)
        name = f'{path.stem}-{round(first * 1000 / rate)}-{round(last * 1000 / rate)}ms.wav'
        handler.send_response(200)
        handler.send_header('Content-Type', 'audio/wav')
        handler.send_header('Content-Length', str(len(header) + size + padding))
        handler.send_header('Content-Disposition', "attachment; filename=\"clip.wav\"; filename*=UTF-8''" + quote(name, safe=''))
        handler.send_header('Cache-Control', 'private, no-store')
        handler.end_headers()
        if handler.command == 'HEAD':
            return
        try:
            handler.wfile.write(header)
            remaining = last - first
            while remaining:
                block = source.readframes(min(remaining, max(1, 131072 // alignment)))
                if not block:
                    break
                remaining -= len(block) // alignment
                handler.wfile.write(block)
            if padding:
                handler.wfile.write(b'\0')
        except (BrokenPipeError, ConnectionResetError):
            pass


def serve_audio(handler, path, active=False):
    if active:
        handler.reply({'error': 'Сначала останови запись.'}, 409)
        return
    query = parse_qs(urlsplit(handler.path).query, keep_blank_values=True)
    if 'start' in query or 'end' in query:
        return serve_fragment(handler, path, query)
    with path.open('rb') as audio:
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        requested = handler.headers.get('Range') if handler.command == 'GET' else None
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested.strip())
            valid = bool(match and any(match.groups()) and size)
            if valid:
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), size - 1) if right else size - 1
                else:
                    suffix = int(right)
                    valid = suffix > 0
                    start = max(0, size - suffix)
                valid = valid and start < size and start <= end
            if not valid:
                handler.send_response(416)
                handler.send_header('Content-Range', f'bytes */{size}')
                handler.send_header('Content-Length', '0')
                handler.send_header('Accept-Ranges', 'bytes')
                handler.end_headers()
                return
            status = 206
        length = max(0, end - start + 1)
        handler.send_response(status)
        handler.send_header('Content-Type', 'audio/wav')
        handler.send_header('Accept-Ranges', 'bytes')
        handler.send_header('Content-Length', str(length))
        handler.send_header('Cache-Control', 'private, no-cache')
        if status == 206:
            handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        handler.end_headers()
        if handler.command == 'HEAD':
            return
        audio.seek(start)
        try:
            while length:
                block = audio.read(min(256 * 1024, length))
                if not block:
                    break
                handler.wfile.write(block)
                length -= len(block)
        except (BrokenPipeError, ConnectionResetError):
            pass
