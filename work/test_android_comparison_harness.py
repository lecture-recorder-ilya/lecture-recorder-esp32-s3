import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from compare_android_asr import build, checked_results, input_files, sha

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
    def test_failed_repetition_cannot_score_as_silence(self):
        cases = [{'id': 'noise'}]
        quiet = {'index': 0, 'repeat': 0, 'segments': []}
        checked_results(cases, [quiet], 1)
        failed = dict(quiet, repeat=1, error='IOException')
        with self.assertRaisesRegex(ValueError, 'noise, повтор 2'):
            checked_results(cases, [quiet, failed], 2)
        with self.assertRaises(ValueError):
            checked_results(cases, [quiet], 2)
        with self.assertRaises(ValueError):
            checked_results(cases, [dict(quiet, index=1)], 1)
        with self.assertRaises(ValueError):
            checked_results(cases, [], 0)

    def test_header_probe_verifies_the_actual_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'original.wav'
            original.write_bytes(b'RIFF')
            case = {'id': 'header', 'original_audio': original.name, 'original_audio_sha256': sha(original)}
            self.assertEqual(input_files([case], root / 'manifest.json', True), [original.resolve()])
            original.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'header'):
                input_files([case], root / 'manifest.json', True)

    def test_quality_run_checks_pcm_and_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'frames.wav'
            frames = bytes(320)
            with wave.open(str(path), 'wb') as audio:
                audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                audio.writeframes(frames)
            case = dict(id='frames', audio=path.name, duration=.01, audio_sha256=sha(path),
                        pcm_sha256=hashlib.sha256(frames).hexdigest())
            manifest = root / 'list.json'
            self.assertEqual(input_files([case], manifest, False), [path.resolve()])
            for changes in ({'pcm_sha256': '0' * 64}, {'duration': 5}, {'duration': float('nan')}):
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'PCM'):
                    input_files([dict(case, **changes)], manifest, False)

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
