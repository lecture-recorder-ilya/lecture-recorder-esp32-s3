"""Run with a JDK on PATH (or JAVA_HOME) and the Android JSON implementation.

Set ANDROID_JSON_JAR to com.vaadin.external.google:android-json:0.0.20131108.vaadin1
or let the test fetch that small JAR from Maven Central.
"""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile


SOURCE = Path(__file__).resolve().parents[1] / "outputs/android/src/ru/ilya/lecturerecorder"
PACKAGE = "ru.ilya.lecturerecorder"
JSON_PATH = "com/vaadin/external/google/android-json/0.0.20131108.vaadin1/android-json-0.0.20131108.vaadin1.jar"
JSON_SHA256 = "dfb7bae2f404cfe0b72b4d23944698cb716b7665171812a0a4d0f5926c0fac79"

STUBS = {
    "Context.java": """package android.content;
import java.io.File;
public final class Context {
    private final File root;
    public Context(File root) { this.root = root; }
    public File getFilesDir() { return root; }
    public SharedPreferences getSharedPreferences(String name, int mode) {
        throw new UnsupportedOperationException();
    }
    public interface SharedPreferences { boolean getBoolean(String key, boolean fallback); }
}
""",
    "BoardPhotos.java": f"""package {PACKAGE};
import android.content.Context;
import java.io.File;
final class BoardPhotos {{
    static File camera(Context context) {{ throw new UnsupportedOperationException(); }}
    static void recover(Context context) {{ throw new UnsupportedOperationException(); }}
}}
""",
    "LectureReaderActivity.java": f"""package {PACKAGE};
final class LectureReaderActivity {{
    static String clock(double seconds) {{ return Double.toString(seconds); }}
}}
""",
}

HARNESS = r"""package ru.ilya.lecturerecorder;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.util.HashSet;
import org.json.JSONArray;
import org.json.JSONObject;

public final class SummaryStateTest {
    private static final String NAME = "lecture-2026-11-22-12-34-56.wav";
    private static final String NEW_TEXT = "Новая расшифровка лекции";
    private static final String OLD_TEXT = "Прежняя расшифровка лекции";
    private static final String OLD_KEY = "phone:" + NAME + ":0";

    public static void main(String[] args) throws Exception {
        File root = new File(args[0]);
        Context context = new Context(root);
        File target = LectureNotes.file(context, NAME, true);
        File mac = LectureNotes.file(context, NAME, false);
        File history = new File(new File(root, "phone-note-history"), NAME);
        if (args[1].equals("replace")) {
            checkEvidence();
            checkPhrases();
            JSONArray oldSegments = segments(OLD_TEXT);
            oldSegments.getJSONObject(0).put("review_key", OLD_KEY);
            JSONObject oldReport = new JSONObject()
                    .put("subject", "Математика").put("topic", "Дифференциальные уравнения")
                    .put("teacher", "Преподаватель").put("duration", 42)
                    .put("overview", "Старое введение").put("warnings", new JSONArray().put("Старое предупреждение"))
                    .put("summary", new JSONArray().put(OLD_TEXT)).put("homework", new JSONArray().put("Старое задание"))
                    .put("draft", true).put("asr_engine", "vosk-small-ru")
                    .put("segments", oldSegments);
            JSONObject original = new JSONObject().put("file", NAME).put("report", oldReport)
                    .put("lesson", new JSONObject().put("date", "2026-11-22")).put("extra", "metadata");
            Store.write(target, original);
            Store.write(mac, original);
            String prior = Store.read(target);

            try {
                LectureNotes.saveTranscript(context, NAME, "Другой заголовок",
                        read(target), new JSONArray(), "gigaam-v3");
                throw new AssertionError("Empty recognition must fail");
            } catch (IOException expected) {
                require(prior.equals(Store.read(target)) && !history.exists(), "Original changed before ASR was ready");
            }

            require(history.getParentFile().mkdir(), "Set up archive failure");
            require(history.createNewFile(), "Block archive directory");
            replacementMustFail(context, target);
            require(prior.equals(Store.read(target)), "Archive failure replaced the old document");
            require(history.delete(), "Unblock archive directory");

            File part = new File(target.getPath() + ".tmp");
            require(part.mkdir(), "Block transcript write");
            replacementMustFail(context, target);
            require(prior.equals(Store.read(target)), "Write failure replaced the old document");
            require(part.delete(), "Unblock transcript write");

            LectureNotes.saveTranscript(context, NAME, "Другой заголовок", read(target), segments(NEW_TEXT), "gigaam-v3");
            JSONObject pending = read(target);
            JSONObject report = pending.getJSONObject("report");
            require(report.optBoolean("local_summary_pending"), "New transcript must invalidate the summary");
            for (String field : new String[]{"summary", "homework", "overview", "warnings", "draft"}) {
                require(!report.has(field), "Stale field: " + field);
            }
            require("Математика".equals(report.getString("subject"))
                    && "Дифференциальные уравнения".equals(report.getString("topic"))
                    && "Преподаватель".equals(report.getString("teacher")) && report.getInt("duration") == 42
                    && "2026-11-22".equals(pending.getJSONObject("lesson").getString("date"))
                    && "metadata".equals(pending.getString("extra")), "Lesson metadata was lost");
            JSONObject line = report.getJSONArray("segments").getJSONObject(0);
            require(NEW_TEXT.equals(line.getString("text")) && line.getInt("start") == 5
                    && "gigaam-v3".equals(report.getString("asr_engine")), "New transcript was not saved");
            require(!OLD_KEY.equals(line.getString("review_key")), "Review mark leaked from the old transcript");
            require(prior.equals(Store.read(mac)) && prior.equals(archive(history)), "Mac note or archive changed");

            // Generating a summary changes the in-memory document. Ending the process here
            // simulates interruption before the summary checkpoint.
            report.put("summary", new JSONArray().put(NEW_TEXT)).put("homework", new JSONArray());
            System.out.println("PASS: replacement guards, pending transcript, lesson metadata, archive and Mac copy");
        } else {
            JSONObject pending = read(target);
            JSONObject report = pending.getJSONObject("report");
            require(report.optBoolean("local_summary_pending") && !report.has("summary"), "Restart lost pending state");
            JSONArray rows = report.getJSONArray("segments");
            require(NEW_TEXT.equals(rows.getJSONObject(0).getString("text")), "Restart lost the new transcript");
            report.put("summary", new JSONArray().put(rows.getJSONObject(0).getString("text")))
                    .put("homework", new JSONArray());
            File part = new File(target.getPath() + ".tmp");
            require(part.mkdir(), "Block summary write");
            try {
                LectureNotes.saveSummary(context, pending);
                throw new AssertionError("Summary write should have failed");
            } catch (IOException expected) {
                JSONObject onDisk = read(target).getJSONObject("report");
                require(onDisk.optBoolean("local_summary_pending") && !onDisk.has("summary"),
                        "Failed summary write changed the pending transcript");
            }
            require(part.delete(), "Unblock summary write");
            LectureNotes.saveSummary(context, pending);
            JSONObject completed = read(target);
            require(!completed.getJSONObject("report").has("local_summary_pending"), "Summary stayed pending");
            String shared = LectureNotes.summary(completed);
            require(shared.contains(NEW_TEXT) && !shared.contains(OLD_TEXT), "Shared summary is stale");
            require(archive(history).equals(Store.read(mac)), "Finishing re-archived or altered the previous result");
            System.out.println("PASS: separate JVM resumed summary from disk and preserved the previous result");
        }
    }

    private static void checkPhrases() throws Exception {
        PhonePhrases builder = new PhonePhrases();
        builder.accept(new JSONArray()
                .put(new JSONObject().put("word", "…").put("start", 0).put("end", .04))
                .put(new JSONObject().put("word", "Нет.").put("start", 1).put("end", 1.35))
                .put(new JSONObject().put("word", ".").put("start", 5).put("end", 5.04)));
        JSONArray result = builder.finish();
        require(result.length() == 1 && "Нет.".equals(result.getJSONObject(0).getString("text")),
                "Punctuation-only noise must not create a transcript");
        require(result.getJSONObject(0).getDouble("start") == 1, "Speech timestamp must be preserved");

        builder = new PhonePhrases();
        builder.accept(new JSONArray()
                .put(new JSONObject().put("word", "Это").put("start", 4).put("end", 4.2))
                .put(new JSONObject().put("word", "по-русски.").put("start", 4.37).put("end", 4.8)));
        JSONObject row = builder.finish().getJSONObject(0);
        TranscriptEdits.Line line = new TranscriptEdits.Line(row, 0, true, new JSONObject());
        require(line.words.size() == 2 && line.words.get(0).audioStartMillis == 4000
                && line.words.get(1).audioStartMillis == 4370, "Word seek must keep millisecond timing and hyphens");
        JSONObject corrections = new JSONObject().put(line.key, new JSONObject().put("original", line.original)
                .put("words", new JSONObject().put("1", new JSONObject().put("original", "по-русски")
                        .put("replacement", "на русском"))));
        TranscriptEdits.Line corrected = new TranscriptEdits.Line(row, 0, true, corrections);
        require("на русском".equals(corrected.words.get(1).value)
                && corrected.words.get(1).audioStartMillis == 4370, "A local correction must keep source playback");
        JSONObject note = new JSONObject().put("report", new JSONObject().put("segments",new JSONArray().put(row)));
        TranscriptEdits.apply(note, corrections, true);
        require(!row.has("word_times"), "Rewritten export cannot reuse old offsets");
        require(new TranscriptEdits.Line(row, 0, true, new JSONObject()).words.get(0).audioStartMillis == -1,
                "Old transcripts must not invent a word timestamp");
    }

    private static void checkEvidence() throws Exception {
        JSONArray rows = new JSONArray();
        String point = "Если функция непрерывна, то предел совпадает с её значением";
        String assignment = "К следующей паре решите задачу номер пять";
        for (String quote : new String[]{point, "Сомнительный термин из записи", assignment,
                "Например, на дом решите другую задачу", "На дом не надо решать задачу восемь",
                "На дом решили задачу девять", "Сейчас решите задачу два"}) {
            rows.put(new JSONObject().put("text", quote).put("start", rows.length() * 2)
                    .put("end", rows.length() * 2 + 1));
        }
        rows.getJSONObject(1).put("needs_review", true);
        JSONArray points = new JSONArray(), sources = new JSONArray(), tasks = new JSONArray();
        PhoneSummaryEvidence.add("KEY: 1,2,99\nTASK: 3,4,5,6", 0, 7, rows,
                points, sources, tasks, new HashSet<>(), new HashSet<>());
        require(points.length() == 1 && point.equals(points.getString(0)), "Summary must keep a complete verified quote");
        JSONObject source = sources.getJSONObject(0);
        require(point.equals(source.getString("quote")) && source.getInt("start") == 0, "Quote must link to its audio");
        require(tasks.length() == 1 && assignment.equals(tasks.getJSONObject(0).getString("quote")), "Only explicit, supported homework is kept");

        PhoneSummaryEvidence.add("KEY: 7 — придуманный вывод\nTASK: 7", 0, 7, rows,
                points, sources, tasks, new HashSet<>(), new HashSet<>());
        require(points.length() == 1 && tasks.length() == 1, "Reject free text and classwork");
        String condition = "Если определитель равен нулю,";
        String consequence = "то система не имеет единственного решения.";
        JSONArray adjacent = new JSONArray()
                .put(new JSONObject().put("text", condition).put("start", 7).put("end", 10))
                .put(new JSONObject().put("text", consequence).put("start", 10.3).put("end", 13));
        JSONArray valid = new JSONArray(), anchors = new JSONArray();
        PhoneSummaryEvidence.add("KEY: 2", 0, 2, adjacent, valid, anchors,
                new JSONArray(), new HashSet<>(), new HashSet<>());
        require(valid.length() == 1 && (condition + " " + consequence).equals(valid.getString(0)),
                "Evidence must retain the complete conditional statement");
        require(anchors.getJSONObject(0).getInt("start") == 7 && anchors.getJSONObject(0).getInt("end") == 13,
                "Evidence must play both adjacent phrases");
        adjacent.getJSONObject(0).put("needs_review", true);
        valid = new JSONArray();
        PhoneSummaryEvidence.add("KEY: 2", 0, 2, adjacent, valid, new JSONArray(),
                new JSONArray(), new HashSet<>(), new HashSet<>());
        require(valid.length() == 0, "A missing or unclear condition cannot yield a confident conclusion");
        adjacent.getJSONObject(0).put("needs_review", false);
        adjacent.getJSONObject(1).put("start", 12);
        valid = new JSONArray();
        PhoneSummaryEvidence.add("KEY: 1,2", 0, 2, adjacent, valid, new JSONArray(),
                new JSONArray(), new HashSet<>(), new HashSet<>());
        require(valid.length() == 0, "Distant fragments must not be joined");
        String uncertainNumber = "Сопротивление равно пятнадцати омам.";
        String unfinishedDate = "На дом решите задачу 15. Срок пока не утверждён.";
        JSONArray critical = segments(uncertainNumber)
                .put(new JSONObject().put("text", unfinishedDate).put("start", 12).put("end", 16));
        JSONArray criticalPoints = new JSONArray(), criticalTasks = new JSONArray();
        PhoneSummaryEvidence.add("KEY: 1\nTASK: 2", 0, 2, critical, criticalPoints, new JSONArray(),
                criticalTasks, new HashSet<>(), new HashSet<>());
        require(criticalPoints.length() == 0, "Uncertain number must not become a confident summary point");
        require(criticalTasks.length() == 1 && unfinishedDate.equals(criticalTasks.getJSONObject(0).getString("task"))
                        && !criticalTasks.getJSONObject(0).has("deadline"),
                "Homework must keep the number and leave the unsettled date unspecified");
        System.out.println("PASS: verbatim quotes, timestamps, uncertainty and explicit homework");
    }

    private static JSONArray segments(String text) throws Exception {
        return new JSONArray().put(new JSONObject().put("text", text).put("start", 5).put("end", 9)
                .put("needs_review", true));
    }

    private static void replacementMustFail(Context context, File target) throws Exception {
        try {
            LectureNotes.saveTranscript(context, NAME, "Title", read(target), segments(NEW_TEXT), "gigaam-v3");
            throw new AssertionError("Replacement should have failed");
        } catch (IOException expected) {
            // A blocked archive or write must leave the active note in place.
        }
    }

    private static JSONObject read(File note) throws Exception {
        return new JSONObject(Store.read(note));
    }

    private static String archive(File history) throws Exception {
        File[] snapshots = history.listFiles();
        require(snapshots != null && snapshots.length == 1, "Expected exactly one archived snapshot");
        return Store.read(snapshots[0]);
    }

    private static void require(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}
"""


def main():
    java_bin = Path(os.environ["JAVA_HOME"]) / "bin" if "JAVA_HOME" in os.environ else Path()
    with tempfile.TemporaryDirectory(prefix="phone-summary-") as temp:
        root = Path(temp)
        jar = root / "android-json.jar"
        if "ANDROID_JSON_JAR" in os.environ:
            jar = Path(os.environ["ANDROID_JSON_JAR"]).resolve()
        else:
            subprocess.run(
                ["curl", "-fLsS", "--max-time", "30", f"https://repo.maven.apache.org/maven2/{JSON_PATH}",
                 "-o", str(jar)],
                check=True,
            )
        if hashlib.sha256(jar.read_bytes()).hexdigest() != JSON_SHA256:
            raise ValueError("Unexpected Android JSON JAR checksum")
        sources = {**STUBS, "SummaryStateTest.java": HARNESS}
        for name, source in sources.items():
            (root / name).write_text(source, encoding="utf-8")
        subprocess.run(
            [java_bin / "javac", "-encoding", "UTF-8", "-cp", jar, "-d", root,
             SOURCE / "LectureNotes.java", SOURCE / "Store.java", SOURCE / "PhoneSummaryEvidence.java",
             SOURCE / "PhonePhrases.java", SOURCE / "TranscriptEdits.java",
             *(root / name for name in sources)],
            check=True,
        )
        data = root / "data"
        data.mkdir()
        for phase in ("replace", "resume"):
            subprocess.run(
                [java_bin / "java", "-cp", os.pathsep.join((str(root), str(jar))),
                 f"{PACKAGE}.SummaryStateTest", data, phase],
                check=True,
            )


if __name__ == "__main__":
    main()
