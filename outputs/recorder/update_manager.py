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
from http.client import HTTPException
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen, build_opener, HTTPSHandler, HTTPRedirectHandler
from urllib.parse import urlsplit
from android_packages import ASSETS, STABLE, apk_identity, cache_folder
from phone_sync import digest as file_digest
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


def headers(token=None):
    value = {'User-Agent': 'LectureRecorder-Updater', 'Accept': 'application/vnd.github+json'}
    if token:
        value['Authorization'] = 'Bearer ' + token
    return value


def asset_digest(asset):
    digest, size = asset.get('digest'), asset.get('size')
    if (not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)
            or type(size) is not int or not 0 < size <= MAX_BYTES):
        raise ValueError('Нет проверяемой контрольной суммы обновления')
    return digest[7:]


def download_asset(asset, target, token=None):
    expected = asset_digest(asset)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.part')
    values = headers(token)
    values['Accept'] = 'application/octet-stream'
    try:
        asset_id = int(asset['id'])
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError('Некорректный идентификатор файла релиза') from error
    url = f'https://api.github.com/repos/{REPOSITORY}/releases/assets/{asset_id}'
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
        if size != asset['size'] or digest.hexdigest() != expected:
            raise ValueError('Контрольная сумма обновления не совпала')
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    return digest.hexdigest()


def cache_android_asset(asset, tag, package, folder, token=None):
    expected = asset_digest(asset)
    target = folder / 'update.apk'
    staged = folder / 'candidate.apk'
    cached = target.is_file() and target.stat().st_size == asset['size'] and file_digest(target) == expected
    try:
        if not cached:
            download_asset(asset, staged, token)
        actual, code = apk_identity(target if cached else staged)
        if actual != package:
            raise ValueError('Имя пакета в APK отличается от канала обновления')
        if not cached:
            staged.replace(target)
        meta = dict(tag=tag, package=package, code=code, digest=asset['digest'], size=asset['size'])
        if read(folder / 'ready.json') != meta:
            atomic(folder / 'ready.json', meta)
    finally:
        staged.unlink(missing_ok=True)


def cache_android(release, project=PROJECT, token=None):
    assets = {a.get('name'): a for a in release.get('assets', []) if isinstance(a, dict)}
    work = project / 'work'
    root = cache_folder(work, STABLE)
    root.mkdir(parents=True, exist_ok=True)
    available = False
    failed = []
    with (root / 'refresh.lock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        for package, name in ASSETS.items():
            folder = cache_folder(work, package)
            try:
                if name not in assets:
                    (folder / 'ready.json').unlink(missing_ok=True)
                    (folder / 'update.apk').unlink(missing_ok=True)
                    continue
                cache_android_asset(assets[name], release.get('tag_name'), package, folder, token)
                available = True
            except (ValueError, OSError, HTTPException):
                failed.append(name)
    messages = ['APK доступен сопряжённому телефону'] if available else []
    if failed:
        messages.append('Не удалось проверить ' + ', '.join(failed))
    return ' · '.join(messages) or 'В релизе нет APK для телефона'


def download_release(project=PROJECT):
    url = 'https://api.github.com/repos/' + REPOSITORY + '/releases/latest'
    token = None
    try:
        response = fetch(Request(url, headers=headers()), timeout=20)
    except HTTPError as error:
        if error.code not in (401, 403, 404, 429):
            raise
        error.close()
        try:
            token = os.environ.get('LECTURE_GITHUB_TOKEN') or AUTH.token()
        except ValueError:
            token = None
        if not token:
            if error.code in (403, 429):
                STATE.update(message='GitHub временно ограничил число запросов. Проверю обновления позже.')
            else:
                STATE.update(message='Войди в GitHub на этом Mac для закрытых обновлений')
            return
        response = fetch(Request(url, headers=headers(token)), timeout=20)
    with response:
        release = json.loads(response.read(2 * 1024 * 1024))
    if release.get('draft') or release.get('prerelease'):
        return
    apk_status = cache_android(release, project, token)
    tag = release.get('tag_name', '')
    if tag == 'v' + read(project / 'release.json').get('version', ''):
        STATE.update(message='На Mac последняя версия · ' + apk_status)
        return True
    asset = next((a for a in release.get('assets', []) if a['name'] == 'lecture-mac-update.zip'), None)
    if not asset:
        raise ValueError('В релизе пока нет обновления Mac')
    folder = project / 'work/updates'
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'candidate.zip'
    downloaded = folder / 'download.zip'
    digest = download_asset(asset, downloaded, token)
    meta, _ = inspect_package(downloaded, project)
    if tag != 'v' + meta['version']:
        raise ValueError('Версия пакета отличается от тега релиза')
    os.replace(downloaded, archive)
    atomic(folder / 'pending.json', dict(meta, sha256=digest))
    STATE.update(pending=True, version=meta['version'],
                 message='Обновление скачано · установлю после записи и обработки · ' + apk_status)


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


def idle_for_update(server):
    return (not (getattr(server, 'pairing', None) and server.pairing.public()['active'])
            and not (getattr(server, 'importer', None) and server.importer.active())
            and not (getattr(server, 'enhancer', None) and server.enhancer.active())
            and idle(server.service_url))


def start(server):
    from character_download import ModelRefresh
    refresh = ModelRefresh(PROJECT)
    AUTH.wake = CHECK.set
    def loop():
        last = -6 * 3600

        def interrupted():
            return STOP.is_set() or CHECK.is_set() or time.monotonic() - last >= 6 * 3600

        def model_idle():
            return not (PROJECT / 'work/updates/pending.json').exists() and idle_for_update(server)

        while not STOP.is_set():
            try:
                AUTH.poll()
                if time.monotonic() - last >= 6 * 3600 or CHECK.is_set():
                    CHECK.clear(); last = time.monotonic()
                    current = False
                    try:
                        current = download_release()
                    except HTTPError as e:
                        STATE.update(message='Релизы недоступны · нужен опубликованный релиз и доступ к репозиторию' if e.code == 404 else 'Проверю обновление позже')
                    except Exception as e:
                        STATE.update(message='Проверка отложена: ' + str(e)[:160])
                    refresh.after_check(current)
                if (read(PROJECT / 'work/updates/pending.json')
                        and read(PROJECT/'work/updates/hold.json').get('until',0) < time.time()
                        and idle_for_update(server)):
                    server.install_requested = True
                    server.shutdown()
                    return
                refresh.poll(fetch, model_idle, interrupted)
            except HTTPError as e:
                STATE.update(message='Релизы недоступны · нужен опубликованный релиз и доступ к репозиторию' if e.code == 404 else 'Проверю обновление позже')
            except Exception as e:
                STATE.update(message='Обновление отложено: ' + str(e)[:160])
            STOP.wait(10)
    threading.Thread(target=loop, daemon=True, name='Release updates').start()
