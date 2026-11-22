package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class AnalysisPreview {
    static final class Transcript {
        final Object stream;
        final List<String> rows;

        Transcript(Object stream, List<String> rows) {
            this.stream = stream;
            this.rows = Collections.unmodifiableList(rows);
        }
    }

    private Object stream;
    private final ArrayList<String> speech = new ArrayList<>();
    volatile String summary;

    synchronized void startSpeech() {
        stream = new Object();
        speech.clear();
    }

    synchronized void addPhrase(JSONObject phrase) {
        if (stream != null) speech.add(phrase.toString());
    }

    synchronized Transcript transcript(Transcript previous) {
        if (stream == null) return null;
        if (previous != null && previous.stream == stream && previous.rows.size() == speech.size()) return previous;
        return new Transcript(stream, new ArrayList<>(speech));
    }

    synchronized void finishSpeech() {
        stream = null;
        speech.clear();
    }

    void showSummary(JSONArray points, JSONArray homework) throws JSONException {
        summary = new JSONObject().put("summary", points).put("homework", homework).toString();
    }
}
