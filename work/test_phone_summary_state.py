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
            checkSourceBinding();
            checkEditedDerivedData(new Context(new File(root, "derived-data")));
            checkPhrases();
            JSONArray oldSegments = segments(OLD_TEXT);
            oldSegments.getJSONObject(0).put("review_key", OLD_KEY);
            JSONObject oldReport = new JSONObject()
                    .put("subject", "Математика").put("topic", "Дифференциальные уравнения")
                    .put("teacher", "Преподаватель").put("duration", 42)
                    .put("overview", "Старое введение").put("warnings", new JSONArray().put("Старое предупреждение"))
                    .put("summary", new JSONArray().put(OLD_TEXT)).put("homework", new JSONArray().put("Старое задание"))
                    .put("formulas", new JSONArray().put(new JSONObject().put("latex", "x=5").put("quote", OLD_TEXT)))
                    .put("formula_review", new JSONArray().put(new JSONObject().put("candidate_latex", "x=50").put("quote", OLD_TEXT)))
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
            for (String field : new String[]{"summary", "summary_evidence", "homework", "formulas", "formula_review", "overview", "warnings", "draft"}) {
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
            checkIncomingOrder(context);
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

    private static void checkIncomingOrder(Context context) throws Exception {
        String name="lecture-2026-11-22-12-00-00-887766.wav";
        JSONObject note=new JSONObject().put("file",name);
        JSONObject report=new JSONObject();note.put("report",report);
        String[] texts={"Старое слово","Исправленное слово","Исправленное слово"};
        byte[][] versions=new byte[3][];
        for(int i=0;i<3;i++){
            report.put("segments",new JSONArray().put(new JSONObject().put("text",texts[i])));
            report.put("summary",new JSONArray().put(i<2?"Старый конспект":"Исправленный конспект"));
            note.put("sync_revision",Integer.toString(i+1));
            versions[i]=note.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
        }
        File target=LectureNotes.file(context,name,false);
        int[][] orders={{0,1,2},{2,0,1},{1,2,0},{0,2,1},{1,0,2},{2,1,0}};
        for(int[] order:orders){
            java.nio.file.Files.deleteIfExists(target.toPath());
            int highest=-1;
            for(int n:order){
                try{LectureNotes.save(context,versions[n]);require(n>highest,"Accepted stale content");highest=n;}
                catch(LectureNotes.RevisionConflict old){require(n<highest,"A newer report was refused");}
            }
            require(java.util.Arrays.equals(versions[2],java.nio.file.Files.readAllBytes(target.toPath())),"Mixed revisions");
            LectureNotes.save(context,versions[2]);
            for(String rev:new String[]{"3",null}){
                note.put("sync_revision",rev);report.put("summary",new JSONArray().put("Устаревший конспект"));
                try{LectureNotes.save(context,note.toString().getBytes("UTF-8"));throw new AssertionError("Stale retry accepted");}
                catch(LectureNotes.RevisionConflict expected){}
            }
        }
        System.out.println("PASS: шесть порядков доставки, повтор, конфликт номера и прежний отправитель");
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
        require(report.getJSONArray("summary").getString(1).equals("Отдельный вывод\nИсточник нужно сверить.")
                && after.equals(report.getJSONArray("summary").getString(2)), "Legacy exact quote or unverified source");
        require((after + " Следует вывод. Отдельный вывод\nИсточник нужно сверить. " + after).equals(report.getString("overview")), "Stale derived Mac overview");
        JSONObject authored = new JSONObject(raw.toString());
        authored.getJSONObject("report").put("overview", "Авторское вступление. " + before);
        TranscriptEdits.apply(authored, edits, true);
        require(("Авторское вступление. " + before).equals(authored.getJSONObject("report").getString("overview")), "Overwrote authored overview");
        require(after.equals(report.getJSONArray("homework").getJSONObject(0).getString("task")), "Stale task after edit");
        require(7 == report.getJSONArray("summary_evidence").getJSONObject(0).getInt("end"), "Lost audio anchor");
        require(LectureNotes.summary(view).contains(after) && !LectureNotes.summary(view).contains(before), "Stale export");
        JSONObject mac = new JSONObject(raw.toString());
        TranscriptEdits.apply(mac, edits, false);
        require(before.equals(mac.getJSONObject("report").getJSONArray("segments").getJSONObject(0).getString("text")), "Phone edit changed independent Mac note");
        TranscriptEdits.save(context, name, line, 0, "Первый");
        JSONObject restored = new JSONObject(raw.toString());
        TranscriptEdits.apply(restored, TranscriptEdits.read(TranscriptEdits.file(context, name)), true);
        require(before.equals(restored.getJSONObject("report").getJSONArray("summary").getString(2))
                && (before + " Следует вывод.").equals(restored.getJSONObject("report").getJSONArray("summary_evidence").getJSONObject(0).getString("quote")), "Undo lost the original quote");
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
        checkNoisyEvidence();
        System.out.println("PASS: verbatim quotes, timestamps, uncertainty and explicit homework");
    }

    private static void checkNoisyEvidence() throws Exception {
        for (String text : new String[]{"Если определитель равен нулю", "Если определитель равен нулю,",
                "При условии, что определитель равен нулю",
                "Структура суверенитета подвергается некой",
                "Если, например, определитель равен нулю,",
                "то система не имеет единственного решения."}) {
            JSONArray rows = new JSONArray().put(new JSONObject().put("text", text).put("start", 0).put("end", 3));
            JSONArray points = new JSONArray();
            PhoneSummaryEvidence.add("KEY: 1", 0, 1, rows, points, new JSONArray(), new JSONArray(),
                    new HashSet<>(), new HashSet<>());
            require(points.length() == 0, "Incomplete condition: " + text);
        }
        String left = "Если определитель равен нулю";
        String right = "то система не имеет единственного решения.";
        JSONArray split = new JSONArray()
                .put(new JSONObject().put("text", left).put("start", 0).put("end", 3))
                .put(new JSONObject().put("text", right).put("start", 3).put("end", 6));
        for (String selection : new String[]{"1", "2", "1,2"}) {
            JSONArray points = new JSONArray(), anchors = new JSONArray();
            PhoneSummaryEvidence.add("KEY: " + selection, 0, 2, split, points, anchors, new JSONArray(),
                    new HashSet<>(), new HashSet<>());
            require(points.length() == 1 && (left + " " + right).equals(points.getString(0)),
                    "Missing punctuation must not sever a condition");
            require(anchors.getJSONObject(0).getInt("start") == 0 && anchors.getJSONObject(0).getInt("end") == 6,
                    "Keep both source timestamps");
        }
        for (String text : new String[]{"Сопротивление равно не 15, а 150 ом.",
                "Сопротивление примерно 150 ом, точное значение не измерено.", "Этот метод не сходится.",
                "Когда началась промышленная революция?",
                "Если функция непрерывна, она ограничена.", "То есть функция ограничена на отрезке."}) {
            JSONArray rows = new JSONArray().put(new JSONObject().put("text", text).put("start", 0).put("end", 3));
            JSONArray points = new JSONArray();
            PhoneSummaryEvidence.add("KEY: 1", 0, 1, rows, points, new JSONArray(), new JSONArray(),
                    new HashSet<>(), new HashSet<>());
            require(points.length() == 1 && text.equals(points.getString(0)), "Changed a number or negation: " + text);
        }
        for (String text : new String[]{"На дом решите задачу 15. Сдайте примерно до пятницы.",
                "На дом решите задачу 15. Сдайте не к пятнице, а к понедельнику.",
                "На дом решите задачу 15. Сдать до пятницы не надо, сдайте к понедельнику.",
                "На дом решите задачу 15. Срок пока не утверждён."}) {
            JSONArray rows = new JSONArray().put(new JSONObject().put("text", text).put("start", 0).put("end", 5));
            JSONArray tasks = new JSONArray();
            PhoneSummaryEvidence.add("TASK: 1", 0, 1, rows, new JSONArray(), new JSONArray(), tasks,
                    new HashSet<>(), new HashSet<>());
            require(tasks.length() == 1 && text.equals(tasks.getJSONObject(0).getString("task"))
                    && !tasks.getJSONObject(0).has("deadline"), "Invented an exact deadline");
        }
        String cancelled = "На дом решите задачу 15. Сдавать её не надо.";
        JSONArray rows = new JSONArray().put(new JSONObject().put("text", cancelled).put("start", 0).put("end", 5));
        JSONArray tasks = new JSONArray();
        PhoneSummaryEvidence.add("TASK: 1", 0, 1, rows, new JSONArray(), new JSONArray(), tasks,
                new HashSet<>(), new HashSet<>());
        require(tasks.length() == 0, "Cancelled work must stay excluded");
        for (String correction : new String[]{"Задание отменяется.", "Нет, срок переносится на понедельник."}) {
            String assignment = "На дом решите задачу 15. Сдайте до пятницы.";
            for (boolean separate : new boolean[]{false, true}) {
                JSONArray lines = new JSONArray().put(new JSONObject().put("text", separate ? assignment : assignment + " " + correction)
                        .put("start", 1).put("end", 4));
                if (separate) lines.put(new JSONObject().put("text", correction).put("start", 4).put("end", 6));
                JSONArray work = new JSONArray();
                PhoneSummaryEvidence.add("TASK: 1", 0, lines.length(), lines, new JSONArray(), new JSONArray(), work,
                        new HashSet<>(), new HashSet<>());
                if (correction.startsWith("Задание")) require(work.length() == 0, "Отменённое ДЗ осталось в списке");
                else require(work.length() == 1 && (assignment + " " + correction).equals(work.getJSONObject(0).getString("quote"))
                        && work.getJSONObject(0).getInt("end") == (separate ? 6 : 4), "Потеряна поправка срока или таймкод");
            }
        }
        System.out.println("PASS: fixed noisy fixtures: deadlines, numbers, negations and incomplete conditions");
    }

    private static void checkEditedDerivedData(Context context) throws Exception {
        for (boolean local : new boolean[]{true, false}) {
            String name = local ? "lecture-2026-11-22-13-00-00.wav" : "lecture-2026-11-22-14-00-00.wav";
            String taskText = "На дом решите задачу 15. Сдайте до 15 ноября.";
            String formulaText = "Икс равен пяти.";
            JSONArray lines = new JSONArray()
                    .put(new JSONObject().put("id", 7).put("start", 10).put("end", 15).put("text", taskText))
                    .put(new JSONObject().put("id", 9).put("start", 20).put("end", 25).put("text", formulaText));
            JSONObject task = new JSONObject().put("quote", taskText).put("task", taskText).put("deadline", "до 15 ноября")
                    .put("segment_id", 7).put("start", 10).put("end", 15);
            JSONObject formula = new JSONObject().put("quote", formulaText).put("latex", "x=5")
                    .put("segment_id", 9).put("start", 20).put("end", 25);
            JSONObject report = new JSONObject().put("segments", lines).put("homework", new JSONArray().put(task))
                    .put("summary", new JSONArray().put(taskText).put(formulaText))
                    .put("summary_evidence", new JSONArray().put(new JSONObject(task.toString())).put(new JSONObject(formula.toString())))
                    .put("formulas", new JSONArray().put(formula));
            JSONObject original = new JSONObject().put("file", name).put("report", report);
            Store.write(LectureNotes.file(context, name, local), original);
            TranscriptEdits.Line line = new TranscriptEdits.Line(lines.getJSONObject(0), 0, local, new JSONObject());
            int lastNumber = -1;
            for (int i = 0; i < line.words.size(); i++) if (line.words.get(i).original.equals("15")) lastNumber = i;
            TranscriptEdits.save(context, name, line, lastNumber, "20");
            TranscriptEdits.Line math = new TranscriptEdits.Line(lines.getJSONObject(1), 1, local, new JSONObject());
            TranscriptEdits.save(context, name, math, 2, "пятидесяти");
            JSONObject edits = TranscriptEdits.read(TranscriptEdits.file(context, name));
            JSONObject view = new JSONObject(original.toString());
            TranscriptEdits.apply(view, edits, local);
            JSONObject revised = view.getJSONObject("report");
            String quote = "На дом решите задачу 15. Сдайте до 20 ноября.";
            require(quote.equals(revised.getJSONArray("summary").getString(0))
                    && quote.equals(revised.getJSONArray("homework").getJSONObject(0).getString("quote")), "Не обновлена цитата после правки числа");
            require(!revised.getJSONArray("homework").getJSONObject(0).has("deadline"), "Остался старый срок после правки");
            require(revised.getJSONArray("formulas").length() == 0, "Осталась старая LaTeX-формула после правки");
            JSONObject anchor = revised.getJSONArray("summary_evidence").getJSONObject(0);
            require(anchor.getInt("segment_id") == 7 && anchor.getInt("start") == 10 && anchor.getInt("end") == 15,
                    "Правка поменяла привязку к аудио");
            if (local) {
                JSONArray replacement = new JSONArray().put(new JSONObject().put("id", 0).put("start", 30).put("end", 34)
                        .put("text", "На дом решите задачу двадцать."));
                JSONObject pending = LectureNotes.saveTranscript(context, name, "Тест", new JSONObject(original.toString()), replacement, "fixed-test-ASR");
                require(!pending.getJSONObject("report").has("formulas"), "Новая расшифровка сохранила старую формулу");
                JSONArray points = new JSONArray(), sources = new JSONArray(), work = new JSONArray();
                PhoneSummaryEvidence.add("KEY: 1\nTASK: 1", 0, 1, replacement, points, sources, work, new HashSet<>(), new HashSet<>());
                pending.getJSONObject("report").put("summary", points).put("summary_evidence", sources).put("homework", work);
                LectureNotes.saveSummary(context, pending);
                JSONObject fresh = read(LectureNotes.file(context, name, true));
                TranscriptEdits.apply(fresh, edits, true);
                JSONObject freshAnchor = fresh.getJSONObject("report").getJSONArray("summary_evidence").getJSONObject(0);
                require(freshAnchor.getInt("start") == 30 && freshAnchor.getInt("end") == 34
                        && freshAnchor.getString("quote").equals(replacement.getJSONObject(0).getString("text")), "Старая правка попала в новый конспект");
                File history = new File(new File(context.getFilesDir(), "phone-note-history"), name);
                JSONObject archived = new JSONObject(archive(history));
                TranscriptEdits.apply(archived, edits, true);
                require(quote.equals(archived.getJSONObject("report").getJSONArray("summary").getString(0)),
                        "История потеряла прежний конспект или его ручную правку");
            }
        }
        System.out.println("PASS: правки Mac/Android, формулы, сроки, новые привязки и старый конспект в истории");
    }

    private static void checkSourceBinding() throws Exception {
        String quote="Икс не равен пяти.";
        JSONObject first=new JSONObject().put("id",7).put("start",1).put("end",4).put("text",quote);
        JSONObject report=new JSONObject().put("segments",new JSONArray().put(first))
                .put("summary",new JSONArray().put(quote)).put("summary_evidence",new JSONArray().put(
                    new JSONObject().put("quote",quote).put("segment_id",7).put("start",1).put("end",4)));
        SummarySources.reconcile(report,false,true);
        String hash=report.getJSONArray("summary_evidence").getJSONObject(0).getString("source_fingerprint");
        require(hash.equals("96ef901c669bbe7404464ae8a4b6d7042df5d3e4a2139564526a6217d77ca32f"),"Отпечатки Mac и Java различаются");
        report.put("segments",new JSONArray().put(new JSONObject().put("id",30).put("start",12).put("end",16).put("text",quote)));
        SummarySources.reconcile(report,false,false);
        JSONObject anchor=report.getJSONArray("summary_evidence").getJSONObject(0);
        require(anchor.getInt("segment_id")==30&&anchor.getInt("start")==12&&anchor.getInt("end")==16,
                "Сдвиг сегментов оставил старый переход к звуку");
        require(anchor.getJSONObject("original_source").getInt("start")==1,"Потерян исходный таймкод");
        report.getJSONArray("segments").put(new JSONObject().put("id",31).put("start",20).put("end",24).put("text",quote));
        // Убираем точное совпадение старого отпечатка, сохранив два новых варианта.
        report.getJSONArray("segments").getJSONObject(0).put("start",13).put("end",17);
        SummarySources.reconcile(report,false,false);anchor=report.getJSONArray("summary_evidence").getJSONObject(0);
        require(!anchor.has("start")&&anchor.getString("source_status").equals("needs_review")
                &&report.getJSONArray("summary").getString(0).contains(SummarySources.NOTICE),"Неоднозначный источник открывает старое аудио");
        report.put("segments",new JSONArray().put(first));SummarySources.reconcile(report,false,false);
        require(quote.equals(report.getJSONArray("summary").getString(0))
                &&report.getJSONArray("summary_evidence").getJSONObject(0).getInt("start")==1,"Восстановление версии не вернуло источник");
        report.put("segments",new JSONArray().put(new JSONObject().put("id",40).put("start",10).put("end",12).put("text","Икс не"))
                .put(new JSONObject().put("id",41).put("start",12).put("end",15).put("text","равен пяти.")));
        SummarySources.reconcile(report,false,false);anchor=report.getJSONArray("summary_evidence").getJSONObject(0);
        require(anchor.getInt("start")==10&&anchor.getInt("end")==15,"Новая нарезка потеряла часть цитаты");
        System.out.println("PASS: сдвиг, новая нарезка, неоднозначность, восстановление и общий отпечаток источника");
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
             SOURCE / "PhonePhrases.java", SOURCE / "TranscriptEdits.java", SOURCE / "SummarySources.java",
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
