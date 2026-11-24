import sys
sys.dont_write_bytecode = True

import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import ssl
import stat
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

setup_modules = Path(__file__).resolve().parent
source_modules = setup_modules.parent / 'outputs/recorder'
sys.path.insert(0, str(setup_modules if (setup_modules / 'app_shortcut.py').is_file() else source_modules))
from app_shortcut import install_shortcut

CANCEL = threading.Event()
OUTPUT = threading.Lock()


class InstallError(Exception):
    pass


class Cancelled(InstallError):
    pass


def check_cancel():
    if CANCEL.is_set():
        raise Cancelled('Установка приостановлена. Нажми «Продолжить», когда будет удобно.')


def emit(stage, detail, progress=None, **values):
    with OUTPUT:
        print(json.dumps(dict(stage=stage, detail=detail, progress=progress, **values), ensure_ascii=False), flush=True)


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            check_cancel()
            result.update(block)
    return result.hexdigest()


def payload_allowed(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name:
        return False
    if name == 'release.json':
        return True
    if path.parts[:2] == ('outputs', 'recorder'):
        if len(path.parts) == 3:
            return path.suffix in ('.py', '.js', '.html', '.txt') or path.name == 'schedule.example.json'
        return path.parts[2] == 'vendor'
    return (len(path.parts) >= 4 and path.parts[0] == 'outputs'
            and path.parts[1] in ('Запись лекций.app', 'Синхронизация Bluetooth.app')
            and path.parts[2] == 'Contents')


def install_payload(archive, root):
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        if len(entries) > 1200 or len({e.filename for e in entries}) != len(entries):
            raise InstallError('Повреждён пакет приложения.')
        if sum(e.file_size for e in entries) > 100 * 1024 * 1024:
            raise InstallError('Повреждён пакет приложения.')
        for entry in entries:
            target = root / entry.filename
            if (not payload_allowed(entry.filename) or stat.S_ISLNK(entry.external_attr >> 16)
                    or not target.resolve().is_relative_to(root.resolve()) or target.is_symlink()):
                raise InstallError('Недопустимый файл пакета приложения.')
        for entry in entries:
            check_cancel()
            target = root / entry.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=target.parent, prefix='.install-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(bundle.read(entry))
                os.chmod(name, (entry.external_attr >> 16) & 0o777 or 0o644)
                os.replace(name, target)
            finally:
                Path(name).unlink(missing_ok=True)


def run(command, log, env, cwd=None):
    check_cancel()
    with log.open('ab') as output:
        output.write(('\n' + Path(command[0]).name + ' · ' + time.strftime('%Y-%m-%d %H:%M:%S') + '\n').encode())
        output.flush()
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   env=env, cwd=cwd, start_new_session=True)
        try:
            while process.poll() is None:
                if CANCEL.wait(.2):
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    check_cancel()
            if process.returncode:
                raise InstallError('Не удалось подготовить компоненты. Проверь интернет и нажми «Продолжить». Подробности доступны в журнале.')
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait()


def download(url, target, size, sha, progress, context=None):
    if target.is_file() and target.stat().st_size == size and digest(target) == sha:
        progress(size)
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.download')
    identity = part.with_name(part.name + '.json')
    expected = dict(bytes=size, sha256=sha)
    if read(identity) != expected or (part.exists() and part.stat().st_size > size):
        part.unlink(missing_ok=True)
    atomic(identity, expected)
    for attempt in range(4):
        check_cancel()
        offset = part.stat().st_size if part.exists() else 0
        try:
            if offset < size:
                headers = {'User-Agent': 'LectureRecorder-Installer'}
                if offset:
                    headers['Range'] = f'bytes={offset}-'
                request = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(request, context=context, timeout=30) as response:
                    if offset and response.status != 206:
                        offset = 0
                    if response.status == 206 and response.headers.get('Content-Range') != f'bytes {offset}-{size-1}/{size}':
                        raise InstallError('Источник вернул неверное продолжение загрузки.')
                    with part.open('ab' if offset else 'wb') as output:
                        try:
                            while block := response.read(1024 * 1024):
                                check_cancel()
                                offset += len(block)
                                if offset > size:
                                    raise InstallError('Размер загружаемого файла изменился.')
                                output.write(block)
                                progress(offset)
                        finally:
                            output.flush()
                            os.fsync(output.fileno())
            if offset != size:
                raise OSError('Incomplete download')
            if digest(part) != sha:
                part.unlink(missing_ok=True)
                raise OSError('Checksum mismatch')
            os.replace(part, target)
            identity.unlink(missing_ok=True)
            progress(size)
            return
        except (OSError, urllib.error.URLError) as error:
            if attempt == 3:
                raise InstallError('Загрузка прервалась. Проверь интернет и нажми «Продолжить»: сохранённая часть будет использована снова.') from error
            CANCEL.wait(min(2 ** attempt, 4))
    check_cancel()


def download_models(resources, root):
    models = read(resources / 'models.json')
    total = sum(file['bytes'] for model in models for file in model['files'])
    amounts = {}
    lock = threading.Lock()
    last = [0]
    labels = {'gigaam': 'Русская речь', 'gigaam-rnnt': 'Проверка речи', 'gigaam-beam': 'Проверка слов',
              'whisper': 'Распознавание', 'lecture': 'Конспекты', 'board-vision': 'Фото доски',
              'search': 'Поиск по лекциям', 'speakers': 'Голоса преподавателей'}
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else ssl.create_default_context()
    def one(model):
        folder = model['folder']
        for file in model['files']:
            name, size, sha = file['name'], file['bytes'], file['sha256']
            if (not re.fullmatch(r'[a-z0-9-]+', folder) or PurePosixPath(name).name != name
                    or not re.fullmatch(r'[a-f0-9]{40}', model['revision'])
                    or not re.fullmatch(r'[a-f0-9]{64}', sha) or type(size) is not int or size < 0):
                raise InstallError('Повреждён список моделей.')
            key = folder + '/' + name
            def progress(count):
                with lock:
                    amounts[key] = count
                    now = time.monotonic()
                    if now - last[0] >= .3 or count == size:
                        current = sum(amounts.values())
                        emit('Модели для лекций', f'{labels[folder]} · {current / 1e9:.2f} из {total / 1e9:.2f} ГБ',
                             20 + 73 * current / max(1, total), downloaded=current, total=total)
                        last[0] = now
            url = 'https://huggingface.co/' + model['repo'] + '/resolve/' + model['revision'] + '/' + urllib.parse.quote(name)
            download(url, root / 'work/models' / folder / name, size, sha, progress, context)
        atomic(root / 'work/models' / (folder + '-manifest.json'), model)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(one, model) for model in models]
        try:
            for future in concurrent.futures.as_completed(futures):
                future.result()
        except Exception:
            CANCEL.set()
            raise
    atomic(root / 'work/models/manifest.json', {model['folder']: {'repo': model['repo'], 'revision': model['revision']}
                                               for model in models if model['folder'] in ('lecture', 'whisper')})


def stop_managed_services(root):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8767/app-info', timeout=2) as response:
            info = json.load(response)
    except urllib.error.HTTPError as error:
        raise InstallError('Порт приложения занят другой программой.') from error
    except OSError:
        info = None
    if info is not None:
        if info.get('project') != str(root.resolve()):
            raise InstallError('Уже запущена другая копия приложения. Заверши её работу через меню приложения, затем продолжи установку.')
        try:
            request = urllib.request.Request('http://127.0.0.1:8767/quit-for-install', data=b'{}', headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=20) as response:
                if not json.load(response).get('ok'):
                    raise InstallError('Не удалось закрыть приложение.')
        except urllib.error.HTTPError as error:
            message = ('Сейчас идёт запись, разбор или сопряжение. Дождись завершения и нажми «Продолжить».' if error.code == 409
                       else 'Сервисы приложения не завершили работу. Нажми «Продолжить», чтобы повторить.')
            raise InstallError(message) from error
    until = time.monotonic() + 8
    while True:
        occupied = []
        for port in (8765, 8767, 8768):
            try:
                with socket.create_connection(('127.0.0.1', port), timeout=.3):
                    occupied.append(port)
            except OSError:
                pass
        if not occupied:
            return
        if info is None or time.monotonic() > until:
            raise InstallError('Сервисы приложения ещё работают. Выбери «Завершить работу» в меню приложения и повтори установку.')
        check_cancel()
        CANCEL.wait(.2)


def install(resources, support, applications, installer_app=None):
    support.mkdir(parents=True, exist_ok=True, mode=0o700)
    root = support / 'project'
    root.mkdir(exist_ok=True)
    updates = root / 'work/updates'
    updates.mkdir(parents=True, exist_ok=True)
    with (support / 'install.lock').open('a') as guard, (updates / 'install.lock').open('a') as update_guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError('Установка уже открыта в другом окне.')
        try:
            fcntl.flock(update_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError('Сейчас устанавливается обновление приложения. Повтори через несколько секунд.')
        metadata = read(resources / 'manifest.json')
        for name, sha in metadata['files'].items():
            if PurePosixPath(name).name != name or digest(resources / name) != sha:
                raise InstallError('Файлы установщика повреждены. Скачай пакет заново.')
        current = read(root / 'release.json')
        if current.get('code', 0) > metadata['code']:
            raise InstallError('Уже установлена более новая версия. Открой приложение из папки приложений.')
        if shutil.disk_usage(support).free < metadata['required_free_bytes']:
            raise InstallError('Для установки нужно не менее 22 ГБ свободного места. Освободи место и нажми «Продолжить».')
        emit('Подготовка', 'Сохраняю приложение в твоём профиле Mac', 1)
        stop_managed_services(root)
        atomic(support / 'install-state.json', dict(status='installing', code=metadata['code']))
        install_payload(resources / 'payload.zip', root)
        runtime = support / ('python-' + metadata['python_version'])
        if not (runtime / '.complete').exists():
            stage = support / (runtime.name + '.incoming')
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(resources / 'python', stage, symlinks=True)
            if runtime.exists():
                shutil.rmtree(runtime)
            stage.rename(runtime)
            (runtime / '.complete').write_text(metadata['python_version'])
        python = runtime / 'bin/python3.12'
        work = root / 'work'
        work.mkdir(exist_ok=True)
        log = support / 'install.log'
        env = dict(os.environ, UV_SYSTEM_CERTS='true', UV_NO_PROGRESS='1', UV_PYTHON_DOWNLOADS='never',
                   UV_CACHE_DIR=str(support / 'cache'), HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_XET='1',
                   PYTHONNOUSERSITE='1', PYTHONUNBUFFERED='1')
        for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE'):
            env.pop(key, None)
        uv = resources / 'uv'
        for index, (name, label) in enumerate((('recorder', 'Запись и подключение телефона'), ('ai', 'Распознавание и конспекты'), ('vision', 'Чтение фото доски'))):
            directory = work / {'recorder': 'esp-check-env', 'ai': 'ai-env', 'vision': 'vision-env'}[name]
            emit('Компоненты приложения', label, 3 + 5 * index)
            if not (directory / 'bin/python').exists():
                run([str(uv), '--no-config', 'venv', '--python', str(python), '--no-python-downloads', str(directory)], log, env)
            run([str(uv), '--no-config', 'pip', 'sync', '--python', str(directory / 'bin/python'), '--require-hashes', '--only-binary', ':all:', str(resources / ('requirements-' + name + '.lock'))], log, env)
        asr = work / 'asr-env'
        if not asr.exists() and not asr.is_symlink():
            asr.symlink_to('ai-env', target_is_directory=True)
        download_models(resources, root)
        emit('Проверка', 'Проверяю компоненты и локальные модели', 94)
        env.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        for name, mode in (('esp-check-env', 'recorder'), ('ai-env', 'ai'), ('vision-env', 'vision')):
            run([str(work / name / 'bin/python'), str(resources / 'verify.py'), str(root), mode], log, env)
        for name in ('Запись лекций', 'Синхронизация Bluetooth'):
            run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(root / 'outputs' / (name + '.app'))], log, env)
        if installer_app and installer_app.resolve() != (support / installer_app.name).resolve():
            incoming = support / (installer_app.name + '.incoming')
            if incoming.exists():
                shutil.rmtree(incoming)
            shutil.copytree(installer_app, incoming, symlinks=True)
            destination = support / installer_app.name
            if destination.exists():
                shutil.rmtree(destination)
            incoming.rename(destination)
        link = install_shortcut(root, applications)
        atomic(support / 'install-state.json', dict(status='complete', code=metadata['code'], version=metadata['version'],
                                                    application=str(link), project=str(root), completed=int(time.time())))
        emit('Готово', 'Приложение установлено. Можно подключить телефон и открыть библиотеку.', 100, complete=True, application=str(root / 'outputs/Запись лекций.app'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--support', type=Path, required=True)
    parser.add_argument('--applications', type=Path, required=True)
    parser.add_argument('--installer-app', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    signal.signal(signal.SIGTERM, lambda *_: CANCEL.set())
    signal.signal(signal.SIGINT, lambda *_: CANCEL.set())
    try:
        install(args.resources, args.support, args.applications, args.installer_app)
    except Exception as error:
        message = str(error) if isinstance(error, InstallError) else 'Установку пока не удалось завершить. Нажми «Продолжить»; сохранённые записи останутся на месте.'
        emit('Установка приостановлена' if isinstance(error, Cancelled) else 'Не удалось завершить установку', message,
             error=True, cancelled=isinstance(error, Cancelled))
        if not isinstance(error, Cancelled):
            import traceback
            args.support.mkdir(parents=True, exist_ok=True)
            with (args.support / 'install.log').open('a') as log:
                traceback.print_exc(file=log)
        return 2 if isinstance(error, Cancelled) else 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
