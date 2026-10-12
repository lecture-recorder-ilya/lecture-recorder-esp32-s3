import argparse
import hashlib
import json
import os
import plistlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'installer'))
from install import payload_allowed


def fetch(url, path):
    context = ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else ssl.create_default_context()
    with urllib.request.urlopen(url, context=context, timeout=60) as response, path.open('wb') as output:
        shutil.copyfileobj(response, output)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--uv', type=Path)
    parser.add_argument('--python-runtime', type=Path)
    parser.add_argument('--skip-dmg', action='store_true')
    args = parser.parse_args()
    distribution = json.loads((ROOT / 'installer/distribution.json').read_text())
    version = json.loads((ROOT / 'release.json').read_text())
    work = ROOT / 'work/installer'
    work.mkdir(parents=True, exist_ok=True)
    tools = ROOT / 'work/installer-tools'
    tools.mkdir(parents=True, exist_ok=True)
    uv = args.uv or tools / 'uv'
    if not uv.exists():
        archive = tools / 'uv.tar.gz'
        fetch(distribution['uv_url'], archive)
        if sha(archive) != distribution['uv_sha256']:
            raise ValueError('Неверная контрольная сумма uv')
        with tarfile.open(archive) as bundle:
            member = next(m for m in bundle.getmembers() if m.name.endswith('/uv') and m.isfile())
            uv.write_bytes(bundle.extractfile(member).read())
        uv.chmod(0o755)
    env = dict(os.environ, UV_SYSTEM_CERTS='true', UV_PYTHON_INSTALL_DIR=str(tools / 'python'))
    runtime = args.python_runtime
    if runtime is None:
        subprocess.run([str(uv), '--no-config', 'python', 'install', '--no-bin', '--managed-python', distribution['python_version']], env=env, check=True)
        runtime = tools / 'python' / ('cpython-' + distribution['python_version'] + '-macos-aarch64-none')
    subprocess.run([sys.executable, str(ROOT / 'tools/build_mac.py')], check=True)
    app = work / 'Установить Запись лекций.app'
    if app.exists():
        shutil.rmtree(app)
    contents = app / 'Contents'
    (contents / 'MacOS').mkdir(parents=True)
    resources = contents / 'Resources'
    setup = resources / 'Setup'
    setup.mkdir(parents=True)
    metadata = plistlib.loads((ROOT / 'macos/InstallerInfo.plist').read_bytes())
    metadata.update(CFBundleShortVersionString=version['version'], CFBundleVersion=str(version['code']))
    (contents / 'Info.plist').write_bytes(plistlib.dumps(metadata))
    shutil.copyfile(ROOT / 'macos/Recorder.icns', resources / 'Recorder.icns')
    shutil.copy2(uv, setup / 'uv')
    shutil.copytree(runtime, setup / 'python', symlinks=True)
    for name in ('install.py', 'verify.py', 'models.json', 'distribution.json', 'requirements-ai.lock', 'requirements-recorder.lock', 'requirements-vision.lock'):
        shutil.copyfile(ROOT / 'installer' / name, setup / name)
    for name in ('LICENSE-MIT', 'LICENSE-APACHE'):
        fetch('https://raw.githubusercontent.com/astral-sh/uv/' + distribution['uv_version'] + '/' + name, resources / ('uv-' + name))
    sources = [ROOT / 'release.json']
    for folder in ('outputs/recorder', 'outputs/Запись лекций.app', 'outputs/Синхронизация Bluetooth.app'):
        sources.extend(path for path in (ROOT / folder).rglob('*') if path.is_file() and payload_allowed(path.relative_to(ROOT).as_posix()))
    with zipfile.ZipFile(setup / 'payload.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(sources):
            if path.is_symlink():
                raise ValueError('Ссылка в приложении: ' + str(path))
            bundle.write(path, path.relative_to(ROOT).as_posix())
    manifest = dict(version, **distribution)
    manifest['files'] = {path.name: sha(path) for path in setup.iterdir() if path.is_file()}
    (setup / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    subprocess.run(['xcrun', 'swiftc', '-target', 'arm64-apple-macos14.0', '-O', str(ROOT / 'macos/InstallerApp.swift'), '-o', str(contents / 'MacOS/Installer')], check=True)
    subprocess.run(['codesign', '--force', '--deep', '--sign', '-', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    if not args.skip_dmg:
        disk = work / 'disk'
        if disk.exists():
            shutil.rmtree(disk)
        disk.mkdir()
        shutil.copytree(app, disk / app.name, symlinks=True)
        (disk / 'Начни здесь.txt').write_text('Открой «Установить Запись лекций» и нажми «Установить и открыть».\nТерминал, Python и права администратора не нужны.\nНужны Mac с Apple Silicon, macOS 14+, 22 ГБ свободного места и интернет.\nПосле установки приложение находится в папке «Приложения» твоего профиля.\n')
        dmg = work / ('lecture-recorder-' + version['version'] + '-arm64.dmg')
        dmg.unlink(missing_ok=True)
        subprocess.run(['hdiutil', 'create', '-volname', 'Запись лекций', '-srcfolder', str(disk), '-format', 'UDZO', str(dmg)], check=True)
        subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
        print(dmg)
    print(app)


if __name__ == '__main__':
    main()
