import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


class LiveViewTree:
    component = 'ru.ilya.lecturerecorder.test.LiveSnapshot'

    def __init__(self, case, adb):
        self.adb = adb
        self.package = 'ru.ilya.lecturerecorder.test.s' + str(os.getpid())
        jdk = Path(os.environ['JAVA_HOME'])
        platform = os.environ['ANDROID_PLATFORM_JAR']
        tools = Path(os.environ['ANDROID_BUILD_TOOLS'])
        env = dict(os.environ, PATH=str(jdk / 'bin') + os.pathsep + os.environ['PATH'])
        source = Path(__file__).resolve().parents[1] / 'tests/android/LiveSnapshot.java'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / 'AndroidManifest.xml'
            manifest.write_text(f'<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="{self.package}">'
                                '<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/>'
                                f'<application/><instrumentation android:name="{self.component}" android:targetPackage="{self.package}"/></manifest>')
            apk = root / 'snapshot.apk'
            def run(*args):
                subprocess.run(args, cwd=root, env=env, check=True, capture_output=True)
            run(tools / 'aapt2', 'link', '-I', platform, '--manifest', manifest, '-o', apk)
            run(jdk / 'bin/javac', '--release', '8', '-classpath', platform, '-d', root, source)
            run(tools / 'd8', '--min-api', '26', '--lib', platform, '--output', root, next(root.rglob('LiveSnapshot.class')))
            with zipfile.ZipFile(apk, 'a') as package:
                package.write(root / 'classes.dex', 'classes.dex')
            run(jdk / 'bin/keytool', '-genkeypair', '-keystore', 'test.p12', '-storepass', 'android', '-keypass', 'android',
                '-alias', 'test', '-keyalg', 'RSA', '-dname', 'CN=Local UI test', '-validity', '1')
            run(tools / 'apksigner', 'sign', '--ks', 'test.p12', '--ks-pass', 'pass:android', apk)
            adb('install', '--no-incremental', apk)
            case.addClassCleanup(adb, 'uninstall', self.package)

    def xml(self):
        for _ in range(3):
            response = self.adb('shell', 'am', 'instrument', '-w', '-r', self.package + '/' + self.component)
            match = re.search(rb'^INSTRUMENTATION_RESULT: tree=(\S+)', response, re.MULTILINE)
            if match:
                return base64.b64decode(match.group(1), validate=True)
        raise AssertionError(response.decode(errors='replace'))
