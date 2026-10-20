import re


def serve_audio(handler, path, active=False):
    if active:
        handler.reply({'error': 'Сначала останови запись.'}, 409)
        return
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
