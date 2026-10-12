"""Reloadable application server. recorder.py owns the persistent audio stream."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit, parse_qs, unquote
import study_store
from learning_moments import moments_for_report, safe_image_query
from speech_context import context_for_recording
import illustrations

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
GENERATION = uuid.uuid4().hex
DOWNLOADS = Path.home()/'Downloads'


def ensure_recording_service(service_url):
    def ready():
        try:
            with urlopen(service_url + '/status', timeout=2) as response:
                status = json.load(response)
                return 'recording' in status and 'samples' in status
        except (OSError, ValueError, URLError):
            return False

    # Reuse the running service, including a recording started by the old app.
    # A lock prevents two application windows from starting two microphone owners.
    work = PROJECT / 'work'
    work.mkdir(exist_ok=True)
    with (work / 'recording-service.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        if ready():
            return
        with (work / 'recording-service.log').open('ab') as log:
            child = subprocess.Popen(
                [sys.executable, str(ROOT / 'recorder.py')], cwd=PROJECT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if ready():
                return
            if child.poll() is not None:
                break
            time.sleep(.2)
        raise RuntimeError('Служба записи не запустилась. См. work/recording-service.log')


def ensure_study_service():
    work = PROJECT/'work'
    with (work/'study-service.lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX)
        try:
            with urlopen('http://127.0.0.1:8768/study-status',timeout=2):return
        except URLError:pass
        with (work/'study-service.log').open('ab') as log:
            subprocess.Popen([str(work/'ai-env/bin/python'),str(ROOT/'study_service.py')],cwd=PROJECT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)


class ApplicationServer(ThreadingHTTPServer):
    # Finish in-flight commands/downloads before replacing the application code.
    daemon_threads = False

    def __init__(self, address, service_url):
        super().__init__(address, Handler)
        self.service_url = service_url
        self.reload_requested = threading.Event()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def reply(self, payload, status=200, mime='application/json; charset=utf-8'):
        if isinstance(payload, dict):
            payload = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def proxy(self, body=None):
        response_started = False
        headers = {'Content-Type': 'application/json'} if body is not None else {}
        request = Request(self.server.service_url + self.path, data=body, headers=headers)
        try:
            try:
                response = urlopen(request, timeout=45)
            except HTTPError as error:
                response = error
            with response:
                self.send_response(response.code)
                for name in ('Content-Type', 'Content-Length'):
                    value = response.headers.get(name)
                    if value is not None:
                        self.send_header(name, value)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                response_started = True
                while True:
                    block = response.read(65536)
                    if not block:
                        break
                    self.wfile.write(block)
        except (URLError, TimeoutError):
            if not response_started:
                self.reply({'error': 'Служба записи не отвечает. Проверь её журнал.'}, 503)
        except (BrokenPipeError, ConnectionResetError):
            # Closing or reloading the UI never sends Stop to the audio service.
            pass

    def do_GET(self):
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        try:
            if route.path=='/proofread':
                name=query.get('file',[''])[0];study_store.audio(name)
                from transcript_corrector import proofread
                report=study_store.read(ROOT/'analysis'/(Path(name).stem+'.json')) or study_store.read(ROOT/'analysis'/(Path(name).stem+'.live.json'))
                return self.reply(proofread(report,context_for_recording(name)['subject']))
            if route.path=='/asr-vocabulary':
                name=query.get('file',[''])[0];study_store.audio(name)
                return self.reply({'terms':study_store.notes(name).get('asr_terms','')})
            if route.path.startswith('/analysis/'):
                name=unquote(route.path.removeprefix('/analysis/'));study_store.audio(name)
                path=ROOT/'analysis'/(Path(name).stem+'.json')
                if not path.exists():path=path.with_suffix('.live.json')
                if path.exists():
                    report=study_store.read(path)
                    from presentation_sections import presentations,roles
                    from passive_teacher import public
                    report['presentations']=presentations(report.get('segments',[]),report.get('duration',0))
                    teacher=public(study_store.read(ROOT/'study'/(Path(name).stem+'.passive-teacher.json')))
                    report['speaker_roles']=roles(report.get('segments',[]),report['presentations'],teacher['teacher_ranges'])
                    from teacher_remarks import remarks
                    report['teacher_remarks']=remarks(report.get('segments',[]),report['speaker_roles'],report.get('teacher_remarks',[]))
                    return self.reply(report)
            if route.path == '/calendar':
                return self.reply(json.loads((ROOT/'schedule.json').read_text()))
            if route.path == '/study_ui.js':
                return self.reply((ROOT/'study_ui.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if route.path == '/telegram_export.js':
                return self.reply((ROOT/'telegram_export.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if route.path.startswith('/vendor/'):
                target=(ROOT/unquote(route.path.lstrip('/'))).resolve()
                if ROOT/'vendor' not in target.parents:
                    raise ValueError('Некорректный путь')
                import mimetypes
                return self.reply(target.read_bytes(),mime=mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
            if route.path == '/status':
                with urlopen(self.server.service_url + '/status', timeout=5) as response:
                    status = json.load(response)
                import phone_sync
                status['phone_sync'] = phone_sync.status()
                return self.reply(study_store.enrich(status))
            if route.path in ('/learning-moments','/illustration'):
                name=query.get('file',[''])[0];study_store.audio(name)
                report=study_store.read(ROOT/'analysis'/(Path(name).stem+'.json')) or study_store.read(ROOT/'analysis'/(Path(name).stem+'.live.json'))
                moments=moments_for_report(report,context_for_recording(name)['subject'])
                if route.path=='/learning-moments':return self.reply({'moments':moments})
                index=int(query.get('moment',['-1'])[0])
                if not 0<=index<len(moments):raise ValueError('Момент не найден')
                item=moments[index]
                from historical_people import person_query,private_name_query
                topic=person_query(item) if item.get('kind')=='person' else safe_image_query(item.get('image_query'),item['quote'])
                if not topic or private_name_query(topic,item.get('quote','')+' '+item.get('context','')):return self.reply({'status':'unavailable'})
                try:return self.reply(illustrations.lookup(topic))
                except (OSError,URLError,ValueError):return self.reply({'status':'unavailable','message':'Иллюстрация пока недоступна'})
            if route.path == '/notes':
                return self.reply(study_store.notes(query.get('file', [''])[0]))
            if route.path.startswith('/photos/'):
                ident = unquote(route.path.removeprefix('/photos/'))
                if not __import__('re').fullmatch(r'[a-f0-9]{32}\.(jpg|png|webp)', ident):
                    raise ValueError('Некорректное фото')
                mime = {'jpg':'image/jpeg', 'png':'image/png', 'webp':'image/webp'}[ident.rsplit('.',1)[1]]
                return self.reply((ROOT/'study/photos'/ident).read_bytes(), mime=mime)
            if route.path.startswith('/speakers/'):
                name = unquote(route.path.removeprefix('/speakers/'))
                study_store.audio(name)
                return self.reply(study_store.read(ROOT/'study'/(Path(name).stem+'.speakers.json'), {'status':'pending','speakers':[],'segments':[]}))
            if route.path in ('/live', '/monitor-frame', '/study-status', '/search', '/speaker-track', '/voice-sample'):
                with urlopen('http://127.0.0.1:8768' + self.path, timeout=90) as response:
                    return self.reply(response.read(), mime=response.headers.get('Content-Type','application/json'))
        except ValueError as error:
            return self.reply({'error':str(error)},400)
        except (OSError, URLError) as error:
            return self.reply({'error':'Учебный сервис пока недоступен: '+str(error)},503)
        if self.path == '/':
            return self.reply((ROOT / 'index.html').read_bytes(), mime='text/html; charset=utf-8')
        if self.path == '/app-info':
            return self.reply({'generation': GENERATION, 'pid': os.getpid()})
        if self.path == '/status' or self.path.startswith(('/recordings/', '/analysis/', '/export/')):
            return self.proxy()
        self.reply({'error': 'Не найдено'}, 404)

    def do_POST(self):
        port = self.server.server_port
        if self.headers.get('Origin') not in (None, f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
            return self.reply({'error': 'Запрос отклонён'}, 403)
        try:
            length = int(self.headers.get('Content-Length', 0))
            route = urlsplit(self.path)
            if route.path=='/telegram-export':
                if not 0<length<=2*1024*1024:raise ValueError('Слишком большой запрос')
                value=json.loads(self.rfile.read(length));name=value.get('file');study_store.audio(name)
                text=value.get('text')
                if not isinstance(text,str) or not text.strip():raise ValueError('Нет текста для сохранения')
                DOWNLOADS.mkdir(parents=True,exist_ok=True)
                target=DOWNLOADS/(Path(name).stem+'-telegram-'+uuid.uuid4().hex[:8]+'.txt')
                with target.open('x',encoding='utf-8') as out:
                    out.write(text);out.flush();os.fsync(out.fileno())
                return self.reply({'ok':True,'filename':target.name})
            if route.path=='/asr-vocabulary':
                if not 0<length<=2048:raise ValueError('Слишком большой запрос')
                body=json.loads(self.rfile.read(length));name=body.get('file');study_store.audio(name)
                from speech_context import normalize_terms
                terms=normalize_terms(body.get('terms',''))
                with study_store.transaction():
                    notes=study_store.notes(name);notes['asr_terms']=terms;study_store.save(study_store.note_path(name),notes)
                return self.reply({'ok':True,'terms':terms})
            if route.path == '/photo':
                if not 0 < length <= 12*1024*1024:
                    return self.reply({'error':'Фото больше 12 МБ или пустое'},413)
                query = parse_qs(route.query)
                with urlopen(self.server.service_url+'/status',timeout=5) as response:
                    status = json.load(response)
                return self.reply(study_store.add_photo(query.get('file',[''])[0],query.get('start',['0'])[0],self.rfile.read(length),status))
            if not 0 <= length <= 4096:
                return self.reply({'error': 'Слишком большой запрос'}, 413)
            body = self.rfile.read(length)
            if body and not isinstance(json.loads(body), dict):
                raise ValueError('Expected object')
        except (ValueError, UnicodeDecodeError, TypeError):
            return self.reply({'error': 'Некорректный запрос'}, 400)
        except (OSError, URLError):
            return self.reply({'error':'Служба записи временно недоступна'},503)
        try:
            value = json.loads(body) if body else {}
            if self.path in ('/marker','/photo-time','/move','/merge'):
                with urlopen(self.server.service_url+'/status',timeout=5) as response:
                    status = study_store.enrich(json.load(response))
                if self.path == '/marker':
                    return self.reply(study_store.marker(value,status))
                if self.path == '/photo-time':
                    return self.reply(study_store.photo_time(value,status))
                if self.path == '/move':
                    return self.reply(study_store.move(value.get('file'),value.get('folder'),status.get('lessons',{}).get(value.get('file'))))
                result = study_store.merged(value,status)
                if status.get('ai',{}).get('auto'):
                    try:
                        with urlopen(Request(self.server.service_url+'/analyze',data=json.dumps({'file':result['file']}).encode(),headers={'Content-Type':'application/json'}),timeout=5):pass
                    except URLError:
                        result['warning'] = 'Запись объединена; запусти разбор кнопкой.'
                return self.reply(result)
            if self.path in ('/live-settings','/speaker-choice'):
                with urlopen(Request('http://127.0.0.1:8768'+self.path,data=body,headers={'Content-Type':'application/json'}),timeout=10) as response:
                    return self.reply(response.read())
        except (ValueError, TypeError, KeyError) as error:
            return self.reply({'error':str(error)},400)
        except (OSError, URLError) as error:
            return self.reply({'error':str(error)},503)
        if self.path == '/reload-app':
            try:
                source = Path(__file__).resolve()
                compile(source.read_bytes(), str(source), 'exec')
                helper = source.parent/'study_store.py'
                compile(helper.read_bytes(), str(helper), 'exec')
            except (SyntaxError, OSError) as error:
                return self.reply({'error': 'Исправь код перед обновлением: ' + str(error)}, 400)
            self.reply({'ok': True, 'generation': GENERATION})
            if not self.server.reload_requested.is_set():
                self.server.reload_requested.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path in ('/start', '/stop', '/pair', '/check-wifi', '/setup-hotspot', '/ai-settings', '/analyze'):
            return self.proxy(body)
        self.reply({'error': 'Не найдено'}, 404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--service-url', default='http://127.0.0.1:8765')
    parser.add_argument('--no-start-service', action='store_true')
    options = parser.parse_args()
    server = ApplicationServer(('127.0.0.1', options.port), options.service_url)
    try:
        if not options.no_start_service:
            ensure_recording_service(options.service_url)
            ensure_study_service()
            import phone_sync
            phone_sync.start()
        print(f'Application: http://127.0.0.1:{options.port}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    if server.reload_requested.is_set():
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])


if __name__ == '__main__':
    main()
