import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from profile_android_asr import prepare_sources

CHECK = '''package ru.ilya.lecturerecorder;

import ai.onnxruntime.*;
import java.io.*;
import java.lang.reflect.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.*;

public final class WindowCheck {
    static boolean fixture = true;
    static volatile boolean cancelled;
    static CountDownLatch thirdFinished;
    static List<Integer> finished;
    static final AtomicInteger active = new AtomicInteger();
    static final AtomicInteger peak = new AtomicInteger();
    static String mode;
    static final int SPAN = 18 * 16000;

    static JSONArray words(PhoneAnalysisService.Job job, long start) throws Exception {
        int index = (int)(start / SPAN);
        int count = active.incrementAndGet();
        peak.accumulateAndGet(count, Math::max);
        try {
            if (index == 1) {
                if (!thirdFinished.await(3, TimeUnit.SECONDS)) throw new AssertionError("Окна не пересеклись");
                if (mode.equals("error")) throw new IOException("Проверочная ошибка");
                job.check();
            }
            finished.add(index);
            if (index == 2) {
                cancelled = mode.equals("cancel");
                thirdFinished.countDown();
            }
            JSONArray output = new JSONArray();
            for (int n = 1; n <= 2; n++) {
                double t = start / 16000.0 + n;
                output.put(new JSONObject().put("word","окно"+index+n).put("start",t).put("end",t+.1)
                        .put("_legacy_core",true).put("conf",.99));
            }
            return output;
        } finally {
            active.decrementAndGet();
        }
    }

    static void run(String next) throws Exception {
        mode = next;
        cancelled = false;
        thirdFinished = new CountDownLatch(1);
        finished = Collections.synchronizedList(new ArrayList<>());
        peak.set(0);
        PhonePhrases phrases = new PhonePhrases();
        PhoneWordTimeline timeline = new PhoneWordTimeline(phrases, 2);
        Method decode = PhoneGigaAm.class.getDeclaredMethod("decodeWindows", PhoneAnalysisService.Job.class,
                RandomAccessFile.class, long.class, long.class, OrtEnvironment.class, OrtSession.class,
                OrtSession.class, String[].class, PhoneWordTimeline.class);
        decode.setAccessible(true);
        Throwable failure = null;
        try {
            decode.invoke(null, new PhoneAnalysisService.Job(), null, 0L, 7L * SPAN, null, null, null, null, timeline);
        } catch (InvocationTargetException caught) {
            failure = caught.getCause();
        }
        assert active.get() == 0 && peak.get() <= 2;
        assert Collections.frequency(finished, 0) == 1;
        if (mode.equals("cancel")) {
            assert failure instanceof InterruptedIOException;
        } else if (mode.equals("error")) {
            assert failure != null && !(failure instanceof IOException) && failure.getCause() instanceof IOException;
        } else {
            assert failure == null && finished.indexOf(2) < finished.indexOf(1);
            timeline.finish();
            JSONArray rows = phrases.finish();
            assert rows.length() == 14;
            for (int i = 0; i < rows.length(); i++) {
                JSONObject row = rows.getJSONObject(i);
                assert row.getString("text").equals("окно"+(i/2)+(i%2+1));
                assert row.getDouble("start") == (i/2)*18+i%2+1;
            }
        }
    }

    public static void main(String[] args) throws Exception {
        long mib = 1024L * 1024;
        long longAudio = 120L * 16000;
        assert PhoneGigaAm.canOverlapWindows(longAudio, 8, 512 * mib, 300 * mib);
        assert !PhoneGigaAm.canOverlapWindows(89 * 16000, 8, 512 * mib, 300 * mib);
        assert !PhoneGigaAm.canOverlapWindows(longAudio, 4, 512 * mib, 300 * mib);
        assert !PhoneGigaAm.canOverlapWindows(longAudio, 8, 192 * mib, 170 * mib);
        assert !PhoneGigaAm.canOverlapWindows(longAudio, 8, 512 * mib, 120 * mib);
        run("ordered");
        run("error");
        run("cancel");
    }
}
'''


class WindowQueueTest(unittest.TestCase):
    def test_order_limits_failure_and_cancellation(self):
        jdk = os.environ.get('CLIPMIC_ASR_JDK') or os.environ.get('JAVA_HOME')
        deps = os.environ.get('CLIPMIC_ASR_DEPS')
        if not jdk or not deps:
            self.skipTest('Нужны JDK и CLIPMIC_ASR_DEPS с ort.jar и android-json.jar')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'java'
            prepare_sources(ROOT, folder, False)
            decoder = folder/'PhoneGigaAm.java'
            marker = '        float[] raw = readWindow(input, data + left * 2, (int) (right - left));'
            source = decoder.read_text()
            self.assertEqual(source.count(marker), 1)
            decoder.write_text(source.replace(marker, '        if (WindowCheck.fixture) return new Window(end, () -> WindowCheck.words(job, start));\n' + marker))
            harness = folder/'Harness.java'
            source = harness.read_text()
            self.assertEqual(source.count('void check() {}'), 1)
            harness.write_text(source.replace('void check() {}',
                'void check() throws InterruptedIOException { if(WindowCheck.cancelled) throw new InterruptedIOException(); }'))
            (folder/'WindowCheck.java').write_text(CHECK)
            cp = os.pathsep.join(map(str, [folder, Path(deps)/'ort.jar', Path(deps)/'android-json.jar']))
            subprocess.run([Path(jdk)/'bin/javac', '--release', '8', '-encoding', 'UTF-8',
                            '-cp', cp, '-d', folder, *folder.glob('*.java')], check=True)
            subprocess.run([Path(jdk)/'bin/java', '-ea', '-XX:ActiveProcessorCount=8', '-Xmx512m',
                            '-cp', cp, 'ru.ilya.lecturerecorder.WindowCheck'], check=True, timeout=18)


if __name__ == '__main__':
    unittest.main()
