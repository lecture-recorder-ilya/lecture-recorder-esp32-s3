package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class PhonePhrases {
    private final JSONArray segments = new JSONArray();
    private final StringBuilder text = new StringBuilder();
    private double start, end, confidence;
    private boolean uncertain, sentenceEnd;
    private int count;

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
            text.append(token);
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
        segments.put(new JSONObject().put("start", start).put("end", end).put("text", text.toString())
                .put("needs_review", uncertain || confidence / count < .78));
        count = 0;
        text.setLength(0);
        confidence = 0;
        uncertain = false;
        sentenceEnd = false;
    }
}
