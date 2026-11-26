import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECK = """
package ru.ilya.lecturerecorder;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

class LectureReaderActivity {
    static String clock(double seconds) { throw new AssertionError(); }
}

public class GapCheck {
    public static void main(String[] args) throws Exception {
        JSONArray gaps = new JSONArray();
        assert RecordingGap.read(null, 10000).isEmpty();
        assert RecordingGap.read(gaps, 10000).isEmpty();
        gaps.put(new JSONObject().put("start", 10).put("seconds", 2).put("unrecorded_tail", true));
        gaps.put(new JSONObject().put("start", 4.5).put("seconds", 0.25));
        gaps.put(new JSONObject().put("start", 0).put("end", 0.1).put("seconds", 0.1));
        gaps.put(new JSONObject().put("start", 9).put("seconds", 4));
        gaps.put(new JSONObject().put("start", 12).put("seconds", 1));
        gaps.put(new JSONObject().put("start", 0).put("seconds", -1));
        gaps.put(new JSONObject().put("start", 1).put("end", "NaN"));
        gaps.put(new JSONObject().put("start", -1).put("seconds", 2));
        gaps.put(new JSONObject().put("start", 1).put("seconds", "Infinity"));
        gaps.put(new JSONObject().put("start", 4).put("seconds", 2).put("unrecorded_tail", true));
        gaps.put(JSONObject.NULL);
        assert RecordingGap.read(gaps, 0).isEmpty();
        List<RecordingGap> parsed = RecordingGap.read(gaps, 10000);
        assert parsed.size() == 4 : parsed.size();
        assert parsed.get(0).start == 0 && parsed.get(0).end == 100 && parsed.get(0).listenFrom() == 0;
        assert parsed.get(1).start == 4500 && parsed.get(1).end == 4750 && parsed.get(1).listenFrom() == 2500;
        assert parsed.get(2).end == 10000 && !parsed.get(2).afterFile;
        assert parsed.get(3).start == 10000 && parsed.get(3).afterFile && parsed.get(3).listenFrom() == 8000;
        assert parsed.get(3).toString().equals("После окончания файла · 2 с");
    }
}
"""


class GapTests(unittest.TestCase):
    def test_recorded_intervals_and_unrecorded_tail(self):
        jar = os.environ.get("ANDROID_JSON_JAR")
        if not jar:
            self.skipTest("Нужен ANDROID_JSON_JAR")
        javabin = Path(os.environ["JAVA_HOME"]) / "bin"
        source = ROOT / "outputs/android/src/ru/ilya/lecturerecorder/RecordingGap.java"
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "GapCheck.java"
            probe.write_text(CHECK)
            subprocess.run([javabin / "javac", "--release", "8", "-classpath", jar,
                            "-d", directory, source, probe], check=True)
            subprocess.run([javabin / "java", "-ea", "-classpath", os.pathsep.join([directory, jar]),
                            "ru.ilya.lecturerecorder.GapCheck"], check=True)


if __name__ == "__main__":
    unittest.main()
