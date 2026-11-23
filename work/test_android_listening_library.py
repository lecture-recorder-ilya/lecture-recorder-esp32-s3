import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/android/src/ru/ilya/lecturerecorder/ListeningLibrary.java"
PREFERENCES = """
package android.content;
import java.util.*;
public class SharedPreferences {
    private final Map<String,Object> values = new HashMap<>();
    public int getInt(String key, int fallback) { return (Integer)values.getOrDefault(key, fallback); }
    public boolean getBoolean(String key, boolean fallback) { return (Boolean)values.getOrDefault(key, fallback); }
    public Editor edit() { return new Editor(); }
    public class Editor {
        public Editor putInt(String k, int v) { values.put(k,v); return this; }
        public Editor putBoolean(String k, boolean v) { values.put(k,v); return this; }
        public Editor remove(String k) { values.remove(k); return this; }
        public void apply() {}
    }
}
"""
CONTEXT = """
package android.content;
import java.util.*;
public class Context {
    public static final int MODE_PRIVATE=0;
    private final Map<String,SharedPreferences> store = new HashMap<>();
    public SharedPreferences getSharedPreferences(String name,int mode) {
        return store.computeIfAbsent(name,key -> new SharedPreferences());
    }
}
"""
CHECK = """
package ru.ilya.lecturerecorder;
import android.content.Context;
import android.content.SharedPreferences;
public class ListeningCheck {
    public static void main(String[] args) {
        Context context = new Context();
        SharedPreferences old = context.getSharedPreferences("playback_positions",0);
        old.edit().putInt("lect1",42000).putInt("lect2",60000).apply();
        ListeningLibrary first = new ListeningLibrary(context), next = new ListeningLibrary(context);
        if (args[0].equals("migration")) {
            assert first.position("lect1",60000)==42000;
            assert next.position("lect2",60000)==0;
            assert old.getInt("lect2",-1)==-1;
            assert next.position("lect1",0)==42000;
            first.savePosition("lect1",0,60000);
            assert next.position("lect1",60000)==0;
            next.savePosition("lect1",12000,60000);
            assert first.position("lect1",60000)==12000;
            next.savePosition("lect1",60000,60000);
            assert first.position("lect1",60000)==0;
            assert first.position("unknown",100)==0;
        } else if (args[0].equals("favorites")) {
            assert !first.favorite("lect1");
            first.favorite("lect1",true);
            assert next.favorite("lect1") && !next.favorite("lect2");
            first.favorite("lect2",true);
            next.favorite("lect1",false);
            assert !first.favorite("lect1") && first.favorite("lect2");
            assert first.position("lect1",60000)==42000;
        } else if (args[0].equals("speed")) {
            assert first.speed()==ListeningLibrary.NORMAL;
            for(int i=0;i<ListeningLibrary.SPEEDS.length;i++) { first.speed(i); assert next.speed()==i; }
            int previous=next.speed(); first.speed(-20); assert next.speed()==previous;
            context.getSharedPreferences("listening_library",0).edit().putInt("playback_speed",999).apply();
            assert first.speed()==ListeningLibrary.NORMAL;
        } else {
            String lecture=ListeningLibrary.normalize("Разбор счёта, формулы и запись");
            assert ListeningLibrary.matches(lecture,ListeningLibrary.terms("  ФОРМУЛЫ   счета "));
            assert !ListeningLibrary.matches(lecture,ListeningLibrary.terms("формулы интеграл"));
            assert ListeningLibrary.terms("   ").length==0;
        }
    }
}
"""


class ListeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        jdk = Path(os.environ["JAVA_HOME"]) / "bin" if "JAVA_HOME" in os.environ else None
        javac = jdk / "javac" if jdk else shutil.which("javac")
        java = jdk / "java" if jdk else shutil.which("java")
        if not javac or not java:
            raise unittest.SkipTest("Нужен JDK")
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        dest = Path(temp.name)
        sources = []
        for filename, source in [("SharedPreferences", PREFERENCES), ("Context", CONTEXT), ("ListeningCheck", CHECK)]:
            path = dest / (filename + ".java")
            path.write_text(source)
            sources.append(path)
        subprocess.run([javac, "--release", "8", "-encoding", "UTF-8", "-d", dest, SOURCE, *sources], check=True)
        cls.command = [java, "-ea", "-cp", dest, "ru.ilya.lecturerecorder.ListeningCheck"]

    def test_positions_from_existing_installs_and_zero(self):
        subprocess.run([*self.command, "migration"], check=True)

    def test_favorites_persist_per_recording(self):
        subprocess.run([*self.command, "favorites"], check=True)

    def test_supported_speed_and_invalid_saved_value(self):
        subprocess.run([*self.command, "speed"], check=True)

    def test_search_on_normalized_russian_words(self):
        subprocess.run([*self.command, "search"], check=True)


if __name__ == "__main__":
    unittest.main()
