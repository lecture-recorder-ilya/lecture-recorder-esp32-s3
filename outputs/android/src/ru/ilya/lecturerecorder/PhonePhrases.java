package ru.ilya.lecturerecorder;

import java.util.function.Consumer;
import java.util.regex.Pattern;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class PhonePhrases {
    private static final Pattern WORD = Pattern.compile("[\\p{L}\\p{N}]");
    private final Consumer<JSONObject> onPhrase;
    private final JSONArray segments = new JSONArray();
    private final StringBuilder text = new StringBuilder();
    private JSONArray wordTimes = new JSONArray();
    private double start, end, confidence;
    private boolean uncertain, sentenceEnd;
    private int count;

    PhonePhrases() {
        this(phrase -> {});
    }

    PhonePhrases(Consumer<JSONObject> onPhrase) {
        this.onPhrase = onPhrase;
    }

    void accept(JSONArray words) throws JSONException {
        if (words == null) return;
        for (int i = 0; i < words.length(); i++) {
            JSONObject word = words.getJSONObject(i);
            String token = word.getString("word");
            double time = word.getDouble("start");
            double until = word.getDouble("end");
            if (count > 0 && (sentenceEnd || time - end >= .65 || until - start > 8 || count >= 22)) flush();
            if (count == 0) start = time;
            else text.append(' ');
            int firstChar = text.length();
            text.append(token);
            if (WORD.matcher(token).find() && Double.isFinite(time) && time >= 0) {
                wordTimes.put(new JSONArray().put(firstChar).put(text.length()).put(Math.round(time * 1000)));
            }
            end = until;
            double score = word.optDouble("conf", 1);
            confidence += score;
            uncertain |= score < .55 || word.optBoolean("needs_review");
            sentenceEnd = token.matches(".*[.!?…][»\\\"’)]*$");
            count++;
        }
    }

    JSONArray finish() throws JSONException {
        flush();
        return segments;
    }

    private void flush() throws JSONException {
        if (count == 0) return;
        if (WORD.matcher(text).find()) {
            JSONObject phrase = new JSONObject().put("start", start).put("end", end).put("text", text.toString())
                    .put("needs_review", uncertain || confidence / count < .78).put("word_times", wordTimes);
            segments.put(phrase);
            onPhrase.accept(phrase);
        }
        count = 0;
        text.setLength(0);
        wordTimes = new JSONArray();
        confidence = 0;
        uncertain = false;
        sentenceEnd = false;
    }
}
