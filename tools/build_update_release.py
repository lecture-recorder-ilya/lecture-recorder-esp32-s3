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
from android_packages import STABLE, apk_identity


def main():
    parser = argparse.ArgumentParser(description='Собрать пакеты закрытого канала обновлений.')
    parser.add_argument('--preview-apk', type=Path, help='APK отдельной сборки Android с прежней подписью')
    parser.add_argument('--offline-apk', type=Path, help='Дополнительный Android APK со встроенными моделями')
    args = parser.parse_args()
    output = ROOT/'work/release'
    output.mkdir(parents=True, exist_ok=True)
    apk = ROOT/'outputs/android/Запись лекций.apk'
    if not apk.is_file():
        raise SystemExit('Сначала собери Android: outputs/android/build.py')
    if args.preview_apk is not None and not args.preview_apk.is_file():
        raise SystemExit('Не найден APK отдельной сборки Android')
    if args.offline_apk is not None:
        version = json.loads((ROOT/'release.json').read_text())
        if not args.offline_apk.is_file() or apk_identity(args.offline_apk) != (STABLE, version['code']):
            raise SystemExit('Автономный APK должен совпадать с версией релиза')
        with zipfile.ZipFile(args.offline_apk) as bundled:
            for model in ('gigaam-v3-e2e-ctc.int8.onnx', 'qwen3-0.6b-int4.litertlm'):
                if 'assets/models/' + model not in bundled.namelist():
                    raise SystemExit('В автономном APK отсутствует ' + model)
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
    stable = output/'lecture-recorder.apk'
    preview = output/'lecture-recorder-android.apk'
    shutil.copyfile(apk, stable)
    packages = [archive, stable]
    if args.preview_apk is not None:
        shutil.copyfile(args.preview_apk, preview)
        packages.append(preview)
    elif preview.is_file():
        preview.unlink()
    offline = output/'lecture-recorder-offline.apk'
    if args.offline_apk is not None:
        if args.offline_apk.resolve() != offline.resolve():
            shutil.copyfile(args.offline_apk, offline)
        packages.append(offline)
    elif offline.is_file():
        offline.unlink()
    sums = []
    for path in packages:
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        sums.append(f'{digest}  {path.name}')
    (output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n')
    print(output)


if __name__ == '__main__':
    main()
