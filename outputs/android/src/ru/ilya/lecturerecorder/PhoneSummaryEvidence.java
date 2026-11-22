package ru.ilya.lecturerecorder;

import java.util.Set;
import java.util.TreeSet;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

final class PhoneSummaryEvidence {
    private static final Pattern INDEXES = Pattern.compile("(?im)^[ \\t]*(KEY|TASK)[ \\t]*:[ \\t]*([0-9, ]{0,40})[ \\t]*$");
    private static final Pattern AFTER_CLASS = Pattern.compile(
            "на дом(?![\\p{L}])|домашнее задание|к следующ(?:ей|ему|им) (?:паре|занятию|уроку|семинару)",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern ASSIGNMENT = Pattern.compile(
            "(?<![\\p{L}])(?:реши(?:те)?|прочитай(?:те)?|подготовь(?:те)?|сделай(?:те)?|выполни(?:те)?|сдай(?:те)?|напиши(?:те)?|выучи(?:те)?|решить|прочитать|подготовить|сделать|выполнить|сдать|написать|выучить)(?![\\p{L}])",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern EXCLUDED_TASK = Pattern.compile(
            "[?]|например|допустим|в качестве примера|если бы|не\\s+(?:нужно|надо|реш|дел|сда|готов|буд)|(?:задани[ея] нет|задани[ея] не будет)",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern CONDITION = Pattern.compile("^(?:если|когда|при условии,? что)\\s+.*[,;:]$",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);
    private static final Pattern CONSEQUENCE = Pattern.compile("^то\\s+(?!(?:есть|же|самое|что)(?:\\s|$))",
            Pattern.CASE_INSENSITIVE | Pattern.UNICODE_CASE);

    static void add(String response, int first, int next, JSONArray segments, JSONArray summary,
                    JSONArray sources, JSONArray homework, Set<String> points, Set<String> tasks)
            throws JSONException {
        Set<Integer> keys = new TreeSet<>();
        Set<Integer> exercises = new TreeSet<>();
        Matcher matcher = INDEXES.matcher(response);
        while (matcher.find()) {
            Set<Integer> selection = matcher.group(1).equalsIgnoreCase("KEY") ? keys : exercises;
            for (String number : matcher.group(2).trim().split("[, ]+")) {
                if (!number.matches("[0-9]{1,2}")) continue;
                int index = first + Integer.parseInt(number) - 1;
                if (index >= first && index < next && selection.size() < 4) selection.add(index);
            }
        }
        for (int index : keys) {
            JSONObject evidence = point(segments, index);
            if (evidence == null) continue;
            String quote = evidence.getString("quote");
            if (quote.length() < 16 || !points.add(quote)) continue;
            summary.put(quote);
            sources.put(evidence);
        }
        for (int index : exercises) {
            JSONObject row = segments.getJSONObject(index);
            String quote = row.getString("text");
            if (row.optBoolean("needs_review") || !AFTER_CLASS.matcher(quote).find()
                    || !ASSIGNMENT.matcher(quote).find() || EXCLUDED_TASK.matcher(quote).find()
                    || !tasks.add(quote)) continue;
            homework.put(anchor(row, index, quote).put("task", quote));
        }
    }

    private static JSONObject point(JSONArray segments, int index) throws JSONException {
        JSONObject row = segments.getJSONObject(index);
        if (row.optBoolean("needs_review")) return null;
        String quote = row.getString("text").trim();
        int previous = index - 1;
        if (CONSEQUENCE.matcher(quote).find()) {
            return previous >= 0 ? conditional(segments, previous, index) : null;
        }
        if (CONDITION.matcher(quote).matches()) {
            return index + 1 < segments.length() ? conditional(segments, index, index + 1) : null;
        }
        return anchor(row, index, quote);
    }

    private static JSONObject conditional(JSONArray segments, int first, int next) throws JSONException {
        JSONObject condition = segments.getJSONObject(first);
        JSONObject result = segments.getJSONObject(next);
        if (condition.optBoolean("needs_review") || result.optBoolean("needs_review")) return null;
        String left = condition.getString("text").trim();
        String right = result.getString("text").trim();
        double gap = result.getDouble("start") - condition.getDouble("end");
        if (!CONDITION.matcher(left).matches() || !CONSEQUENCE.matcher(right).find() || gap < -.25 || gap > 1.5) {
            return null;
        }
        return anchor(condition, first, left + " " + right).put("end", result.getDouble("end"));
    }

    private static JSONObject anchor(JSONObject row, int index, String quote) throws JSONException {
        return new JSONObject().put("quote", quote).put("segment_id", index)
                .put("start", row.getDouble("start")).put("end", row.getDouble("end"));
    }

    private PhoneSummaryEvidence() {}
}
