package ru.ilya.lecturerecorder;

import android.content.Context;
import android.util.Log;
import com.google.ai.edge.litertlm.Backend;
import com.google.ai.edge.litertlm.Content;
import com.google.ai.edge.litertlm.Conversation;
import com.google.ai.edge.litertlm.ConversationConfig;
import com.google.ai.edge.litertlm.Engine;
import com.google.ai.edge.litertlm.EngineConfig;
import com.google.ai.edge.litertlm.Message;
import com.google.ai.edge.litertlm.SamplerConfig;
import com.google.ai.edge.litertlm.ThinkingConfig;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.vosk.Model;
import org.vosk.Recognizer;

import java.io.*;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class PhoneLectureAnalysis {
    private static final Pattern INDEXES = Pattern.compile("(?im)^\\s*(KEY|TASK)\\s*[:=]\\s*([0-9, ]{1,40})");
    private static final Pattern EXPLICIT_HOMEWORK = Pattern.compile(
            "\\b(?:на дом\\s+(?:решите|прочитайте|подготовьте|сделайте|выполните)|домашнее задание)\\b",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern HOMEWORK = Pattern.compile(
            "на дом|домашн|задани|к следующ|подготовь|подготовит|прочита|решите|сдайте|запиши",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);

    static void run(Context context, PhoneAnalysisService.Job job, String name, String title,
                    boolean retranscribe) throws Exception {
        File existing = LectureNotes.file(context, name, true);
        JSONObject document = null;
        if (existing.isFile()) {
            try {
                JSONObject saved = new JSONObject(Store.read(existing));
                saved.getJSONObject("report");
                document = saved;
            } catch (JSONException error) {
                if (!retranscribe) throw error;
            }
        }
        if (document == null || retranscribe) {
            JSONArray segments;
            String recognizer;
            try {
                File model = PhoneModels.acoustic(context, job);
                job.update("Загружаю модель речи");
                try {
                    segments = PhoneGigaAm.transcribe(context, job, name, model);
                    recognizer = PhoneModels.personalized(model) ? "gigaam-v3-personal" : "gigaam-v3";
                } catch (ai.onnxruntime.OrtException error) {
                    job.check();
                    if (!PhoneModels.personalized(model)) throw error;
                    Log.w("LectureAnalysis", "Personal acoustic model unavailable", error);
                    segments = PhoneGigaAm.transcribe(context, job, name, PhoneModels.acousticBase(context, job));
                    recognizer = "gigaam-v3";
                }
            } catch (IOException | ai.onnxruntime.OrtException | LinkageError error) {
                job.check();
                Log.w("LectureAnalysis", "Using the fallback speech model", error);
                File speech = PhoneModels.speech(context, job);
                job.update("Распознаю речь · 0%");
                segments = transcribeVosk(context, job, name, speech);
                recognizer = "vosk-small-ru";
            }
            if (segments.length() == 0) throw new IOException("В записи не удалось распознать русскую речь");
            if (document == null) {
                JSONObject report = new JSONObject().put("subject", title).put("topic", title)
                        .put("local_summary_pending", true);
                document = new JSONObject().put("file", name).put("report", report);
            }
            document.put("file", name).getJSONObject("report").put("segments", segments).put("asr_engine", recognizer);
            job.check();
            LectureNotes.saveLocal(context, document, retranscribe);
        }

        JSONObject report = document.getJSONObject("report");
        if (!report.optBoolean("local_summary_pending")) return;
        File text = PhoneModels.text(context, job);
        summarize(context, job, text, report);
        report.remove("local_summary_pending");
        job.check();
        LectureNotes.saveLocal(context, document);
    }

    static JSONArray transcribeVosk(Context context, PhoneAnalysisService.Job job, String name, File speech)
            throws Exception {
        JSONArray segments = new JSONArray();
        try (RandomAccessFile input = Store.openAudio(context, name);
             Model model = new Model(speech.getPath());
             Recognizer recognizer = new Recognizer(model, PcmWave.SAMPLE_RATE)) {
            long total = PcmWave.seekData(input);
            recognizer.setWords(true);
            byte[] buffer = new byte[8000];
            long remaining = total;
            int progress = 0;
            while (remaining > 0) {
                job.check();
                int size = (int) Math.min(remaining, buffer.length);
                input.readFully(buffer, 0, size);
                if (recognizer.acceptWaveForm(buffer, size)) append(segments, new JSONObject(recognizer.getResult()).optJSONArray("result"), name);
                remaining -= size;
                int percent = (int) (100 * (total - remaining) / total);
                if (percent != progress) {
                    progress = percent;
                    job.update("Распознаю речь · " + percent + "%");
                }
            }
            append(segments, new JSONObject(recognizer.getFinalResult()).optJSONArray("result"), name);
        }
        return segments;
    }

    static void append(JSONArray segments, JSONArray words, String name) throws Exception {
        if (words == null) return;
        for (int first = 0; first < words.length(); ) {
            JSONObject start = words.getJSONObject(first);
            StringBuilder phrase = new StringBuilder();
            double end = start.getDouble("end");
            double confidence = 0;
            boolean uncertain = false;
            int next = first;
            for (; next < words.length() && next - first < 22; next++) {
                JSONObject word = words.getJSONObject(next);
                if (next > first && word.getDouble("start") - end >= 0.30) break;
                if (next > first) phrase.append(' ');
                phrase.append(word.getString("word"));
                end = word.getDouble("end");
                double score = word.optDouble("conf", 1);
                confidence += score;
                uncertain |= score < 0.55;
            }
            if (phrase.length() != 0) {
                segments.put(new JSONObject()
                        .put("start", start.getDouble("start")).put("end", end).put("text", phrase.toString())
                        .put("needs_review", uncertain || confidence / (next - first) < 0.78)
                        .put("review_key", "phone:" + name + ":" + segments.length()));
            }
            first = next;
        }
    }

    private static void summarize(Context context, PhoneAnalysisService.Job job, File model, JSONObject report)
            throws Exception {
        JSONArray segments = report.getJSONArray("segments");
        JSONArray summary = new JSONArray();
        JSONArray homework = new JSONArray();
        Set<String> points = new HashSet<>();
        Set<String> tasks = new HashSet<>();
        job.update("Загружаю модель конспекта");
        EngineConfig config = new EngineConfig(model.getPath(), new Backend.CPU(4, null),
                null, null, 4096, null, context.getCacheDir().getPath());
        Engine engine = new Engine(config);
        engine.initialize();
        ConversationConfig conversationConfig = new ConversationConfig(null,
                Collections.emptyList(), Collections.emptyList(), new SamplerConfig(1, 1.0, 1.0, 42));
        try (Engine initialized = engine) {
            for (int first = 0; first < segments.length(); ) {
                job.check();
                job.update("Составляю конспект · " + (100 * first / segments.length()) + "%");
                StringBuilder input = new StringBuilder(
                        "Выбери важные утверждения из расшифровки лекции. Верни только номера строк. "
                        + "Две строки ответа: KEY: 2,4 (до четырёх ключевых фраз) и TASK: 5 "
                        + "(только явно заданное преподавателем, если нет — пусто). Пример формата, "
                        + "номера возьми из расшифровки.\n");
                int next = first;
                while (next < segments.length() && input.length() < 2200 && next - first < 36) {
                    input.append(next - first + 1).append(". ")
                            .append(segments.getJSONObject(next).getString("text")).append('\n');
                    next++;
                }
                try (Conversation conversation = initialized.createConversation(conversationConfig)) {
                    job.conversation = conversation;
                    try {
                        job.check();
                        Message answer = conversation.sendMessage(input.toString(), Collections.emptyMap(),
                                null, null, null, 64, new ThinkingConfig(false));
                        StringBuilder response = new StringBuilder();
                        for (Content item : answer.getContents().getContents()) {
                            if (item instanceof Content.Text) response.append(((Content.Text) item).getText());
                        }
                        addSelection(response.toString(), first, next, segments, summary, homework, points, tasks);
                    } finally {
                        job.conversation = null;
                    }
                }
                first = next;
            }
        }
        if (summary.length() == 0) throw new IOException("Модель не выделила ключевые фразы. Текст сохранён");
        report.put("summary", summary).put("homework", homework);
    }

    private static void addSelection(String response, int first, int next, JSONArray segments,
                                     JSONArray summary, JSONArray homework, Set<String> points, Set<String> tasks)
            throws Exception {
        SortedSet<Integer> keys = new TreeSet<>();
        SortedSet<Integer> exercises = new TreeSet<>();
        Matcher matcher = INDEXES.matcher(response);
        while (matcher.find()) {
            boolean exercise = matcher.group(1).equalsIgnoreCase("TASK");
            Set<Integer> selected = exercise ? exercises : keys;
            for (String number : matcher.group(2).trim().split("[, ]+")) {
                if (!number.matches("[0-9]{1,2}")) continue;
                int index = first + Integer.parseInt(number) - 1;
                if (index >= first && index < next && selected.size() < 4) selected.add(index);
            }
        }
        for (int index : keys) {
            String phrase = segments.getJSONObject(index).getString("text");
            if (phrase.length() >= 16 && points.add(phrase)) summary.put(phrase);
        }
        for (int index = first; index < next; index++) {
            JSONObject row = segments.getJSONObject(index);
            String phrase = row.getString("text");
            Matcher explicit = EXPLICIT_HOMEWORK.matcher(phrase);
            if (explicit.find()) phrase = phrase.substring(explicit.start());
            else if (!exercises.contains(index) || !HOMEWORK.matcher(phrase).find()) continue;
            if (tasks.add(phrase)) {
                homework.put(new JSONObject().put("task", phrase).put("quote", phrase)
                        .put("start", row.getDouble("start")));
            }
        }
    }

    private PhoneLectureAnalysis() {}
}
