import json
import os
import queue
import signal
import subprocess
import threading
import lesson_schedule
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent.parent
RESULTS = ROOT / 'analysis'
RESULTS.mkdir(exist_ok=True)
CONFIG = PROJECT / 'work' / 'ai-settings.json'
PYTHON = PROJECT / 'work' / 'ai-env' / 'bin' / 'python'
tasks = queue.Queue()
lock = threading.Lock()
pending = set()
process = None
stopping = False
configuration = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
auto = configuration.get('auto', True)
speech = configuration.get('speech', 'whisper')
paused = configuration.get('paused', False)
economical = configuration.get('economical', True)

def save_settings():
    write(CONFIG, {'auto':auto, 'speech':speech, 'paused':paused, 'economical':economical})

def set_economical(value):
    global economical
    economical = bool(value)
    save_settings()

def set_paused(value):
    global paused
    with lock:
        paused = bool(value)
        if process and process.poll() is None:
            process.send_signal(signal.SIGSTOP if paused else signal.SIGCONT)
        save_settings()
ASR_PYTHON = PROJECT/'work/asr-env/bin/python'
def qwen_ready():
    from quality_asr import ready
    return PYTHON.exists() and ready()


def file_path(name):
    if not isinstance(name, str) or Path(name).name != name or '/' in name or '\\' in name or not name.endswith('.wav'):
        raise ValueError('Некорректное имя записи.')
    path = ROOT / 'recordings' / name
    if not path.is_file():
        raise ValueError('Запись не найдена.')
    return path


def paths(name):
    stem = Path(name).stem
    return RESULTS / (stem + '.json'), RESULTS / (stem + '.progress.json')


def write(path, value):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


def status():
    jobs = {}
    for progress in RESULTS.glob('*.progress.json'):
        try:
            jobs[progress.name.removesuffix('.progress.json') + '.wav'] = json.loads(progress.read_text())
        except (ValueError, OSError):
            pass
    return {'auto':auto, 'speech':speech, 'paused':paused, 'economical':economical, 'qwen_ready':qwen_ready(), 'ready':PYTHON.exists() and (PROJECT / 'work/models/manifest.json').exists(), 'jobs':jobs}


def set_auto(value):
    global auto
    auto = bool(value)
    save_settings()


def set_speech(value):
    global speech
    if value not in ('whisper','qwen'):
        raise ValueError('Неизвестная модель речи.')
    if value=='qwen' and not qwen_ready():
        raise ValueError('Модель русской речи ещё не готова.')
    speech=value
    save_settings()


def submit(name, wait_models=False):
    file_path(name)
    if not wait_models and not status()['ready']:
        raise RuntimeError('Локальные модели ещё не готовы.')
    with lock:
        if name in pending:
            return
        pending.add(name)
        _, progress = paths(name)
        write(progress, {'status':'queued','stage':'queued','percent':0,'message':'Ожидает обработки на Mac'})
        tasks.put(name)


def run_queue():
    global process
    while not stopping:
        name = tasks.get()
        if name is None:
            return
        result, progress = paths(name)
        try:
            if stopping:
                break
            while (paused or not status()['ready']) and not stopping:
                write(progress, {'status':'queued','stage':'queued','percent':0,'message':'Разбор на паузе' if paused else 'Ожидаю загрузки локальных моделей'})
                threading.Event().wait(1)
            if stopping:
                break
            write(progress, {'status':'processing','stage':'loading','percent':1,'message':'Загружаю локальные модели'})
            env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1')
            logs = PROJECT / 'work' / 'ai-logs'
            logs.mkdir(exist_ok=True)
            with (logs / (Path(name).stem + '.log')).open('w') as log:
                def execute(arguments):
                    global process
                    child = subprocess.Popen(arguments, env=env, stdout=log, stderr=log)
                    with lock:
                        process=child
                        if paused:child.send_signal(signal.SIGSTOP)
                        if stopping:
                            child.terminate()
                            child.send_signal(signal.SIGCONT)
                    return child.wait()
                code=0
                if speech=='qwen':
                    if not qwen_ready():raise RuntimeError('Модель русской речи ещё не готова.')
                    code=execute([str(ASR_PYTHON),str(ROOT/'qwen_transcribe.py'),str(file_path(name)),str(result),str(progress)])
                else:
                    transcript=result.with_suffix('.transcript.json')
                    if transcript.exists() and json.loads(transcript.read_text()).get('engine','').startswith('Qwen'):
                        transcript.replace(transcript.with_suffix('.qwen-backup.json'))
                if code==0 and not stopping:
                    code=execute([str(PYTHON),str(ROOT/'ai_worker.py'),str(file_path(name)),str(result),str(progress)])
            data = json.loads(progress.read_text()) if progress.exists() else {}
            if code == 0:
                lesson_schedule.organize(name)
            if code and data.get('status') != 'error':
                write(progress, {'status':'error','stage':'error','percent':0,'message':'Обработка прервана. Можно запустить повторно.'})
        except Exception as exc:
            write(progress, {'status':'error','stage':'error','percent':0,'message':str(exc)[:1000]})
        finally:
            with lock:
                pending.discard(name)
                process = None
            tasks.task_done()


def shutdown():
    global stopping
    with lock:
        stopping = True
        if process and process.poll() is None:
            process.terminate()
            process.send_signal(signal.SIGCONT)
    tasks.put(None)


for path in RESULTS.glob('*.progress.json'):
    try:
        data = json.loads(path.read_text())
        if data.get('status') in ('processing','queued'):
            if auto:
                submit(path.name.removesuffix('.progress.json') + '.wav', wait_models=True)
            else:
                write(path, {'status':'error','stage':'error','percent':0,'message':'Приложение было закрыто. Запусти разбор повторно.'})
    except (ValueError, OSError):
        pass
threading.Thread(target=run_queue, daemon=True).start()
