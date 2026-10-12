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
    output = ROOT/'work/release'
    output.mkdir(parents=True, exist_ok=True)
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
    apk = ROOT/'outputs/android/Запись лекций.apk'
    if not apk.exists():
        raise SystemExit('Сначала собери Android: outputs/android/build.py')
    shutil.copyfile(apk, output/'lecture-recorder.apk')
    sums = [hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name for p in (archive, output/'lecture-recorder.apk')]
    (output/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n')
    print(output)


if __name__ == '__main__':
    main()
