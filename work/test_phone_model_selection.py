import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'ru.ilya.lecturerecorder'
CONTEXT = '''package android.content;
import java.io.File;
public final class Context {
 private final File directory;
 public Context(File value) { directory=value; }
 public File getFilesDir() { return directory; }
 public android.content.res.AssetManager getAssets() { return new android.content.res.AssetManager(); }
}'''
HARNESS = '''package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
class PhoneAnalysisService { static class Job { void check() {} void update(String text) {} } }
class Store { static String hash(File file) { throw new AssertionError("Unexpected model download"); } }
public final class ModelSelectionHarness {
 public static void main(String[] args)throws Exception {
  Context context=new Context(new File(args[0]));File directory=new File(args[0],"phone-models");
  if(!directory.mkdirs())throw new IOException("Model fixture directory");
  File personal=new File(directory,"gigaam-personal.int8.onnx");
  try(FileOutputStream out=new FileOutputStream(personal)) { out.write(new byte[]{1,2,3}); }
  File text=new File(directory,"qwen3-0.6b-int4.litertlm");
  try(RandomAccessFile out=new RandomAccessFile(text,"rw")) { out.setLength(343490560L); }
  System.out.println("personal_only_ready="+PhoneModels.ready(context));
  try {
   PhoneModels.offlineAcoustic(context,new PhoneAnalysisService.Job());
   throw new AssertionError("Missing offline model was accepted");
  } catch(IOException expected) { System.out.println("offline_missing="+expected.getMessage()); }
  File stock=new File(directory,"gigaam-v3-e2e-ctc.int8.onnx");
  try(RandomAccessFile out=new RandomAccessFile(stock,"rw")) { out.setLength(224893347L); }
  System.out.println("stock_and_text_ready="+PhoneModels.ready(context));
  System.out.println("selected="+PhoneModels.acoustic(context,new PhoneAnalysisService.Job()).getName());
  System.out.println("offline_selected="+PhoneModels.offlineAcoustic(context,new PhoneAnalysisService.Job()).getName());
  System.out.println("personal_preserved="+(personal.isFile() && personal.length()==3));
  if(!text.delete())throw new IOException("Summary fixture deletion");
  System.out.println("without_text_ready="+PhoneModels.ready(context));
 }
}'''


def observe(source):
    java = Path(os.environ['JAVA_HOME'])/'bin'
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory);classes=root/'classes';classes.mkdir();files=root/'files';files.mkdir()
        (root/'Context.java').write_text(CONTEXT)
        (root/'AssetManager.java').write_text('''package android.content.res;
import java.io.*;
public class AssetManager {
 public AssetFileDescriptor openFd(String name) throws IOException { throw new FileNotFoundException(name); }
 public InputStream open(String name) throws IOException { throw new FileNotFoundException(name); }
}''')
        (root/'AssetFileDescriptor.java').write_text('''package android.content.res;
public class AssetFileDescriptor implements java.io.Closeable {
 public long getLength(){ return 0; }
 public void close() {}
}''')
        (root/'ModelSelectionHarness.java').write_text(HARNESS)
        subprocess.run([java/'javac','--release','8','-encoding','UTF-8','-d',classes,
                        source/'outputs/android/src/ru/ilya/lecturerecorder/PhoneModels.java',
                        root/'Context.java',root/'AssetManager.java',root/'AssetFileDescriptor.java',root/'ModelSelectionHarness.java'],check=True,capture_output=True,text=True)
        result=subprocess.check_output([java/'java','-cp',classes,PACKAGE+'.ModelSelectionHarness',files],text=True)
        return dict(line.split('=',1) for line in result.splitlines())


class PhoneModelSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=observe(ROOT)

    def test_unchecked_personal_file_does_not_make_models_ready(self):
        self.assertEqual(self.result['personal_only_ready'],'false')

    def test_stock_is_selected_when_a_personal_file_also_exists(self):
        self.assertEqual(self.result['selected'],'gigaam-v3-e2e-ctc.int8.onnx')

    def test_offline_retry_uses_only_local_weights(self):
        self.assertEqual(self.result['offline_missing'], 'На телефоне ещё нет локальной модели речи')
        self.assertEqual(self.result['offline_selected'], 'gigaam-v3-e2e-ctc.int8.onnx')

    def test_stock_and_summary_are_still_ready(self):
        self.assertEqual(self.result['stock_and_text_ready'],'true')

    def test_model_selection_preserves_the_personal_file(self):
        self.assertEqual(self.result['personal_preserved'],'true')

    def test_missing_summary_stays_not_ready(self):
        self.assertEqual(self.result['without_text_ready'],'false')


if __name__=='__main__':unittest.main()
