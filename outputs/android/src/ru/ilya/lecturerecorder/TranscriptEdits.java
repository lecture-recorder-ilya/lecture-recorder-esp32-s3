package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class TranscriptEdits {
    private static final String WORD_PART = "[\\p{L}\\p{M}\\p{N}]+";
    private static final Pattern WORD = Pattern.compile(WORD_PART + "(?:['’‑-]" + WORD_PART + ")*");
    static final int MAX_REPLACEMENT = 160;

    static File file(Context context, String recording) {
        if (!LectureNotes.valid(recording)) throw new IllegalArgumentException("Некорректное имя записи");
        File folder = new File(context.getFilesDir(), "transcript-edits");
        return new File(folder, recording + ".json");
    }

    static String stamp(File file) {
        return file.lastModified() + ":" + file.length();
    }

    static JSONObject read(File file) throws IOException, JSONException {
        return file.isFile() ? new JSONObject(Store.read(file)) : new JSONObject();
    }

    static synchronized void save(Context context, String recording, Line line, int index, String replacement)
            throws IOException, JSONException {
        Word word = line.words.get(index);
        String value = replacement.trim();
        if (value.isEmpty() || value.length() > MAX_REPLACEMENT || value.contains("\n") || value.contains("\r")) {
            throw new IOException("Введи слово или короткую фразу");
        }
        File file = file(context, recording);
        JSONObject document = read(file);
        JSONObject previous = document.optJSONObject(line.key);
        JSONObject replacements = changes(previous, line.original);
        if (replacements == null) replacements = new JSONObject();
        String wordIndex = Integer.toString(index);
        if (value.equals(word.original)) {
            replacements.remove(wordIndex);
        } else {
            replacements.put(wordIndex, new JSONObject().put("original", word.original).put("replacement", value));
        }
        if (replacements.length() == 0) {
            document.remove(line.key);
        } else {
            document.put(line.key, new JSONObject().put("original", line.original).put("words", replacements));
        }
        File directory = file.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) throw new IOException("Папка правок недоступна");
        Store.write(file, document);
    }

    static void apply(JSONObject note, JSONObject corrections, boolean local) throws JSONException {
        JSONObject report = note.getJSONObject("report");
        JSONArray rows = report.optJSONArray("segments");
        if (rows == null || corrections.length() == 0) return;
        String[] originals = new String[rows.length()];
        boolean changed = false;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject segment = rows.optJSONObject(i);
            if (segment != null) {
                Line line = new Line(segment, i, local, corrections);
                originals[i] = line.original.trim();
                if (line.corrected) {
                    segment.put("text", line.text());
                    segment.remove("word_times");
                    changed = true;
                }
            }
        }
        if (!changed) return;
        report.remove("logic_review");
        JSONArray points = report.optJSONArray("summary");
        JSONArray sources = report.optJSONArray("summary_evidence");
        String overview = report.optString("overview");
        boolean derivedOverview = points != null && !overview.isEmpty() && overview.equals(summaryOverview(points));
        if (points != null) for (int i = 0; i < points.length(); i++) {
            if (!(points.opt(i) instanceof String)) continue;
            String point = points.getString(i);
            JSONObject source = sources == null ? null : sources.optJSONObject(i);
            String quote = source == null ? point : source.optString("quote");
            String revised = revisedQuote(quote, source, originals, rows);
            if (quote.equals(revised)) continue;
            if (source != null) source.put("quote", revised);
            if (quote.equals(point)) points.put(i, revised);
        }
        if (derivedOverview) report.put("overview", summaryOverview(points));
        JSONArray tasks = report.optJSONArray("homework");
        if (tasks != null) for (int i = 0; i < tasks.length(); i++) {
            JSONObject task = tasks.optJSONObject(i);
            if (task == null || !task.has("quote")) continue;
            String quote = task.getString("quote");
            String revised = revisedQuote(quote, task, originals, rows);
            if (!quote.equals(revised)) {
                task.put("quote", revised);
                if (quote.equals(task.optString("task"))) task.put("task", revised);
            }
        }
    }

    // The Mac writer derives its overview from the first three points, capped at 1500 Unicode characters.
    private static String summaryOverview(JSONArray points) {
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < Math.min(points.length(), 3); i++) {
            if (!(points.opt(i) instanceof String)) return "";
            if (i > 0) text.append(' ');
            text.append(points.optString(i));
        }
        int length = text.codePointCount(0, text.length());
        return length <= 1500 ? text.toString() : text.substring(0, text.offsetByCodePoints(0, 1500));
    }

    // Project only verbatim evidence. An older note can lack anchors; in that case
    // match one unique whole segment so a repeated phrase cannot change the wrong point.
    private static String revisedQuote(String quote, JSONObject anchor, String[] originals, JSONArray rows)
            throws JSONException {
        if (quote.isEmpty()) return quote;
        int id = anchor == null ? -1 : anchor.optInt("segment_id", -1);
        double start = anchor == null ? Double.NaN : anchor.optDouble("start");
        int index = -1;
        for (int i = 0; i < originals.length; i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null || originals[i] == null) continue;
            if (id >= 0 && i != id && row.optInt("id", -1) != id) continue;
            if (Double.isFinite(start) && row.optDouble("start") != start) continue;
            if (id < 0 && !quote.equals(originals[i])) continue;
            if (index >= 0) return quote;
            index = i;
        }
        if (index < 0) return quote;
        StringBuilder before = new StringBuilder(), after = new StringBuilder();
        for (int i = index; i < originals.length && originals[i] != null; i++) {
            JSONObject row = rows.getJSONObject(i);
            if (i != index) { before.append(' '); after.append(' '); }
            before.append(originals[i]);
            after.append(row.getString("text").trim());
            if (!quote.startsWith(before.toString())) break;
            if (before.length() == quote.length()) {
                if (anchor != null && anchor.has("end") && row.optDouble("end") != anchor.optDouble("end")) break;
                return after.toString();
            }
        }
        return quote;
    }

    private static JSONObject changes(JSONObject entry, String original) {
        return entry != null && original.equals(entry.optString("original")) ? entry.optJSONObject("words") : null;
    }

    static final class Line {
        final String key;
        final String original;
        final double start;
        final List<Word> words = new ArrayList<>();
        final boolean corrected;
        final boolean needsReview;

        Line(JSONObject segment, int index, boolean local, JSONObject corrections) {
            original = segment.optString("text");
            start = segment.optDouble("start");
            needsReview = segment.optBoolean("needs_review");
            key = (local ? "phone:" : "mac:") + index + ":" + segment.optString("start") + ":" + segment.optString("end");
            JSONObject replacements = changes(corrections.optJSONObject(key), original);
            Matcher matcher = WORD.matcher(original);
            JSONArray timings = segment.optJSONArray("word_times");
            double end = segment.optDouble("end");
            int timeIndex = 0;
            boolean changed = false;
            while (matcher.find()) {
                String source = matcher.group();
                JSONObject found = replacements == null ? null
                        : replacements.optJSONObject(Integer.toString(words.size()));
                String value = found != null && source.equals(found.optString("original"))
                        ? found.optString("replacement", source) : source;
                long audioStart = -1;
                while (timings != null && timeIndex < timings.length()) {
                    JSONArray time = timings.optJSONArray(timeIndex);
                    if (time == null || time.optInt(1, -1) <= matcher.start()) {
                        timeIndex++;
                        continue;
                    }
                    int first = time.optInt(0, -1);
                    int last = time.optInt(1, -1);
                    long millis = time.optLong(2, -1);
                    if (first >= 0 && first <= matcher.start() && last >= matcher.end() && last <= original.length()
                            && millis >= 0 && millis <= Integer.MAX_VALUE
                            && millis >= start * 1000 - 1 && millis <= end * 1000 + 1) {
                        audioStart = millis;
                    }
                    break;
                }
                words.add(new Word(source, value, matcher.start(), matcher.end(), audioStart));
                changed |= !source.equals(value);
            }
            corrected = changed;
        }

        String text() {
            StringBuilder result = new StringBuilder();
            int offset = 0;
            for (Word word : words) {
                result.append(original, offset, word.start).append(word.value);
                offset = word.end;
            }
            return result.append(original, offset, original.length()).toString();
        }
    }

    static final class Word {
        final String original;
        final String value;
        final int start;
        final int end;
        final long audioStartMillis;

        Word(String original, String value, int start, int end, long audioStartMillis) {
            this.original = original;
            this.value = value;
            this.start = start;
            this.end = end;
            this.audioStartMillis = audioStartMillis;
        }
    }

    private TranscriptEdits() {}
}
