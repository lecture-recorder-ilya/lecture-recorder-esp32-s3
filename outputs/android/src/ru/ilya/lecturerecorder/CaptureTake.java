package ru.ilya.lecturerecorder;

import android.content.Context;
import android.os.SystemClock;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

final class CaptureTake implements AutoCloseable {
    final RandomAccessFile audio;
    final String name;
    final JSONArray gaps = new JSONArray();
    long localPrefixFrames = -1;
    private final JSONArray routes = new JSONArray();
    private final File part;
    private final File sidecar;
    private final JSONObject metadata;
    private String previousLabel = "";
    private long lastCheckpoint;

    CaptureTake(Context context, String source) throws Exception {
        File directory = Store.root(context);
        if (directory.getUsableSpace() < 100L * 1024 * 1024) throw new IOException("На телефоне мало свободного места");
        long started = System.currentTimeMillis();
        SimpleDateFormat date = new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss", Locale.US);
        date.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));
        String stem = "lecture-" + date.format(new Date(started)) + "-" + String.format(Locale.US, "%06d", started % 1000 * 1000);
        name = stem + ".wav";
        part = new File(directory, stem + ".part");
        sidecar = new File(directory, stem + ".part.json");
        metadata = new JSONObject().put("started_ms", started).put("awaiting_lesson", true)
                .put("source", source).put("input_routes", routes).put("gaps", gaps);
        if (new File(directory, name).exists() || !part.createNewFile()) throw new IOException("Запись с этим временем уже существует");
        RandomAccessFile opened = null;
        try {
            opened = new RandomAccessFile(part, "rw");
            Store.header(opened, 0);
            saveMetadata();
            audio = opened;
        } catch (Exception failure) {
            if (opened != null) opened.close();
            if (part.delete()) sidecar.delete();
            throw failure;
        }
    }

    void route(String transport, String label, long frame) throws Exception {
        if (label.equals(previousLabel)) return;
        JSONObject entry = new JSONObject().put("start_frame", frame).put("start", frame / 16000.0)
                .put("transport", transport).put("label", label);
        routes.put(entry);
        previousLabel = label;
        metadata.put("source", transport.equals("phone") ? "android_microphone" : "android");
        saveMetadata();
    }

    void trim(long frame) throws Exception {
        long end = 44 + frame * 2;
        if (audio.length() == end) return;
        audio.setLength(end);
        audio.seek(end);
        while (routes.length() > 0 && routes.getJSONObject(routes.length() - 1).getLong("start_frame") >= frame) {
            routes.remove(routes.length() - 1);
        }
        previousLabel = routes.length() == 0 ? "" : routes.getJSONObject(routes.length() - 1).getString("label");
        double seconds = frame / 16000.0;
        for (int i = gaps.length() - 1; i >= 0; i--) {
            JSONObject gap = gaps.getJSONObject(i);
            double start = gap.getDouble("start");
            if (start >= seconds) gaps.remove(i);
            else if (start + gap.getDouble("seconds") > seconds) {
                gap.put("seconds", seconds - start);
                if (gap.has("end")) gap.put("end", seconds);
            }
        }
        saveMetadata();
    }

    void saveMetadata() throws Exception {
        Store.write(sidecar, metadata);
    }

    boolean shouldCheckpoint() {
        return SystemClock.elapsedRealtime() - lastCheckpoint >= 2000;
    }

    void checkpoint() throws Exception {
        audio.getFD().sync();
        saveMetadata();
        lastCheckpoint = SystemClock.elapsedRealtime();
        checkCapacity();
    }

    void checkCapacity() throws IOException {
        if (audio.length() > 4_200_000_000L || part.getUsableSpace() < 30L * 1024 * 1024)
            throw new IOException("Память заканчивается — запись сохранена");
    }

    void setError(String message) throws Exception {
        metadata.put("error", message);
    }

    @Override public void close() throws Exception {
        try {
            audio.getFD().sync();
        } finally {
            audio.close();
        }
        if (part.length() <= 44) {
            if (part.delete()) sidecar.delete();
            return;
        }
        try {
            saveMetadata();
        } finally {
            Store.seal(part);
        }
    }
}
