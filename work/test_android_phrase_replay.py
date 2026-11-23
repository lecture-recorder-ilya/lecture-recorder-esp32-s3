import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from profile_android_asr import prepare_sources

HARNESS = """
package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import ai.onnxruntime.OrtSession;
import org.json.*;
public class ReplayCheck {
    static JSONObject word(String text, double from, double to) throws Exception {
        return new JSONObject().put("word", text).put("start", from).put("end", to);
    }
    public static void main(String[] args) throws Exception {
        if (args[0].equals("bounds")) {
            PhraseReplayAudio.Window near = PhraseReplayAudio.window(100 * 16000, .25, 4.75, Double.NaN);
            assert near.left == 0 && near.start == 4000 && near.end == 76000 && near.right == 100000;
            PhraseReplayAudio.Window tail = PhraseReplayAudio.window(20 * 16000, 18., 30., Double.NaN);
            assert tail.start == 18 * 16000 && tail.end == tail.right && tail.end == 20 * 16000;
            PhraseReplayAudio.Window longRow = PhraseReplayAudio.window(500 * 16000, 100., 160., 130.);
            assert longRow.right - longRow.left == 18 * 16000;
            assert longRow.start == (long)(122.5 * 16000) && longRow.end == (long)(137.5 * 16000);
            assert PhraseReplayAudio.window(500 * 16000, 100, 160, Double.NaN).start == 100 * 16000;
            for (double[] interval : new double[][]{{Double.NaN, 1}, {-1, 2}, {1, 1}, {20, 100}}) {
                try { PhraseReplayAudio.window(20 * 16000, interval[0], interval[1], 0); throw new AssertionError(); }
                catch (IOException expected) {}
            }
            return;
        }
        if (args[0].equals("words")) {
            PhraseReplayAudio.Window selected = PhraseReplayAudio.window(100 * 16000, 13., 16., Double.NaN);
            JSONArray words = new JSONArray().put(word("слева", 12.2, 12.3))
                    .put(word("два", 12.9, 13.3)).put(word("метра", 13.4, 15.))
                    .put(word("эхо", 15.1, 15.3).put("verify_onset", true)).put(word("справа", 15.95, 16.3));
            assert PhraseReplayAudio.text(selected, words).equals("два метра");
            return;
        }
        try (RandomAccessFile source = new RandomAccessFile(args[1], "r"); OrtSession.RunOptions run = new OrtSession.RunOptions()) {
            long total = PcmWave.seekData(source) / 2;
            long data = source.getFilePointer();
            PhraseReplayAudio.Window at = PhraseReplayAudio.window(total, Double.parseDouble(args[4]), Double.parseDouble(args[5]), Double.NaN);
            String result = PhraseReplayAudio.decode(new Context(new File(args[3])), source, data, at,
                new File(args[2]), run, new PhoneAnalysisService.Job());
            System.out.print(result);
        }
    }
}
"""


class PhraseReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get("JAVA_HOME") or not os.environ.get("CLIPMIC_ASR_DEPS"):
            raise unittest.SkipTest("Нужны JDK и зависимости стенда ASR")
        jdk, deps = Path(os.environ["JAVA_HOME"]), Path(os.environ["CLIPMIC_ASR_DEPS"])
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.directory = Path(temp.name)
        sources = cls.directory / "sources"
        prepare_sources(ROOT, sources, False)
        shutil.copy(ROOT / "outputs/android/src/ru/ilya/lecturerecorder/PhraseReplayAudio.java", sources)
        (sources / "ReplayCheck.java").write_text(HARNESS)
        cp = os.pathsep.join(map(str, [deps / "ort.jar", deps / "android-json.jar", sources]))
        subprocess.run([jdk / "bin/javac", "--release", "8", "-encoding", "UTF-8", "-cp", cp,
                        "-d", sources, *sources.glob("*.java")], check=True)
        cls.command = [jdk / "bin/java", "-ea", "-cp", cp, "ru.ilya.lecturerecorder.ReplayCheck"]

    def test_bounds(self):
        subprocess.run([*self.command, "bounds"], check=True)

    def test_excludes_words_from_context(self):
        subprocess.run([*self.command, "words"], check=True)

    def test_silence_in_selected_interval_with_non_silent_context(self):
        wav = self.directory / "fixture.wav"
        with wave.open(str(wav), "wb") as out:
            out.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            out.writeframes((b"\x10\x10\x20\x20" * 8000) + bytes(2 * 16000) + (b"\x10\x10\x20\x20" * 8000))
        result = subprocess.check_output([*self.command, "decode", wav, "missing.onnx", "absent", "1.0", "2.0"], text=True)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
