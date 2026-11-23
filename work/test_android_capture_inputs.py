import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PACKAGE = "ru.ilya.lecturerecorder"
SOURCE = Path(__file__).resolve().parents[1] / "outputs/android/src" / PACKAGE.replace(".", "/")
STUBS = {
    "android.os.Build": "public class Build { public static class VERSION { public static int SDK_INT = 36; } }",
    "android.os.SystemClock": "public class SystemClock { public static long elapsedRealtime() { return System.nanoTime()/1000000; } }",
    "android.bluetooth.BluetoothProfile": "public interface BluetoothProfile { int HEADSET=1, STATE_CONNECTED=2; }",
    "android.bluetooth.BluetoothAdapter": """
        public class BluetoothAdapter {
            public int headsetState;
            public boolean isEnabled() { return true; }
            public int getProfileConnectionState(int profile) { return headsetState; }
        }
    """,
    "android.bluetooth.BluetoothManager": """
        public class BluetoothManager {
            public final BluetoothAdapter adapter = new BluetoothAdapter();
            public BluetoothAdapter getAdapter() { return adapter; }
        }
    """,
    "android.content.Context": """
        import android.media.AudioManager;
        import android.bluetooth.BluetoothManager;
        public class Context {
            public final AudioManager sound = new AudioManager();
            public final BluetoothManager bluetooth = new BluetoothManager();
            public java.io.File directory;
            public <T> T getSystemService(Class<T> type) {
                return type.cast(type == AudioManager.class ? sound : bluetooth);
            }
        }
    """,
    "android.media.AudioDeviceInfo": """
        public class AudioDeviceInfo {
            public static final int TYPE_WIRED_HEADSET=3, TYPE_USB_HEADSET=22, TYPE_USB_DEVICE=11, TYPE_USB_ACCESSORY=12,
                    TYPE_BLUETOOTH_SCO=7, TYPE_BLE_HEADSET=26, TYPE_BUILTIN_MIC=15, TYPE_BLUETOOTH_A2DP=8;
            private final int type;
            private final boolean input;
            public AudioDeviceInfo(int type, boolean input) { this.type=type; this.input=input; }
            public boolean isSource() { return input; }
            public int getType() { return type; }
        }
    """,
    "android.media.AudioManager": """
        import java.util.*;
        public class AudioManager {
            public static final int GET_DEVICES_INPUTS=1, MODE_NORMAL=0, MODE_IN_COMMUNICATION=3;
            public AudioDeviceInfo[] inputs = {};
            public List<AudioDeviceInfo> calls = new ArrayList<>();
            public AudioDeviceInfo selected;
            public boolean accept=true, scoStarted, scoOn;
            public int mode;
            public AudioDeviceInfo[] getDevices(int mask) { return inputs; }
            public int getMode() { return mode; }
            public void setMode(int value) { mode=value; }
            public AudioDeviceInfo getCommunicationDevice() { return selected; }
            public List<AudioDeviceInfo> getAvailableCommunicationDevices() { return calls; }
            public boolean setCommunicationDevice(AudioDeviceInfo device) { if (accept) selected=device; return accept; }
            public void clearCommunicationDevice() { selected=null; }
            public boolean isBluetoothScoAvailableOffCall() { return true; }
            public void startBluetoothSco() { scoStarted=true; }
            public void stopBluetoothSco() { scoStarted=false; }
            public boolean isBluetoothScoOn() { return scoOn; }
            public void setBluetoothScoOn(boolean value) { scoOn=value; }
        }
    """,
    "android.media.AudioRecord": """
        public class AudioRecord {
            public AudioDeviceInfo routed, preferred;
            public boolean setPreferredDevice(AudioDeviceInfo device) { preferred=device; return true; }
            public AudioDeviceInfo getRoutedDevice() { return routed; }
        }
    """,
    "android.media.MediaRecorder": "public class MediaRecorder { public static class AudioSource { public static final int VOICE_COMMUNICATION=7, MIC=1; } }",
    PACKAGE + ".BleStream": """
        import android.content.Context;
        import java.io.IOException;
        import java.util.concurrent.CountDownLatch;
        import java.util.concurrent.TimeUnit;
        import java.util.function.BooleanSupplier;
        final class BleStream {
            static CountDownLatch priming, audio, closed;
            static boolean fail;
            BleStream(Context context, BooleanSupplier cancelled, long deadline, boolean trusted) {
                if (!trusted) throw new AssertionError("Проверка допускает незнакомый диктофон");
            }
            static void reset(boolean unavailable) {
                priming=new CountDownLatch(1); audio=new CountDownLatch(1); closed=new CountDownLatch(1); fail=unavailable;
            }
            void prime(long deadline) throws Exception {
                priming.countDown();
                if (!audio.await(2, TimeUnit.SECONDS) || fail) throw new IOException("Нет PCM");
            }
            void close() { closed.countDown(); audio.countDown(); }
        }
    """,
}
HARNESS = """
import android.content.Context;
import android.media.*;
import android.os.Build;
import java.util.concurrent.TimeUnit;
import static android.media.AudioDeviceInfo.*;

public class CaptureInputCheck {
    static void routes() {
        Context context=new Context();
        AudioDeviceInfo builtin=new AudioDeviceInfo(TYPE_BUILTIN_MIC, true);
        AudioDeviceInfo hfp=new AudioDeviceInfo(TYPE_BLUETOOTH_SCO, false);
        AudioDeviceInfo a2dp=new AudioDeviceInfo(TYPE_BLUETOOTH_A2DP, false);
        AudioDeviceInfo wired=new AudioDeviceInfo(TYPE_WIRED_HEADSET, true);
        AudioRecord mic=new AudioRecord();
        context.sound.calls.add(a2dp);
        context.sound.inputs=new AudioDeviceInfo[]{builtin};
        try (RecordingInput input=new RecordingInput(context)) {
            assert input.audioSource()==MediaRecorder.AudioSource.MIC;
            assert context.sound.selected==null;
        }
        context.sound.calls.add(hfp);
        try (RecordingInput input=new RecordingInput(context)) {
            assert input.audioSource()==MediaRecorder.AudioSource.VOICE_COMMUNICATION;
            assert context.sound.selected==hfp;
            mic.routed=builtin;
            assert RecordingInput.actualLabel(mic).equals("Микрофон телефона");
            for (int type : new int[]{TYPE_BLUETOOTH_SCO, TYPE_BLE_HEADSET}) {
                mic.routed=new AudioDeviceInfo(type, true);
                assert RecordingInput.actualLabel(mic).equals("Bluetooth-гарнитура");
            }
            mic.routed=builtin;
            assert RecordingInput.actualLabel(mic).equals("Микрофон телефона");
        }
        assert context.sound.selected==null && context.sound.getMode()==AudioManager.MODE_NORMAL;
        context.sound.inputs=new AudioDeviceInfo[]{wired, builtin};
        try (RecordingInput input=new RecordingInput(context)) {
            input.prefer(mic);
            assert mic.preferred==wired && context.sound.selected==null;
            mic.routed=wired;
            assert RecordingInput.actualLabel(mic).equals("Проводная гарнитура");
        }
        context.sound.inputs=new AudioDeviceInfo[]{builtin};
        context.sound.accept=false;
        try (RecordingInput input=new RecordingInput(context)) {
            assert input.audioSource()==MediaRecorder.AudioSource.MIC && context.sound.mode==AudioManager.MODE_NORMAL;
        }
        Build.VERSION.SDK_INT=30;
        context.bluetooth.adapter.headsetState=2;
        try (RecordingInput input=new RecordingInput(context)) {
            assert context.sound.scoStarted && context.sound.scoOn;
            assert input.audioSource()==MediaRecorder.AudioSource.VOICE_COMMUNICATION;
        }
        assert !context.sound.scoStarted && !context.sound.scoOn && context.sound.mode==AudioManager.MODE_NORMAL;
    }

    static void probe() throws Exception {
        Context context=new Context();
        BleStream.reset(false);
        BleStream accepted;
        try (ClipMicProbe candidate=new ClipMicProbe(context, () -> false)) {
            assert BleStream.priming.await(1, TimeUnit.SECONDS);
            assert candidate.take()==null;
            BleStream.audio.countDown();
            accepted=candidate.await(() -> false);
            assert accepted!=null && candidate.take()==null;
            assert BleStream.closed.getCount()==1;
        }
        assert BleStream.closed.await(1, TimeUnit.SECONDS);
        BleStream.reset(true);
        try (ClipMicProbe candidate=new ClipMicProbe(context, () -> false)) {
            assert BleStream.priming.await(1, TimeUnit.SECONDS);
            BleStream.audio.countDown();
            assert candidate.await(() -> false)==null;
        }
        assert BleStream.closed.await(1, TimeUnit.SECONDS);
        BleStream.reset(false);
        try (ClipMicProbe abandoned=new ClipMicProbe(context, () -> false)) {
            assert BleStream.priming.await(1, TimeUnit.SECONDS);
        }
        assert BleStream.closed.await(1, TimeUnit.SECONDS);
    }

    public static void main(String[] args) throws Exception {
        if (args[0].equals("routes")) routes();
        else probe();
    }
}
"""

TAKE_STORE = """
import java.io.*;
import java.nio.file.Files;
import android.content.Context;
import org.json.JSONObject;
final class Store {
    static File root(Context context) { return context.directory; }
    static void header(RandomAccessFile file, long bytes) throws IOException { file.write(new byte[44]); }
    static void write(File file, JSONObject metadata) throws IOException {
        Files.write(file.toPath(), metadata.toString().getBytes("UTF-8"));
    }
    static void seal(File part) throws IOException {
        File wav = new File(part.toString().replace(".part", ".wav"));
        Files.move(part.toPath(), wav.toPath());
        Files.move(new File(part + ".json").toPath(), new File(wav + ".json").toPath());
    }
}
"""
TAKE_HARNESS = """
import java.io.*;
import java.nio.file.*;
import android.content.Context;
import org.json.*;
public class CaptureTakeCheck {
    public static void main(String[] args) throws Exception {
        Context context = new Context();
        context.directory = new File(args[0]);
        String name;
        try (CaptureTake take = new CaptureTake(context, "android_microphone")) {
            name = take.name;
            take.route("phone", "Телефон", 0);
            take.audio.write(new byte[]{1, 0, 2, 0});
            take.route("phone", "Гарнитура", 2);
            take.audio.write(new byte[]{3, 0, 4, 0});
            take.gaps.put(new JSONObject().put("start", 0).put("seconds", 4 / 16000.0).put("end", 4 / 16000.0));
            take.gaps.put(new JSONObject().put("start", 3 / 16000.0).put("seconds", 1 / 16000.0));
            take.trim(2);
            take.route("ble", "ClipMic", 2);
            take.audio.write(new byte[]{5, 0, 6, 0});
            take.route("ble", "ClipMic", 4);
        }
        Path wav = context.directory.toPath().resolve(name);
        byte[] data = Files.readAllBytes(wav);
        assert java.util.Arrays.equals(java.util.Arrays.copyOfRange(data, 44, data.length), new byte[]{1,0,2,0,5,0,6,0});
        JSONObject saved = new JSONObject(new String(Files.readAllBytes(Paths.get(wav + ".json")), "UTF-8"));
        JSONArray routes = saved.getJSONArray("input_routes"), gaps = saved.getJSONArray("gaps");
        assert routes.length()==2 && routes.getJSONObject(0).getLong("start_frame")==0;
        assert routes.getJSONObject(1).getLong("start_frame")==2 && routes.getJSONObject(1).getString("transport").equals("ble");
        assert saved.getString("source").equals("android") && saved.getBoolean("awaiting_lesson");
        assert gaps.length()==1 && gaps.getJSONObject(0).getDouble("seconds")==2 / 16000.0;
        context.directory = Files.createDirectory(context.directory.toPath().resolve("empty")).toFile();
        try (CaptureTake empty = new CaptureTake(context, "android_microphone")) {
            name = empty.name;
        }
        assert !context.directory.toPath().resolve(name).toFile().exists();
    }
}
"""


class CaptureInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jdk = Path(os.environ["JAVA_HOME"]) / "bin" if "JAVA_HOME" in os.environ else None
        cls.javac = str(jdk / "javac") if jdk else shutil.which("javac")
        cls.java = str(jdk / "java") if jdk else shutil.which("java")
        if not cls.javac or not cls.java:
            raise unittest.SkipTest("Нужен JDK")
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.classes = Path(temp.name)
        generated = []
        for name, body in {**STUBS, PACKAGE + ".CaptureInputCheck": HARNESS}.items():
            package, simple = name.rsplit(".", 1)
            path = cls.classes / (name.replace(".", "/") + ".java")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("package " + package + ";\n" + body, encoding="utf-8")
            generated.append(path)
        subprocess.run([cls.javac, "-encoding", "UTF-8", "-d", cls.classes, SOURCE / "RecordingInput.java",
                        SOURCE / "ClipMicProbe.java", *generated], check=True)

    def check(self, name):
        subprocess.run([self.java, "-ea", "-cp", self.classes, PACKAGE + ".CaptureInputCheck", name],
                       check=True, timeout=10)

    def test_input_and_output_only_headsets(self):
        self.check("routes")

    def test_clipmic_needs_audio_and_releases_cancelled_stream(self):
        self.check("probe")

    def test_local_prefix_and_clipmic_share_one_timeline(self):
        jar = os.environ.get("ANDROID_JSON_JAR")
        if not jar or not Path(jar).is_file():
            self.skipTest("Нужен ANDROID_JSON_JAR")
        cp = os.pathsep.join([str(self.classes), jar])
        sources = []
        for name, body in [("Store", TAKE_STORE), ("CaptureTakeCheck", TAKE_HARNESS)]:
            path = self.classes / (name + ".java")
            path.write_text("package " + PACKAGE + ";\n" + body, encoding="utf-8")
            sources.append(path)
        subprocess.run([self.javac, "-cp", cp, "-encoding", "UTF-8", "-d", self.classes,
                        SOURCE / "CaptureTake.java", *sources], check=True)
        with tempfile.TemporaryDirectory() as storage:
            subprocess.run([self.java, "-ea", "-cp", cp, PACKAGE + ".CaptureTakeCheck", storage], check=True)


if __name__ == "__main__":
    unittest.main()
