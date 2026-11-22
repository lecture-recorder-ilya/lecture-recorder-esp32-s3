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
    "Log.java": """package android.util;
public final class Log { public static int w(String tag, String message, Throwable error) { return 0; } }
""",
    "PhoneAnalysisService.java": f"""package {PACKAGE};
final class PhoneAnalysisService {{
    static final class Job {{
        void check() {{}}
        void update(String message) {{}}
    }}
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
        checkSummaryCheckpoint(context, args[1].equals("replace"));
        File target = LectureNotes.file(context, NAME, true);
        File mac = LectureNotes.file(context, NAME, false);
        File history = new File(new File(root, "phone-note-history"), NAME);
        if (args[1].equals("replace")) {
            checkEvidence();
            checkLogicReview();
            checkLivePreview();
            checkRecordingNames(context);
            checkApprovedAcousticModel(context);
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
            checkEditedEvidence(context);
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

    private static void checkLivePreview() throws Exception {
        AnalysisPreview preview = new AnalysisPreview();
        require(preview.transcript(null) == null, "A summary-only job has no speech stream");
        preview.startSpeech();
        AnalysisPreview.Transcript empty = preview.transcript(null);
        PhonePhrases stream = new PhonePhrases(preview::addPhrase);
        JSONArray words = new JSONArray().put(new JSONObject().put("word", "Первый.").put("start", 1).put("end", 2))
                .put(new JSONObject().put("word", "Второй.").put("start", 3).put("end", 4));
        stream.accept(words);
        AnalysisPreview.Transcript first = preview.transcript(empty);
        require(first.rows.size() == 1 && empty.rows.isEmpty()
                && first.stream == empty.stream, "Sealed phrases must publish an immutable snapshot before completion");
        require(preview.transcript(first) == first, "Unchanged previews should not produce another snapshot");
        JSONArray finalRows = stream.finish();
        require(preview.transcript(first).rows.size() == 2 && finalRows.length() == 2,
                "Live publishing changed sentence boundaries");
        finalRows.getJSONObject(0).put("review_key", "persisted-only");
        require(!first.rows.get(0).contains("persisted-only"), "Saving a note must not mutate pending UI snapshots");
        preview.startSpeech();
        AnalysisPreview.Transcript retry = preview.transcript(first);
        require(retry.stream != first.stream && retry.rows.isEmpty(), "A fallback must reset its speech stream");
        preview.finishSpeech();
        require(preview.transcript(retry) == null, "Completed speech should display the saved report");
        preview.showSummary(new JSONArray().put("Проверенный вывод"), new JSONArray());
        require(new JSONObject(preview.summary).getJSONArray("summary").length() == 1, "Summary preview missing");
        System.out.println("PASS: live phrase publishing, fallback reset and summary preview");
    }

    private static void checkLogicReview() throws Exception {
        JSONArray rows = new JSONArray();
        String[] examples = {
            "Функция возрастает на данном промежутке определения.",
            "Функция не возрастает на данном промежутке определения.",
            "В этом примере сопротивление проводника равно пяти омам.",
            "В этом примере сопротивление проводника равно 5 омам.",
            "В этом примере сопротивление проводника равно пять омам.",
            "В этом примере сопротивление проводника равно 6 омам.",
            "В другом примере сопротивление проводника равно 7 омам."
        };
        for (int i = 0; i < examples.length; i++)
            rows.put(new JSONObject().put("start", i * 20).put("end", i * 20 + 5).put("text", examples[i]));
        String before = rows.toString();
        JSONArray review = PhoneLogicReview.evaluate(rows);
        require(review.length() == 2, "Report only nearby mismatches of the same wording");
        JSONObject negation = review.getJSONObject(0), number = review.getJSONObject(1);
        require(negation.getInt("before") == 0 && negation.getInt("after") == 1 && negation.optBoolean("negation"),
                "A changed negation must retain both transcript anchors");
        require(number.getInt("before") == 4 && number.getInt("after") == 5 && number.optBoolean("numbers"),
                "Equivalent written forms should not be flagged");
        require(before.equals(rows.toString()), "Logical review must preserve the recognized text");
        System.out.println("PASS: logical review detects mismatches and preserves words and timestamps");
    }

    private static void checkSummaryCheckpoint(Context context, boolean firstProcess) throws Exception {
        String name = "lecture-2026-11-23-15-01-00.wav";
        String quote = "Производная определяет скорость изменения функции.";
        String task = "К следующей паре решите задачу номер пять";
        JSONArray rows = new JSONArray()
                .put(new JSONObject().put("text", quote).put("start", 0).put("end", 4))
                .put(new JSONObject().put("text", task).put("start", 4).put("end", 7))
                .put(new JSONObject().put("text", quote).put("start", 7).put("end", 11));
        PhoneSummaryProgress progress = PhoneSummaryProgress.open(context, name, rows);
        if (firstProcess) {
            require(progress.next == 0, "A new summary must start at the beginning");
            PhoneSummaryEvidence.add("KEY: 1\nTASK: 2", 0, 2, rows, progress.summary,
                    progress.sources, progress.homework, progress.points, progress.tasks);
            progress.checkpoint(2);
            return;
        }
        require(progress.next == 2 && progress.summary.length() == 1 && progress.sources.length() == 1,
                "The new process must recover the cursor and the exact citation");
        require(progress.homework.length() == 1 && progress.tasks.contains(task), "Homework was not restored");
        JSONObject finished = new JSONObject().put("report",
                new JSONObject().put("segments", new JSONArray(rows.toString())).put("summary", progress.summary)
                .put("asr_engine", "gigaam-v3"));
        finished.getJSONObject("report").getJSONArray("segments").getJSONObject(0).put("review_key", "original");
        require(LectureNotes.hasSameFinishedTranscript(finished, rows, "gigaam-v3"),
                "Identical text and timing should reuse the finished summary");
        require(!LectureNotes.hasSameFinishedTranscript(finished, rows, "vosk-small-ru"),
                "A model change must rebuild the summary");
        PhoneSummaryEvidence.add("KEY: 1", 2, 3, rows, progress.summary,
                progress.sources, progress.homework, progress.points, progress.tasks);
        require(progress.summary.length() == 1 && quote.equals(progress.summary.getString(0)),
                "Resuming must preserve deduplication");
        rows.getJSONObject(0).put("text", "Отредактированный текст");
        require(PhoneSummaryProgress.open(context, name, rows).next == 0, "Changed transcript reused a checkpoint");
        require(!LectureNotes.hasSameFinishedTranscript(finished, rows, "gigaam-v3"),
                "A changed transcript must rebuild the summary");
        PhoneSummaryProgress.clear(context, name);
        require(PhoneSummaryProgress.open(context, name, rows).next == 0, "Finished checkpoint was retained");
        System.out.println("PASS: summary resumed in a new process with unchanged citations and no duplicates");
    }

    private static void checkApprovedAcousticModel(Context context) throws Exception {
        File models = new File(context.getFilesDir(), "phone-models");
        require(models.mkdirs(), "Create model fixture directory");
        File trial = new File(models, "gigaam-personal.int8.onnx");
        File acoustic = new File(models, "gigaam-v3-e2e-ctc.int8.onnx");
        File summary = new File(models, "qwen3-0.6b-int4.litertlm");
        require(trial.createNewFile(), "Create experimental model marker");
        try (java.io.RandomAccessFile file = new java.io.RandomAccessFile(summary, "rw")) {
            file.setLength(343490560L);
        }
        require(!PhoneModels.ready(context), "An experimental model is not a verified cached model");
        try (java.io.RandomAccessFile file = new java.io.RandomAccessFile(acoustic, "rw")) {
            file.setLength(224893347L);
        }
        require(PhoneModels.ready(context), "The verified model is available");
        require(acoustic.equals(PhoneModels.acoustic(context, new PhoneAnalysisService.Job())),
                "The experimental file must not override the stock model");
        require(trial.isFile(), "Model selection removed a user's file");
    }

    private static void checkRecordingNames(Context context) throws Exception {
        String name = "lecture-2026-11-22-12-30-00.wav";
        String date = Store.recordingTitle(name);
        JSONObject transcript = LectureNotes.saveTranscript(context, name, date, null, segments(NEW_TEXT), "gigaam-v3");
        require(date.equals(Store.recordingTitle(context, name)), "A date placeholder became a label");
        LectureNotes.saveTopic(context, transcript, "Уравнения первого порядка");
        JSONObject saved = read(LectureNotes.file(context, name, true)).getJSONObject("report");
        require(saved.optBoolean(LectureNotes.SUMMARY_PENDING), "A topic marked the unfinished summary as ready");
        require(("Уравнения первого порядка · " + date).equals(Store.recordingTitle(context, name)), "Detected topic missing from picker");
        File lesson = Store.lessonFile(context, name);
        Store.write(lesson, new JSONObject().put("subject", "Математика"));
        require(("Математика · " + date).equals(Store.recordingTitle(context, name)), "Detected topic replaced the selected subject");
        require(lesson.delete() && LectureNotes.file(context, name, true).delete(), "Could not clean the naming fixture");
    }

    private static void checkEditedEvidence(Context context) throws Exception {
        String name = "lecture-2026-11-22-10-01-02.wav";
        String before = "Первый закон описывает опыт.";
        String after = "Второй закон описывает опыт.";
        JSONObject segment = new JSONObject().put("id", 17).put("text", before).put("start", 0).put("end", 4);
        JSONObject next = new JSONObject().put("text", "Следует вывод.").put("start", 4).put("end", 7);
        JSONObject anchor = new JSONObject().put("quote", before + " Следует вывод.")
                .put("segment_id", 17).put("start", 0).put("end", 7);
        JSONObject assignment = new JSONObject().put("quote", before).put("task", before)
                .put("segment_id", 0).put("start", 0).put("end", 4);
        JSONObject raw = new JSONObject().put("report", new JSONObject()
                .put("segments", new JSONArray().put(segment).put(next))
                .put("summary", new JSONArray().put(anchor.getString("quote")).put("Отдельный вывод").put(before))
                .put("overview", before + " Следует вывод. Отдельный вывод " + before)
                .put("summary_evidence", new JSONArray().put(anchor))
                .put("homework", new JSONArray().put(assignment)));
        TranscriptEdits.Line line = new TranscriptEdits.Line(segment, 0, true, new JSONObject());
        TranscriptEdits.save(context, name, line, 0, "Второй");
        JSONObject edits = TranscriptEdits.read(TranscriptEdits.file(context, name));
        JSONObject view = new JSONObject(raw.toString());
        TranscriptEdits.apply(view, edits, true);
        JSONObject report = view.getJSONObject("report");
        require(after.equals(report.getJSONArray("segments").getJSONObject(0).getString("text")), "Word edit lost");
        require((after + " Следует вывод.").equals(report.getJSONArray("summary").getString(0)), "Stale summary after word edit");
        require((after + " Следует вывод.").equals(report.getJSONArray("summary_evidence").getJSONObject(0).getString("quote")), "Stale evidence");
        require("Отдельный вывод".equals(report.getJSONArray("summary").getString(1)) && after.equals(report.getJSONArray("summary").getString(2)), "Legacy exact quote");
        require((after + " Следует вывод. Отдельный вывод " + after).equals(report.getString("overview")), "Stale derived Mac overview");
        JSONObject authored = new JSONObject(raw.toString());
        authored.getJSONObject("report").put("overview", "Авторское вступление. " + before);
        TranscriptEdits.apply(authored, edits, true);
        require(("Авторское вступление. " + before).equals(authored.getJSONObject("report").getString("overview")), "Overwrote authored overview");
        require(after.equals(report.getJSONArray("homework").getJSONObject(0).getString("task")), "Stale task after edit");
        require(7 == report.getJSONArray("summary_evidence").getJSONObject(0).getInt("end"), "Lost audio anchor");
        require(LectureNotes.summary(view).contains(after) && !LectureNotes.summary(view).contains(before), "Stale export");
        JSONObject mac = new JSONObject(raw.toString());
        TranscriptEdits.apply(mac, edits, false);
        require(mac.toString().equals(raw.toString()), "Phone edit changed independent Mac note");
        TranscriptEdits.save(context, name, line, 0, "Первый");
        JSONObject restored = new JSONObject(raw.toString());
        TranscriptEdits.apply(restored, TranscriptEdits.read(TranscriptEdits.file(context, name)), true);
        require(restored.toString().equals(raw.toString()), "Undo lost the original quote");
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
             SOURCE / "PhonePhrases.java", SOURCE / "TranscriptEdits.java", SOURCE / "PhoneModels.java",
             SOURCE / "PhoneSummaryProgress.java", SOURCE / "PhoneLogicReview.java", SOURCE / "AnalysisPreview.java",
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
