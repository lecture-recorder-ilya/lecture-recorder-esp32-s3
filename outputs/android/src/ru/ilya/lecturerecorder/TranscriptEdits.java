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
        JSONArray rows = note.getJSONObject("report").optJSONArray("segments");
        if (rows == null) return;
        for (int i = 0; i < rows.length(); i++) {
            JSONObject segment = rows.optJSONObject(i);
            if (segment != null) {
                Line line = new Line(segment, i, local, corrections);
                if (line.corrected) segment.put("text", line.text());
            }
        }
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

        Line(JSONObject segment, int index, boolean local, JSONObject corrections) {
            original = segment.optString("text");
            start = segment.optDouble("start");
            key = (local ? "phone:" : "mac:") + index + ":" + segment.optString("start") + ":" + segment.optString("end");
            JSONObject replacements = changes(corrections.optJSONObject(key), original);
            Matcher matcher = WORD.matcher(original);
            boolean changed = false;
            while (matcher.find()) {
                String source = matcher.group();
                JSONObject found = replacements == null ? null
                        : replacements.optJSONObject(Integer.toString(words.size()));
                String value = found != null && source.equals(found.optString("original"))
                        ? found.optString("replacement", source) : source;
                words.add(new Word(source, value, matcher.start(), matcher.end()));
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

        Word(String original, String value, int start, int end) {
            this.original = original;
            this.value = value;
            this.start = start;
            this.end = end;
        }
    }

    private TranscriptEdits() {}
}
