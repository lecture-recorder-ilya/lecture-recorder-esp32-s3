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
import update_manager
update_manager.recover()
import study_store
import mirea_schedule
import lesson_schedule
import recording_selection
from learning_moments import moments_for_report, safe_image_query
from speech_context import context_for_recording
import illustrations
import board_photos
from audio_import import Importer, MAX_BYTES
from audio_enhance import Enhancer
from transcript_quality import annotate, report_for, plain_text, markdown
from phone_pairing import Pairing, PairingError

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
        self.install_requested = False
        self.pairing = Pairing(PROJECT)
        self.importer = Importer(ROOT, self.import_ready)
        self.enhancer = Enhancer(ROOT)

    def import_ready(self, job):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime.fromtimestamp(job['created'], ZoneInfo('Europe/Moscow'))
        subject = job.get('subject') or 'Загруженная запись'
        date = job.get('date') or now.strftime('%Y-%m-%d')
        meta = {'subject': subject, 'teacher': job.get('teacher', ''), 'date': date,
                'start': now.strftime('%H:%M'), 'end': '', 'type': 'Лекция',
                'title': job.get('title') or Path(job['name']).stem,
                'imported': True, 'original_name': job['name']}
        folder = study_store.folder_name(date + ' — ' + subject)
        study_store.move(job['file'], folder, meta)
        with study_store.transaction():
            notes = study_store.notes(job['file'])
            notes.update(import_id=job['id'], original_name=job['name'])
            study_store.save(study_store.note_path(job['file']), notes)
        if job['analyze']:
            request = Request(self.service_url + '/analyze',
                              data=json.dumps({'file': job['file'], 'wait_models': True}).encode(),
                              headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=15) as response:
                json.load(response)

    def server_close(self):
        self.importer.close()
        self.enhancer.close()
        self.pairing.close()
        super().server_close()


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
        if self.headers.get('Range'):
            headers['Range'] = self.headers['Range']
        request = Request(self.server.service_url + self.path, data=body, headers=headers,
                          method='HEAD' if self.command == 'HEAD' else None)
        try:
            try:
                response = urlopen(request, timeout=45)
            except HTTPError as error:
                response = error
            with response:
                self.send_response(response.code)
                for name in ('Content-Type', 'Content-Length', 'Accept-Ranges', 'Content-Range', 'Content-Disposition'):
                    value = response.headers.get(name)
                    if value is not None:
                        self.send_header(name, value)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                response_started = True
                if self.command == 'HEAD':
                    return
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

    def do_HEAD(self):
        route = urlsplit(self.path)
        if route.path.startswith('/enhanced-audio/'):
            return self.do_GET()
        if urlsplit(self.path).path.startswith('/recordings/'):
            return self.proxy()
        self.send_response(404)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        try:
            if route.path in ('/mirea-profile', '/recording-selection', '/calendar'):
                port = self.server.server_port
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
            if route.path == '/audio_enhance_ui.js':
                return self.reply((ROOT / 'audio_enhance_ui.js').read_bytes(), mime='text/javascript; charset=utf-8')
            if route.path == '/audio-enhancement' or route.path.startswith('/enhanced-audio/'):
                name = query.get('file', [''])[0] if route.path == '/audio-enhancement' else unquote(route.path.removeprefix('/enhanced-audio/'))
                study_store.audio(name)
                profile = query.get('profile', ['gentle'])[0]
                if route.path == '/audio-enhancement':
                    return self.reply(self.server.enhancer.status(name, profile))
                from media_stream import serve_audio
                return serve_audio(self, self.server.enhancer.audio(name, profile))
            if route.path == '/imports':
                return self.reply({'jobs': self.server.importer.list()})
            if route.path == '/lecture_workflow.js':
                return self.reply((ROOT / 'lecture_workflow.js').read_bytes(), mime='text/javascript; charset=utf-8')
            if route.path.startswith('/transcript-export/'):
                name = unquote(route.path.removeprefix('/transcript-export/'))
                study_store.audio(name)
                report = report_for(ROOT, name)
                if report is None:
                    return self.reply({'error': 'Расшифровка ещё не готова.'}, 404)
                decisions = study_store.notes(name).get('transcript_review', {})
                return self.reply(plain_text(annotate(report, decisions)).encode(), mime='text/plain; charset=utf-8')
            if route.path.startswith('/export/'):
                name = unquote(route.path.removeprefix('/export/'))
                study_store.audio(name)
                report = report_for(ROOT, name)
                if report is None:
                    return self.reply({'error': 'Конспект ещё не готов.'}, 404)
                report = annotate(report, study_store.notes(name).get('transcript_review', {}))
                return self.reply(markdown(report).encode(), mime='text/markdown; charset=utf-8')
            if route.path in ('/phone-pairing', '/phone-sync', '/phone_pairing_ui.js'):
                if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
                if route.path == '/phone-sync':
                    import phone_sync
                    try:
                        return self.reply(phone_sync.status())
                    except OSError:
                        return self.reply({'error':'Не удалось прочитать состояние обмена.'},503)
                if route.path == '/phone-pairing':
                    return self.reply(self.server.pairing.public())
                return self.reply((ROOT/'phone_pairing_ui.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if route.path=='/updates_ui.js':
                return self.reply((ROOT/'updates_ui.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if route.path=='/board-photos':return self.reply(board_photos.public())
            if route.path.startswith('/board-photo-image/'):
                return self.reply(board_photos.image(route.path.removeprefix('/board-photo-image/')).read_bytes(),mime='image/jpeg')
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
                report = report_for(ROOT, name)
                if report is not None:
                    report = annotate(report, study_store.notes(name).get('transcript_review', {}))
                    from presentation_sections import presentations,roles
                    from passive_teacher import public
                    report['presentations']=presentations(report.get('segments',[]),report.get('duration',0))
                    teacher=public(study_store.read(ROOT/'study'/(Path(name).stem+'.passive-teacher.json')))
                    report['speaker_roles']=roles(report.get('segments',[]),report['presentations'],teacher['teacher_ranges'])
                    from teacher_remarks import remarks
                    report['teacher_remarks']=remarks(report.get('segments',[]),report['speaker_roles'],report.get('teacher_remarks',[]))
                    return self.reply(report)
            if route.path == '/mirea-profile':
                return self.reply(mirea_schedule.profile())
            if route.path == '/calendar':
                return self.reply(mirea_schedule.load_calendar(lesson_schedule.DATA))
            if route.path == '/recording-selection':
                name = query.get('file', [''])[0]
                with urlopen(self.server.service_url+'/status',timeout=4) as response:
                    status = json.load(response)
                if name not in status.get('pending_lessons', []):
                    raise ValueError('Эта запись уже обработана или недоступна.')
                audio = recording_selection.recording(name)
                moment = lesson_schedule.recording_time(name)
                seconds = (audio.stat().st_size - 44) / 32000
                calendar = mirea_schedule.load_calendar(lesson_schedule.DATA)
                entries = [entry for entry in calendar['entries'] if entry['date'] == moment.date().isoformat()]
                return self.reply({'file':name,'date':moment.date().isoformat(),'start':moment.strftime('%H:%M'),
                                   'seconds':seconds,'choices':entries,'suggested':mirea_schedule.suggest(entries,moment,seconds),
                                   'note':calendar.get('error','')})
            if route.path == '/study_ui.js':
                return self.reply((ROOT/'study_ui.js').read_bytes(),mime='text/javascript; charset=utf-8')
            if route.path == '/board_ui.js':
                return self.reply((ROOT/'board_ui.js').read_bytes(),mime='text/javascript; charset=utf-8')
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
            if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
                return self.reply({'error': 'Запрос отклонён'}, 403)
            installed = update_manager.read(PROJECT / 'release.json').get('version', '')
            return self.reply({'generation': GENERATION, 'pid': os.getpid(), 'project': str(PROJECT.resolve()),
                               'version': installed, 'updates': dict(update_manager.STATE),
                               'update_auth': update_manager.AUTH.public()})
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
            if route.path == '/import-audio':
                self.close_connection = True
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error': 'Запрос отклонён'}, 403)
                if self.server.reload_requested.is_set():
                    return self.reply({'error': 'Приложение перезапускается. Повтори загрузку.'}, 409)
                if not 0 < length <= MAX_BYTES:
                    return self.reply({'error': 'Выбери непустую запись размером до 2 ГБ.'}, 413)
                query = parse_qs(route.query)
                self.connection.settimeout(180)
                values = {key: query.get(key, [''])[0] for key in ('title', 'subject', 'teacher', 'date')}
                values['analyze'] = query.get('analyze', ['1'])[0] != '0'
                value = self.server.importer.receive(self.rfile, length, query.get('name', [''])[0], values)
                return self.reply({key: value[key] for key in ('id', 'file', 'status', 'message', 'duplicate') if key in value}, 202)
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
        except (ValueError, UnicodeDecodeError, TypeError) as error:
            message = str(error) if urlsplit(self.path).path == '/import-audio' else 'Некорректный запрос'
            return self.reply({'error': message}, 400)
        except (OSError, URLError):
            return self.reply({'error':'Служба записи временно недоступна'},503)
        try:
            value = json.loads(body) if body else {}
            if self.path == '/mirea-profile':
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
                return self.reply(mirea_schedule.set_profile(value))
            if self.path == '/start':
                return self.proxy(json.dumps(dict(value,choose_lesson=True)).encode())
            if self.path.startswith('/update-auth/'):
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error': 'Запрос отклонён'}, 403)
                actions = {'/update-auth/start': update_manager.AUTH.begin,
                           '/update-auth/cancel': update_manager.AUTH.cancel,
                           '/update-auth/disconnect': update_manager.AUTH.disconnect}
                if self.path not in actions: return self.reply({'error': 'Не найдено'}, 404)
                return self.reply(actions[self.path]())
            if self.path == '/imports/retry':
                result = self.server.importer.retry(value.get('id'))
                return self.reply({'id': result['id'], 'status': result['status']})
            if self.path == '/audio-enhancement':
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error': 'Запрос отклонён'}, 403)
                if self.server.reload_requested.is_set():
                    return self.reply({'error': 'Приложение перезапускается. Повтори после запуска.'}, 409)
                name = value.get('file')
                study_store.audio(name)
                with urlopen(self.server.service_url + '/status', timeout=5) as response:
                    status = json.load(response)
                if status.get('recording') and status.get('file') == name:
                    return self.reply({'error': 'Сначала останови запись, затем очисти звук.'}, 409)
                return self.reply(self.server.enhancer.request(name, value.get('profile', 'gentle')), 202)
            if self.path == '/transcript-review':
                name = value.get('file')
                study_store.audio(name)
                report = report_for(ROOT, name)
                if report is None:
                    raise ValueError('Расшифровка ещё не готова.')
                item = next((row for row in annotate(report)['segments'] if row['review_key'] == value.get('key')), None)
                if item is None:
                    return self.reply({'error': 'Текст изменился. Открой обновлённый фрагмент и проверь его ещё раз.'}, 409)
                if type(value.get('reviewed')) is not bool:
                    raise ValueError('Выбери состояние проверки.')
                with study_store.transaction():
                    notes = study_store.notes(name)
                    notes.setdefault('transcript_review', {})[item['review_key']] = {
                        'reviewed': value['reviewed'], 'updated': time.time()}
                    study_store.save(study_store.note_path(name), notes)
                return self.reply({'key': item['review_key'], 'reviewed': value['reviewed']})
            if self.path == '/quit-for-install':
                if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
                if self.server.reload_requested.is_set():
                    return self.reply({'error':'Приложение перезапускается. Повтори через несколько секунд.'},409)
                if self.server.pairing.public()['active']:
                    return self.reply({'error':'Заверши сопряжение телефона перед выходом.'},409)
                if self.server.importer.active() or self.server.enhancer.active():
                    return self.reply({'error': 'Дождись завершения загрузки и обработки звука перед выходом.'}, 409)
                try:
                    with urlopen(self.server.service_url+'/status',timeout=3) as response:status=json.load(response)
                except URLError:status={}
                if (status.get('recording') or status.get('busy') or any(j.get('status') in ('queued','processing') for j in status.get('ai',{}).get('jobs',{}).values())):
                    return self.reply({'error':'Дождись завершения записи и разбора перед выходом.'},409)
                update_manager.STOP.set()
                update_manager.stop_service(self.server.service_url)
                update_manager.stop_service('http://127.0.0.1:8768')
                self.reply({'ok':True})
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if self.path == '/phone-sync/retry':
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
                import phone_sync
                try:
                    return self.reply(phone_sync.request_retry(),202)
                except OSError:
                    return self.reply({'error':'Не удалось сохранить запрос на повтор.'},503)
            if self.path.startswith('/phone-pairing/'):
                if self.headers.get('Host') not in (f'127.0.0.1:{port}', f'localhost:{port}'):
                    return self.reply({'error':'Запрос отклонён'},403)
                if self.server.reload_requested.is_set():
                    return self.reply({'error':'Приложение перезапускается. Повтори через несколько секунд.'},409)
                pairing = self.server.pairing
                if self.path == '/phone-pairing/start': return self.reply(pairing.start())
                if self.path == '/phone-pairing/cancel':
                    pairing.close();return self.reply(pairing.public())
                if self.path == '/phone-pairing/approve':return self.reply(pairing.decide(value.get('request_id'),True))
                if self.path == '/phone-pairing/reject':return self.reply(pairing.decide(value.get('request_id'),False))
                if self.path == '/phone-pairing/forget':return self.reply(pairing.forget())
                return self.reply({'error':'Не найдено'},404)
            if self.path=='/board-photo-assign':
                with urlopen(self.server.service_url+'/status',timeout=5) as response:active=json.load(response)
                return self.reply(board_photos.assign(value.get('id'),value.get('file'),value.get('start',0),active))
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
        except PairingError as error:
            return self.reply({'error':str(error)},error.status)
        except (ValueError, TypeError, KeyError) as error:
            return self.reply({'error':str(error)},400)
        except (OSError, URLError) as error:
            return self.reply({'error':str(error)},503)
        if self.path == '/reload-app':
            if self.server.importer.active() or self.server.enhancer.active():
                return self.reply({'error': 'Дождись завершения подготовки и очистки звука перед обновлением.'}, 409)
            if self.server.pairing.public()['active']:
                return self.reply({'error':'Заверши или закрой сопряжение телефона перед перезапуском.'},409)
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
        if self.path == '/check-updates':
            update_manager.CHECK.set()
            return self.reply({'ok': True})
        if self.path in ('/stop', '/pair', '/check-wifi', '/setup-hotspot', '/ai-settings', '/analyze', '/recording-selection'):
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
            board_photos.start()
            update_manager.start(server)
        print(f'Application: http://127.0.0.1:{options.port}', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        update_manager.STOP.set()
        server.server_close()
    if server.install_requested:
        try:
            update_manager.stop_service(server.service_url)
            update_manager.stop_service('http://127.0.0.1:8768')
            update_manager.install()
        except Exception as error:
            update_manager.atomic(update_manager.PROJECT/'work/updates/hold.json', {'until': time.time()+3600, 'error': str(error)[:300]})
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])
    if server.reload_requested.is_set():
        os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]])


if __name__ == '__main__':
    main()
