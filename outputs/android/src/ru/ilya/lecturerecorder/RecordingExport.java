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
        SUMMARY("Конспект", "text/markdown", " — конспект.md", "MD");

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

    static void write(Context context, String name, Kind kind, Uri destination) throws Exception {
        byte[] text = null;
        if (kind != Kind.WAV) {
            boolean local = LectureNotes.file(context, name, true).isFile();
            File notes = LectureNotes.file(context, name, local);
            JSONObject document = new JSONObject(Store.read(notes));
            TranscriptEdits.apply(document, TranscriptEdits.read(TranscriptEdits.file(context, name)), local);
            String content = kind == Kind.TEXT ? LectureNotes.text(document) : LectureNotes.summary(document);
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
