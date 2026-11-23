import argparse
import json
import subprocess
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from urllib.request import urlopen
from .corpus import Corpus

ROOT=Path(__file__).resolve().parent
CORPUS=Corpus(ROOT.parent,ROOT.parents[2]/'work/custom-ai')
JOB_LOCK=threading.Lock()
JOB=None

def job_status():
    with JOB_LOCK:
        if JOB is None:return dict(running=False,started=False)
        process,path,task=JOB
        lines=path.read_text(errors='replace').splitlines() if path.exists() else []
        message=''
        for line in reversed(lines):
            try:
                value=json.loads(line)
                message=f"Шаг обучения: {value['epoch']}."
                if value.get('word_error_rate') is not None:
                    message+=f" Ошибки слов на контрольных занятиях: {value['word_error_rate']*100:.1f}%."
                break
            except (ValueError,TypeError,KeyError):continue
        if process.poll() not in (None,0):
            last=lines[-1] if lines else ''
            message=last if last and any('А'<=c<='я' for c in last) and 'Error' not in last else 'Эксперимент остановлен. Журнал сохранён на Mac.'
        return dict(running=process.poll() is None,started=True,task=task,exit_code=process.poll(),message=message)

def start_training(task):
    global JOB
    if task not in ('speech','notes'):raise ValueError('Выбери одну из двух моделей')
    with JOB_LOCK:
        if JOB is not None and JOB[0].poll() is None:raise ValueError('Обучение уже идёт')
        if CORPUS.status()['examples']<20:raise ValueError('Сначала проверь хотя бы 20 фрагментов')
        inactive(None)
        path=CORPUS.root/'training.log'
        with path.open('wb') as log:
            process=subprocess.Popen([sys.executable,'-m','custom_ai.train',task],cwd=ROOT.parent,
                                     stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        JOB=(process,path,task)

def stop_training():
    with JOB_LOCK:
        if JOB is not None and JOB[0].poll() is None:JOB[0].terminate()

def inactive(name):
    with urlopen('http://127.0.0.1:8765/status',timeout=3) as response:status=json.load(response)
    if (status.get('recording') or status.get('busy')) and (name is None or status.get('file')==name):
        raise ValueError('Этот файл сейчас записывается. Выбери сохранённую запись.')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def allowed(self):
        port=self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}',f'localhost:{port}') and self.headers.get('Origin') in (None,f'http://127.0.0.1:{port}',f'http://localhost:{port}')
    def reply(self,value,status=200,mime='application/json; charset=utf-8'):
        data=json.dumps(value,ensure_ascii=False).encode() if isinstance(value,dict) else value
        self.send_response(status);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self.allowed():return self.reply({'error':'Запрос отклонён'},403)
        try:
            route=urlsplit(self.path)
            if route.path=='/':return self.reply((ROOT/'index.html').read_bytes(),mime='text/html; charset=utf-8')
            if route.path=='/status':return self.reply(dict(**CORPUS.status(),workspace='custom-ai-v1',recordings=CORPUS.recordings(),job=job_status()))
            if route.path=='/clip':
                query=parse_qs(route.query);name=query.get('file',[''])[0];inactive(name)
                return self.reply(CORPUS.clip(name,query.get('start',[''])[0],query.get('end',[''])[0]),mime='audio/wav')
            return self.reply({'error':'Не найдено'},404)
        except (ValueError,TypeError,KeyError,wave.Error,EOFError):return self.reply({'error':'Проверь запись и время фрагмента'},400)
        except OSError:return self.reply({'error':'Служба записи или файл недоступны'},503)
    def do_POST(self):
        if not self.allowed():return self.reply({'error':'Запрос отклонён'},403)
        try:
            if self.path not in ('/review','/train','/stop'):return self.reply({'error':'Не найдено'},404)
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384:raise ValueError('Слишком большой запрос')
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict):raise ValueError('Некорректный запрос')
            if self.path=='/stop':
                stop_training()
                return self.reply(dict(ok=True))
            if self.path=='/train':
                start_training(body.get('task'))
                return self.reply(dict(ok=True))
            inactive(body.get('file'))
            return self.reply(dict(ok=True,example=CORPUS.review(body)))
        except (ValueError,TypeError,KeyError,wave.Error,EOFError) as error:return self.reply({'error':str(error)},400)
        except OSError:return self.reply({'error':'Не удалось прочитать или сохранить пример'},503)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8769)
    args=parser.parse_args()
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
if __name__=='__main__':main()
