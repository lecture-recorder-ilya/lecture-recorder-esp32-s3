"""Build native launchers in the expected checkout layout."""
import argparse,plistlib,shutil,subprocess,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
p=argparse.ArgumentParser();p.add_argument('--check',action='store_true');args=p.parse_args()
for title,source,template,binary in [('Запись лекций','RecorderApp.swift','RecorderInfo.plist','Recorder'),('Синхронизация Bluetooth','PhoneBluetooth.swift','BluetoothInfo.plist','PhoneBluetooth')]:
 if args.check:
  subprocess.run(['xcrun','swiftc','-typecheck',str(ROOT/'macos'/source)],check=True)
  continue
 app=ROOT/'outputs'/(title+'.app');contents=app/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
 metadata=plistlib.loads((ROOT/'macos'/template).read_bytes());version=json.loads((ROOT/'release.json').read_text())
 metadata.update(CFBundleShortVersionString=version['version'],CFBundleVersion=str(version['code']),LSMinimumSystemVersion='14.0')
 (contents/'Info.plist').write_bytes(plistlib.dumps(metadata))
 if binary=='Recorder':
  (contents/'Resources').mkdir(exist_ok=True);shutil.copyfile(ROOT/'macos/Recorder.icns',contents/'Resources/Recorder.icns')
 subprocess.run(['xcrun','swiftc','-target','arm64-apple-macos14.0','-O',str(ROOT/'macos'/source),'-o',str(contents/'MacOS'/binary)],check=True)
 subprocess.run(['xattr','-cr',str(app)],check=True)
 subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
 print('Готово:',app)
