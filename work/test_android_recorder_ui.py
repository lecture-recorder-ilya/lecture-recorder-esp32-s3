import os
import re
import shutil
import subprocess
import time
import unittest
from pathlib import Path
from xml.etree import ElementTree
from work.android_ui_snapshot import LiveViewTree


class RecorderUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        serial = os.environ.get("FIELDNOTES_UI_SERIAL")
        if not serial:
            raise unittest.SkipTest("Для прогона на тестовом эмуляторе укажи FIELDNOTES_UI_SERIAL")
        cls.command = [os.environ.get("ADB") or shutil.which("adb") or "adb", "-s", serial]
        if cls.adb("shell", "getprop", "ro.kernel.qemu").strip() != b"1":
            raise RuntimeError("Для этой проверки нужен тестовый эмулятор Android")
        sdk = ("JAVA_HOME", "ANDROID_PLATFORM_JAR", "ANDROID_BUILD_TOOLS")
        cls.tree_reader = LiveViewTree(cls, cls.adb) if all(os.environ.get(key) for key in sdk) else None
        cls.package = os.environ.get("FIELDNOTES_UI_PACKAGE", "ru.ilya.lecturerecorder")
        cls.adb("shell", "pm", "grant", cls.package, "android.permission.RECORD_AUDIO")
        cls.adb("shell", "am", "start", "-W", "-n", cls.package + "/ru.ilya.lecturerecorder.MainActivity")

    @classmethod
    def adb(cls, *command):
        return subprocess.check_output([*cls.command, *map(str, command)], timeout=30, stderr=subprocess.STDOUT)

    def screen(self):
        if self.tree_reader is not None:
            self.xml = self.tree_reader.xml()
            return list(ElementTree.fromstring(self.xml).iter("node"))
        path = "/sdcard/fieldnotes-recorder-ui.xml"
        for _ in range(3):
            result = self.adb("shell", "uiautomator", "dump", path)
            if b"dumped to:" in result:
                self.xml = self.adb("exec-out", "cat", path)
                return list(ElementTree.fromstring(self.xml).iter("node"))
        self.fail(f"Android не вернул актуальное дерево экрана: {result!r}")

    def photograph(self, name):
        folder = os.environ.get("FIELDNOTES_UI_ARTIFACTS")
        if name and folder:
            target = Path(folder)
            target.mkdir(parents=True, exist_ok=True)
            (target / (name + ".xml")).write_bytes(self.xml)
            (target / (name + ".png")).write_bytes(self.adb("exec-out", "screencap", "-p"))

    def wait_for(self, label, description=False, photograph=None):
        end = time.monotonic() + 18
        while True:
            nodes = self.screen()
            for node in nodes:
                field = "content-desc" if description else "text"
                if node.get(field) == label and node.get("enabled") == "true":
                    if photograph:
                        self.photograph(photograph)
                    return node
            if time.monotonic() >= end:
                self.fail(f"{label!r}: {[node.get('text') for node in nodes if node.get('text')]}")

    def tap(self, node):
        left, top, right, bottom = map(int, re.findall(r"\d+", node.get("bounds")))
        self.adb("shell", "input", "tap", (left + right) // 2, (top + bottom) // 2)

    def test_record_save_open_and_return_to_library(self):
        initial = self.screen()
        up = next((n for n in initial if n.get("content-desc") == "Вернуться в библиотеку"), None)
        if up is not None:
            self.tap(up)
        self.tap(self.wait_for("Запись"))
        nodes = self.screen()
        self.assertFalse(any(n.get("text") == "Завершить запись" for n in nodes), "В эмуляторе уже идёт запись")
        new = next((n for n in nodes if n.get("text") == "Новая запись" and n.get("clickable") == "true"), None)
        if new is not None:
            self.tap(new)
        self.wait_for("зу")
        self.wait_for("Источник звука")
        self.wait_for("Импортировать аудио")
        self.tap(self.wait_for("Начать запись", photograph="01-ready"))
        self.wait_for("Идёт запись")
        self.wait_for("Микрофон телефона", photograph="04-recording")
        stop = self.wait_for("Завершить запись")
        self.tap(stop)
        self.wait_for("Запись сохранена", photograph="05-saved")
        saved = self.screen()
        duration = next(n.get("text") for n in saved if n.get("content-desc", "").startswith("Длительность записи "))
        self.assertNotEqual(duration, "00:00")
        self.tap(self.wait_for("Открыть запись"))
        self.wait_for("Слушать", photograph="06-audio")
        self.tap(self.wait_for("Вернуться в библиотеку", description=True))
        self.wait_for("Найти запись", photograph="07-library")
        self.assertTrue(any(duration in node.get("content-desc", "") for node in self.screen()))


    def test_rail_grows_with_large_labels_in_landscape(self):
        settings = [("system", "font_scale"), ("system", "accelerometer_rotation"), ("system", "user_rotation")]
        previous = {key: self.adb("shell", "settings", "get", *key).decode().strip() for key in settings}
        try:
            self.adb("shell", "settings", "put", "system", "accelerometer_rotation", "0")
            self.adb("shell", "settings", "put", "system", "user_rotation", "1")
            widths = []
            for scale in ("1.0", "1.6"):
                self.adb("shell", "settings", "put", "system", "font_scale", scale)
                time.sleep(.6)
                tab = self.wait_for("Библиотека", description=True)
                left, top, right, bottom = map(int, re.findall(r"\d+", tab.get("bounds")))
                self.assertLess(left, right - left)
                widths.append(right - left)
            self.assertGreater(widths[1], widths[0] * 1.15)
        finally:
            for key, value in reversed(list(previous.items())):
                if value == "null":
                    self.adb("shell", "settings", "delete", *key)
                else:
                    self.adb("shell", "settings", "put", *key, value)

    def test_system_microphone_block_and_restore(self):
        if int(self.adb("shell", "getprop", "ro.build.version.sdk")) < 31:
            self.skipTest("Для системного переключателя микрофона нужен Android 12 или новее")
        state = self.adb("shell", "dumpsys", "audio").decode()
        if not re.search(r"mic mute [^\n]*from system=false", state, re.IGNORECASE):
            self.skipTest("Для проверки нужен включённый микрофон тестового эмулятора")
        self.tap(self.wait_for("Запись"))
        initial = self.screen()
        new = next((n for n in initial if n.get("text") == "Новая запись" and n.get("clickable") == "true"), None)
        if new is not None:
            self.tap(new)
        self.tap(self.wait_for("Начать запись"))
        try:
            self.wait_for("Идёт запись")
            self.adb("shell", "cmd", "sensor_privacy", "enable", "0", "microphone")
            self.wait_for("Микрофон выключен", photograph="08-system-muted")
            self.adb("shell", "cmd", "sensor_privacy", "disable", "0", "microphone")
            self.wait_for("Идёт запись", photograph="09-system-restored")
        finally:
            self.adb("shell", "cmd", "sensor_privacy", "disable", "0", "microphone")
            self.tap(self.wait_for("Завершить запись"))
        self.wait_for("Запись сохранена")
