"""Build without third-party Android runtime dependencies; local SDK + JDK 17."""
import os,subprocess,zipfile,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parent; PROJECT=ROOT.parent.parent
TOOLS=PROJECT/'work/android-tools';BUILD=PROJECT/'work/android-build';BUILD.mkdir(exist_ok=True)
JDK=Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else next((TOOLS/'jdk').glob('*/Contents/Home'))
sdk_root=Path(os.environ['ANDROID_SDK_ROOT']) if os.environ.get('ANDROID_SDK_ROOT') else None
SDK=sdk_root/'platforms/android-36/android.jar' if sdk_root else TOOLS/'platform/android-36/android.jar'
BT=Path(os.environ['ANDROID_BUILD_TOOLS']) if os.environ.get('ANDROID_BUILD_TOOLS') else sorted((sdk_root/'build-tools').iterdir())[-1] if sdk_root else TOOLS/'build-tools/android-16'
env=dict(os.environ,JAVA_HOME=str(JDK),PATH=str(JDK/'bin')+os.pathsep+os.environ['PATH'])
def run(args):subprocess.run([str(x) for x in args],env=env,check=True)
for f in ['aapt2','zipalign','apksigner','d8']:(BT/f).chmod(0o755)
res=ROOT/'res/drawable';res.mkdir(parents=True,exist_ok=True)
shutil.copyfile(PROJECT/'outputs/recorder-icon.png',res/'icon.png')
run([BT/'aapt2','compile','--dir',ROOT/'res','-o',BUILD/'res.zip'])
generated=BUILD/'generated';generated.mkdir(exist_ok=True)
run([BT/'aapt2','link','-o',BUILD/'base.apk','-I',SDK,'--manifest',ROOT/'AndroidManifest.xml','--java',generated,BUILD/'res.zip'])
classes=BUILD/'classes';classes.mkdir(exist_ok=True)
run([JDK/'bin/javac','-encoding','UTF-8','-source','8','-target','8','-classpath',SDK,'-d',classes,*ROOT.glob('src/**/*.java'),*generated.glob('**/*.java')])
with zipfile.ZipFile(BUILD/'classes.jar','w') as z:
 for f in classes.glob('**/*.class'):z.write(f,f.relative_to(classes))
run([BT/'d8','--release','--min-api','26','--lib',SDK,'--output',BUILD,BUILD/'classes.jar'])
with zipfile.ZipFile(BUILD/'base.apk','a') as z:z.write(BUILD/'classes.dex','classes.dex')
run([BT/'zipalign','-f','4',BUILD/'base.apk',BUILD/'aligned.apk'])
key=TOOLS/'lectures.keystore'
if not key.exists():run([JDK/'bin/keytool','-genkeypair','-keystore',key,'-storepass','android','-keypass','android','-alias','lectures','-dname','CN=Ilya Lecture Recorder','-keyalg','RSA','-validity','10000'])
key.chmod(0o600)
run([BT/'apksigner','sign','--ks',key,'--ks-pass','pass:android','--out',ROOT/'Запись лекций.apk',BUILD/'aligned.apk'])
run([BT/'apksigner','verify',ROOT/'Запись лекций.apk'])
print('APK ready')
