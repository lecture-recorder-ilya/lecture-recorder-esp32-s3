import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from compare_android_asr import build

HARNESS='''package ru.ilya.lecturerecorder;
import java.util.function.Consumer;
import org.json.*;
public final class CallbackContractTest {
 public static void main(String[] args)throws Exception {
  Harness.started=System.nanoTime();
  PhoneAnalysisService.Job job=new PhoneAnalysisService.Job();
  Consumer<JSONObject> current=job::publishPhrase;
  Consumer<JSONObject> legacy=job.preview::addPhrase;
  JSONObject row=new JSONObject().put("text","не три").put("needs_review",true);
  current.accept(row);
  if(job.preview.phrases!=1 || job.preview.first<0)throw new AssertionError("publishPhrase");
  double first=job.preview.first;
  legacy.accept(row);
  if(job.preview.phrases!=2 || job.preview.first!=first)throw new AssertionError("preview::addPhrase");
  job.preview.startSpeech();
  if(job.preview.phrases!=0 || job.preview.first!=-1)throw new AssertionError("startSpeech");
  current.accept(row);
  if(job.preview.phrases!=1 || !row.getBoolean("needs_review"))throw new AssertionError("metadata");
 }
}'''


class AndroidComparisonHarnessTests(unittest.TestCase):
    def test_legacy_and_current_phrase_callbacks_share_the_probe(self):
        jdk_path=os.environ.get('JAVA_HOME')
        deps_path=os.environ.get('CLIPMIC_ASR_DEPS')
        if not jdk_path or not deps_path:
            self.skipTest('Нужны JAVA_HOME и CLIPMIC_ASR_DEPS с ort.jar и android-json.jar')
        jdk=Path(jdk_path)
        deps=Path(deps_path)
        with tempfile.TemporaryDirectory() as directory:
            generated=Path(directory)/'java'
            cp,sources=build(ROOT,generated,deps,jdk)
            self.assertIn('PhoneGigaAm',sources)
            file=generated/'CallbackContractTest.java';file.write_text(HARNESS)
            subprocess.run([jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cp,'-d',generated,file],check=True)
            subprocess.run([jdk/'bin/java','-cp',cp,'ru.ilya.lecturerecorder.CallbackContractTest'],check=True)


if __name__=='__main__':unittest.main()
