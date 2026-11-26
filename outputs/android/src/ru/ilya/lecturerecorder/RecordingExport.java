package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;

final class RecordingExport {
    enum Kind {
        WAV("WAV", "audio/wav", ".wav", "WAV"),
        TEXT("Расшифровка", "text/plain", " — расшифровка.txt", "TXT"),
        SUMMARY("Конспект", "text/markdown", " — конспект.md", "MD"),
        SRT("Субтитры", "application/x-subrip", ".srt", "SRT");

        final String label, mime, suffix, format;

        Kind(String label, String mime, String suffix, String format) {
            this.label = label;
            this.mime = mime;
            this.suffix = suffix;
            this.format = format;
        }
    }

    private RecordingExport() {}

    static String audioLabel(File audio) {
        try {
            JSONObject metadata = Store.readObject(new File(audio.getPath() + ".json"));
            if (metadata.optBoolean("imported")) return "Импортированная копия WAV";
            return metadata.optString("source").isEmpty() ? "Сохранённый WAV" : "Исходный WAV";
        } catch (Exception error) {
            return "Сохранённый WAV";
        }
    }

    static Intent picker(Context context, String name, Kind kind) {
        File audio = Store.audio(context, name);
        String title = RecordingLibraryPage.title(context, name, audio)
                .replaceAll("[\\p{Cntrl}/\\\\:]", " ").trim();
        String stem = name.substring("lecture-".length(), name.length() - 4);
        String date = stem.substring(0, Math.min(19, stem.length()));
        if (kind == Kind.WAV) title += " — " + audioLabel(audio);
        return new Intent(Intent.ACTION_CREATE_DOCUMENT).setType(kind.mime)
                .addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_TITLE, date + " — " + title + kind.suffix);
    }

    private static String stamp(double seconds) {
        long ms = Math.round(seconds * 1000);
        return String.format(java.util.Locale.ROOT, "%02d:%02d:%02d,%03d", ms/3600000, ms/60000%60, ms/1000%60, ms%1000);
    }

    static String subtitles(JSONObject report) throws IOException {
        org.json.JSONArray rows = report.optJSONArray("segments");
        StringBuilder text = new StringBuilder();
        int index = 0;
        for (int i = 0; rows != null && i < rows.length(); i++) {
            JSONObject row = rows.optJSONObject(i);
            if (row == null) continue;
            double start = row.optDouble("start"), end = row.optDouble("end");
            String quote = row.optString("text").trim().replaceAll("\\s+", " ");
            if (!Double.isFinite(start) || !Double.isFinite(end) || start < 0 || end <= start || quote.isEmpty()) continue;
            text.append(++index).append('\n').append(stamp(start)).append(" --> ").append(stamp(end))
                    .append('\n').append(quote).append("\n\n");
        }
        if (index == 0) throw new IOException("Пока нет фраз с таймкодами");
        return text.toString();
    }

    static void write(Context context, String name, Kind kind, Uri destination) throws Exception {
        byte[] text = null;
        if (kind != Kind.WAV) {
            boolean local = LectureNotes.file(context, name, true).isFile();
            File notes = LectureNotes.file(context, name, local);
            JSONObject document = new JSONObject(Store.read(notes));
            TranscriptEdits.apply(document, TranscriptEdits.read(TranscriptEdits.file(context, name)), local);
            String content = kind == Kind.SRT ? subtitles(document.getJSONObject("report")) :
                    kind == Kind.TEXT ? LectureNotes.text(document) : LectureNotes.summary(document);
            text = content.getBytes(StandardCharsets.UTF_8);
        }
        try (OutputStream output = context.getContentResolver().openOutputStream(destination, "wt")) {
            if (output == null) throw new IOException("Папка недоступна");
            if (kind == Kind.WAV) {
                try (FileInputStream input = new FileInputStream(Store.audio(context, name))) {
                    byte[] buffer = new byte[65536];
                    for (int length; (length = input.read(buffer)) != -1; ) output.write(buffer, 0, length);
                }
            } else {
                output.write(text);
            }
        }
    }
}
