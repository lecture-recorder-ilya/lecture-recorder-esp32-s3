import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'outputs/recorder'))
from update_manager import allowed


def main():
    parser = argparse.ArgumentParser(description='Собрать пакеты закрытого канала обновлений.')
    parser.add_argument('--preview-apk', type=Path, help='APK отдельной сборки Android с прежней подписью')
    parser.add_argument('--android-only', action='store_true', help='Собрать только пакет обновлений Android')
    parser.add_argument('--android-apk', type=Path, help='Обычный APK, подписанный ключом предыдущего релиза')
    args = parser.parse_args()
    output = ROOT/'work/release'
    if args.android_only:
        if args.android_apk is None and args.preview_apk is None:
            parser.error('--android-only требует --android-apk или --preview-apk')
        output /= 'android'
    apk = args.android_apk
    if not args.android_only and apk is None:
        apk = ROOT/'outputs/android/Запись лекций.apk'
    for path in (apk, args.preview_apk):
        if path is not None and not path.is_file():
            parser.error(f'APK не найден: {path}')
    output.mkdir(parents=True, exist_ok=True)
    packages = [] if args.android_only else [build_mac_archive(output)]
    for source, name in ((apk, 'lecture-recorder.apk'), (args.preview_apk, 'lecture-recorder-android.apk')):
        target = output/name
        if source is None:
            target.unlink(missing_ok=True)
            continue
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        packages.append(target)

    sums = []
    for path in packages:
        with path.open('rb') as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        sums.append(f'{digest.hexdigest()}  {path.name}')
    (output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n')
    print(output)


def build_mac_archive(output):
    sources = [ROOT/'release.json']
    for folder in ('outputs/recorder', 'outputs/Запись лекций.app', 'outputs/Синхронизация Bluetooth.app'):
        path = ROOT/folder
        if not path.exists():
            raise SystemExit('Сначала собери приложения Mac: tools/build_mac.py')
        sources.extend(p for p in path.rglob('*') if p.is_file() and allowed(p.relative_to(ROOT).as_posix()))
    archive = output/'lecture-mac-update.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in sources:
            if path.is_symlink():
                raise ValueError('Ссылки не включаются в обновление')
            z.write(path, path.relative_to(ROOT).as_posix())
    return archive


if __name__ == '__main__':
    main()
