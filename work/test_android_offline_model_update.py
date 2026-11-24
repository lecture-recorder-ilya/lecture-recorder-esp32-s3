import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'ru.ilya.lecturerecorder'
SRC = ROOT / 'outputs/android/src/ru/ilya/lecturerecorder/PhoneModels.java'
MODELS = {
    'gigaam-v3-e2e-ctc.int8.onnx': '2e3fcb7a7b66030336fd10c2fcfb033bd1dc7e1bf238fe5cfd83b1d0cfc9d28e',
    'qwen3-0.6b-int4.litertlm': 'bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0',
}
JAVA = {
'Context.java': '''package android.content;
import java.io.*;
import android.content.res.AssetManager;
public class Context {
    private final File files;
    private final AssetManager assets;
    public Context(File files, File installed) throws IOException {
        this.files = files;
        this.assets = new AssetManager(installed);
    }
    public File getFilesDir() {return files;}
    public AssetManager getAssets() {return assets;}
}''',
'AssetFileDescriptor.java': '''package android.content.res;
public class AssetFileDescriptor implements java.io.Closeable {
    private final long length;
    AssetFileDescriptor(long length) {this.length = length;}
    public long getLength() {return length;}
    public void close() {}
}''',
'AssetManager.java': '''package android.content.res;
import java.io.*;
import java.util.zip.*;
public class AssetManager {
    private final ZipFile installed;
    public AssetManager(File path) throws IOException {installed = new ZipFile(path);}
    private ZipEntry entry(String name) throws IOException {
        ZipEntry result = installed.getEntry("assets/" + name);
        if (result == null) throw new FileNotFoundException(name);
        return result;
    }
    public AssetFileDescriptor openFd(String name) throws IOException {
        ZipEntry value = entry(name);
        if (value.getMethod() != ZipEntry.STORED) throw new IOException("compressed");
        return new AssetFileDescriptor(value.getSize());
    }
    public InputStream open(String name) throws IOException {return installed.getInputStream(entry(name));}
}''',
'Migration.java': '''package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import java.security.MessageDigest;
import java.util.zip.ZipFile;
class PhoneAnalysisService {static class Job {void check() {} void update(String text) {}}}
class Store {
    static String hash(File path) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new FileInputStream(path)) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder value = new StringBuilder();
        for (byte b : digest.digest()) value.append(String.format("%02x", b & 255));
        return value.toString();
    }
}
public class Migration {
    public static void main(String[] args) throws Exception {
        Context context = new Context(new File(args[0]), new File(args[1]));
        File candidate = new File(args[2]);
        PhoneAnalysisService.Job job = new PhoneAnalysisService.Job();
        if (args.length == 3) {
            PhoneModels.preserveBundledForUpdate(context, candidate, job);
            return;
        }
        try (ZipFile zip = new ZipFile(candidate)) {
            PhoneModels.preserveModel(context, zip, args[3], Long.parseLong(args[4]), args[5], job);
        }
    }
}'''
}


class OfflineUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.build = Path(cls.temp.name)
        for name, source in JAVA.items():
            (cls.build / name).write_text(source)
        cls.jdk = Path(os.environ['JAVA_HOME']) / 'bin'
        subprocess.run([cls.jdk / 'javac', '--release', '8', '-d', cls.build, SRC,
                        *[cls.build / name for name in JAVA]], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def migrate(self, directory, installed, replacement, *spec, check=True):
        return subprocess.run([self.jdk / 'java', '-cp', self.build, PACKAGE + '.Migration',
                               directory, installed, replacement, *spec], check=check,
                              capture_output=True, text=True)

    def test_preserves_only_models_missing_from_next_package_and_retries_failed_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            content = b'local-test-model'
            sha = hashlib.sha256(content).hexdigest()
            asset = 'assets/models/tiny'
            installed, compact, compressed = [base / n for n in ('offline.apk', 'compact.apk', 'compressed.apk')]
            for path, key, codec in [(installed, asset, zipfile.ZIP_STORED),
                                     (compact, 'assets/other', zipfile.ZIP_STORED),
                                     (compressed, asset, zipfile.ZIP_DEFLATED)]:
                with zipfile.ZipFile(path, 'w', compression=codec) as z:
                    z.writestr(key, content)
            target = base / 'phone-models/tiny'
            size = str(len(content))
            self.migrate(base, installed, installed, 'tiny', size, sha)
            self.assertFalse(target.exists())
            bad = self.migrate(base, installed, compact, 'tiny', size, '0' * 64, check=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.part').exists())
            self.migrate(base, installed, compressed, 'tiny', size, sha)
            self.assertEqual(target.read_bytes(), content)
            written = target.stat().st_mtime_ns
            self.migrate(base, installed, compact, 'tiny', size, sha)
            self.assertEqual(target.stat().st_mtime_ns, written)
            self.migrate(base, compact, compact)

    @unittest.skipUnless(os.environ.get('TEST_OFFLINE_APK') and os.environ.get('TEST_COMPACT_APK'), 'Нужны готовые APK')
    def test_release_models_survive_compact_update_before_first_transcription(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            full = Path(os.environ['TEST_OFFLINE_APK'])
            compact = Path(os.environ['TEST_COMPACT_APK'])
            self.migrate(base, full, full)
            self.assertFalse((base / 'phone-models').exists())
            self.migrate(base, full, compact)
            for name, expected in MODELS.items():
                with (base / 'phone-models' / name).open('rb') as stream:
                    self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(), expected)


if __name__ == '__main__':
    unittest.main()
