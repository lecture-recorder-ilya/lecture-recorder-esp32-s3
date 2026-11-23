package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

final class PhoneWordTimeline {
    private static final double MATCH_SECONDS = .08;
    private final PhonePhrases phrases;
    private final double overlap;
    private final List<JSONObject> pending = new ArrayList<>();

    PhoneWordTimeline(PhonePhrases phrases, double overlap) {
        this.phrases = phrases;
        this.overlap = overlap;
    }

    private static String lexical(JSONObject word) throws Exception {
        return word.getString("word").toLowerCase(Locale.ROOT).replace('ё', 'е')
                .replaceAll("^[«(]+|[.,;:!?…)»]+$", "");
    }

    private static boolean sameTime(JSONObject first, JSONObject second) throws Exception {
        boolean oneOriginal = first.optBoolean("_legacy_core") != second.optBoolean("_legacy_core");
        double tolerance = MATCH_SECONDS + (oneOriginal ? 1e-9 : -1e-9);
        return Math.abs(first.getDouble("end") - second.getDouble("end")) < tolerance
                && Math.max(first.getDouble("start"), second.getDouble("start"))
                < Math.min(first.getDouble("end"), second.getDouble("end"));
    }

    void accept(JSONArray words, double boundary) throws Exception {
        int previous = pending.size();
        boolean[] matched = new boolean[previous];
        for (int i = 0; i < words.length(); i++) {
            JSONObject word = words.getJSONObject(i);
            String text = lexical(word);
            int match = -1;
            double distance = Double.POSITIVE_INFINITY;
            for (int j = 0; j < previous; j++) {
                JSONObject other = pending.get(j);
                if (matched[j] || text.isEmpty() || !sameTime(word, other)) continue;
                boolean same = text.equals(lexical(other));
                if (!same && word.optBoolean("_legacy_core") == other.optBoolean("_legacy_core")) {
                    word.put("needs_review", true);
                    other.put("needs_review", true);
                    continue;
                }
                double delta = Math.abs(word.getDouble("end") - other.getDouble("end"));
                if (delta < distance) { distance = delta; match = j; }
            }
            if (match >= 0) {
                JSONObject other = pending.get(match);
                boolean same = text.equals(lexical(other));
                JSONObject keep = !other.optBoolean("_legacy_core") && word.optBoolean("_legacy_core") ? word : other;
                if (!same || word.optBoolean("needs_review") || other.optBoolean("needs_review")) keep.put("needs_review", true);
                if (keep == word) {
                    pending.set(match, null);
                    pending.add(word);
                } else {
                    pending.set(match, keep);
                }
                matched[match] = true;
            } else {
                pending.add(word);
            }
        }
        pending.removeIf(word -> word == null);
        flush(boundary - overlap - MATCH_SECONDS);
    }

    void finish() throws Exception { flush(Double.POSITIVE_INFINITY); }

    private void flush(double before) throws Exception {
        JSONArray ready = new JSONArray();
        int count = 0;
        for (JSONObject word : pending) {
            if (word.getDouble("end") >= before) break;
            if (!word.optBoolean("_legacy_core")) word.put("needs_review", true);
            word.remove("_legacy_core");
            ready.put(word);
            count++;
        }
        pending.subList(0, count).clear();
        phrases.accept(ready);
    }
}
