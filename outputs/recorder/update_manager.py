import ast
import contextlib
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import ssl
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlsplit
from update_auth import AUTH

PROJECT = Path(__file__).resolve().parents[2]
REPOSITORY = 'lecture-recorder-ilya/lecture-recorder-esp32-s3'
MAX_BYTES = 80 * 1024 * 1024
STATE = {'message': 'Проверка обновлений при подключении к интернету', 'pending': False}
STOP = threading.Event()
CHECK = threading.Event()


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme != 'https':
            raise ValueError('Небезопасное перенаправление обновления')
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        if result is not None and urlsplit(req.full_url).netloc != urlsplit(newurl).netloc:
            result.remove_header('Authorization')
        return result


def fetch(request, **options):
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else ssl.create_default_context()
    return build_opener(HTTPSHandler(context=context), ReleaseRedirect()).open(request, **options)


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w') as out:
        json.dump(value, out, ensure_ascii=False)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)


def allowed(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or str(p) != name:
        return False
    if name == 'release.json':
        return True
    if len(p.parts) == 3 and p.parts[:2] == ('outputs', 'recorder'):
        return p.suffix in ('.py', '.js', '.html')
    if p.parts[:3] == ('outputs', 'recorder', 'vendor'):
        return p.suffix in ('.js', '.mjs', '.css', '.svg', '.woff', '.woff2', '.ttf', '.md')
    app = (len(p.parts) >= 4 and p.parts[0] == 'outputs'
           and p.parts[1] in ('Запись лекций.app', 'Синхронизация Bluetooth.app')
           and p.parts[2] == 'Contents')
    return app and ((len(p.parts) >= 5 and p.parts[3] in ('MacOS', 'Resources', '_CodeSignature'))
                    or (len(p.parts) == 4 and p.parts[3] == 'Info.plist'))


def inspect_package(archive, project=PROJECT):
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        names = [i.filename for i in entries]
        if len(names) != len(set(names)) or len(names) > 1000:
            raise ValueError('Повторяющиеся файлы обновления')
        if sum(i.file_size for i in entries) > MAX_BYTES:
            raise ValueError('Обновление слишком большое')
        for i in entries:
            if not allowed(i.filename) or stat.S_ISLNK(i.external_attr >> 16):
                raise ValueError('Недопустимый путь обновления: ' + i.filename)
            target = project / i.filename
            if not target.resolve().is_relative_to(project.resolve()) or target.is_symlink():
                raise ValueError('Символическая ссылка в месте обновления')
            if i.filename.endswith('.py'):
                ast.parse(z.read(i), filename=i.filename)
        meta = json.loads(z.read('release.json'))
        current = read(project / 'release.json')
        if (not isinstance(meta.get('version'), str) or not meta['version']
                or type(meta.get('code')) is not int or meta['code'] <= current.get('code', 0)
                or meta.get('runtime') != current.get('runtime', 1)
                or meta.get('repository') != REPOSITORY):
            raise ValueError('Несовместимая или устаревшая версия обновления')
        for required in ('outputs/recorder/app_server.py', 'outputs/recorder/recorder.py',
                         'outputs/recorder/update_manager.py'):
            if required not in names:
                raise ValueError('Неполное обновление')
        return meta, names


def headers():
    value = {'User-Agent': 'LectureRecorder-Updater', 'Accept': 'application/vnd.github+json'}
    token = os.environ.get('LECTURE_GITHUB_TOKEN') or AUTH.token()
    if token:
        value['Authorization'] = 'Bearer ' + token
    return value


def download_asset(asset, target):
    expected = asset.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', expected) or not 0 < asset.get('size', 0) <= MAX_BYTES:
        raise ValueError('Нет проверяемой контрольной суммы обновления')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.part')
    values = headers()
    values['Accept'] = 'application/octet-stream'
    url = f'https://api.github.com/repos/{REPOSITORY}/releases/assets/{int(asset["id"])}'
    digest, size = hashlib.sha256(), 0
    try:
        with fetch(Request(url, headers=values), timeout=60) as response, temp.open('wb') as out:
            for block in iter(lambda: response.read(65536), b''):
                size += len(block)
                if size > asset['size']: raise ValueError('Размер обновления изменился')
                digest.update(block)
                out.write(block)
            out.flush()
            os.fsync(out.fileno())
        if size != asset['size'] or digest.hexdigest() != expected[7:]:
            raise ValueError('Контрольная сумма обновления не совпала')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return digest.hexdigest()


def cache_android(release, project=PROJECT):
    asset = next((a for a in release.get('assets', []) if a.get('name') == 'lecture-recorder.apk'), None)
    if not asset: return
    folder = project/'work/updates/android'
    target = folder/'update.apk'
    cached = read(folder/'ready.json')
    expected = asset.get('digest', '')
    if (cached.get('digest') == expected and target.is_file()
            and hashlib.sha256(target.read_bytes()).hexdigest() == expected.removeprefix('sha256:')): return
    download_asset(asset, target)
    with zipfile.ZipFile(target) as apk:
        if 'AndroidManifest.xml' not in apk.namelist():
            target.unlink(missing_ok=True)
            raise ValueError('Получен некорректный APK')
    atomic(folder/'ready.json', dict(tag=release.get('tag_name'), digest=expected, size=asset['size']))


def download_release(project=PROJECT):
    if not headers().get('Authorization'):
        STATE.update(message='Войди в GitHub на этом Mac для закрытых обновлений')
        return
    url = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
    with fetch(Request(url, headers=headers()), timeout=20) as response:
        release = json.loads(response.read(2 * 1024 * 1024))
    if release.get('draft') or release.get('prerelease'):
        return
    cache_android(release, project)
    tag = release.get('tag_name', '')
    if tag == 'v' + read(project / 'release.json').get('version', ''):
        STATE.update(message='На Mac последняя версия · APK доступен сопряжённому телефону')
        return
    asset = next((a for a in release.get('assets', []) if a['name'] == 'lecture-mac-update.zip'), None)
    if not asset:
        raise ValueError('В релизе пока нет обновления Mac')
    folder = project / 'work/updates'
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'candidate.zip'
    downloaded = folder / 'download.zip'
    digest = download_asset(asset, downloaded)
    meta, _ = inspect_package(downloaded, project)
    if tag != 'v' + meta['version']:
        raise ValueError('Версия пакета отличается от тега релиза')
    os.replace(downloaded, archive)
    atomic(folder / 'pending.json', dict(meta, sha256=digest))
    STATE.update(pending=True, version=meta['version'], message='Обновление скачано · установлю после записи и обработки')


def idle(service_url):
    try:
        with urlopen(service_url + '/status', timeout=3) as response:
            s = json.load(response)
        return not (s.get('recording') or s.get('busy') or any(
            j.get('status') in ('queued', 'processing') for j in s.get('ai', {}).get('jobs', {}).values()))
    except (OSError, ValueError):
        return False


def stop_service(base):
    status_url = base + ('/study-status' if base.endswith(':8768') else '/status')
    try:
        with urlopen(Request(base + '/shutdown-for-update', data=b'{}',
                             headers={'Content-Type': 'application/json'}), timeout=5) as r:
            if not json.load(r).get('ok'):
                raise RuntimeError('Сервис занят')
    except HTTPError:
        raise
    except OSError:
        try:
            with urlopen(status_url, timeout=1):
                pass
        except HTTPError:
            raise
        except OSError:
            return
        raise
    for _ in range(100):
        try:
            with urlopen(status_url, timeout=.3):
                pass
        except HTTPError:
            pass
        except OSError:
            return
        time.sleep(.1)
    raise RuntimeError('Сервис ещё завершает работу')


@contextlib.contextmanager
def install_lock(project):
    folder = project / 'work/updates'
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'install.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        yield


def recover(project=PROJECT):
    with install_lock(project):
        _recover(project)


def _recover(project):
    folder = project / 'work/updates'
    journal = read(folder / 'transaction.json')
    if not journal:
        return
    for name, existed in journal['files'].items():
        if not allowed(name):
            raise ValueError('Некорректный журнал обновления')
        target = project / name
        if not target.resolve().is_relative_to(project.resolve()) or target.is_symlink():
            raise ValueError('Ссылка в журнале обновления')
        if existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(folder / 'backup' / name, target)
        else:
            target.unlink(missing_ok=True)
    (folder / 'transaction.json').unlink()


def install(project=PROJECT):
    with install_lock(project):
        return _install(project)


def _install(project):
    folder = project / 'work/updates'
    _recover(project)
    pending = read(folder / 'pending.json')
    archive = folder / 'candidate.zip'
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pending.get('sha256'):
        raise ValueError('Скачанный архив изменился')
    meta, names = inspect_package(archive, project)
    backup = folder / 'backup'
    if backup.exists():
        shutil.rmtree(backup)
    original = {}
    for name in names:
        target = project / name
        original[name] = target.exists()
        if target.exists():
            dest = backup / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
    atomic(folder / 'transaction.json', {'files': original})
    try:
        with zipfile.ZipFile(archive) as z:
            for name in names:
                target = project / name
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + '.update-tmp')
                with temp.open('wb') as out:
                    out.write(z.read(name)); out.flush(); os.fsync(out.fileno())
                mode = (z.getinfo(name).external_attr >> 16) & 0o777
                temp.chmod(mode or 0o644)
                os.replace(temp, target)
        (folder / 'pending.json').unlink()
        (folder / 'transaction.json').unlink()
    except Exception:
        _recover(project)
        raise
    return meta


def start(server):
    AUTH.wake = CHECK.set
    def loop():
        last = -6 * 3600
        while not STOP.is_set():
            try:
                AUTH.poll()
                if time.monotonic() - last >= 6 * 3600 or CHECK.is_set():
                    CHECK.clear(); last = time.monotonic()
                    try:
                        download_release()
                    except HTTPError as e:
                        STATE.update(message='Релизы недоступны · нужен опубликованный релиз и доступ к репозиторию' if e.code == 404 else 'Проверю обновление позже')
                    except Exception as e:
                        STATE.update(message='Проверка отложена: ' + str(e)[:160])
                if (read(PROJECT / 'work/updates/pending.json')
                        and read(PROJECT/'work/updates/hold.json').get('until',0) < time.time()
                        and not (getattr(server, 'pairing', None) and server.pairing.public()['active'])
                        and not (getattr(server, 'importer', None) and server.importer.active())
                        and not (getattr(server, 'enhancer', None) and server.enhancer.active())
                        and idle(server.service_url)):
                    server.install_requested = True
                    server.shutdown()
                    return
            except HTTPError as e:
                STATE.update(message='Релизы недоступны · нужен опубликованный релиз и доступ к репозиторию' if e.code == 404 else 'Проверю обновление позже')
            except Exception as e:
                STATE.update(message='Обновление отложено: ' + str(e)[:160])
            STOP.wait(10)
    threading.Thread(target=loop, daemon=True, name='Release updates').start()
