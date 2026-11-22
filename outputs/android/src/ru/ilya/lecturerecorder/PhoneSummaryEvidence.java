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
            JSONObject row = segments.getJSONObject(index);
            String quote = row.getString("text");
            if (row.optBoolean("needs_review") || quote.trim().length() < 16 || !points.add(quote)) continue;
            summary.put(quote);
            sources.put(anchor(row, index, quote));
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

    private static JSONObject anchor(JSONObject row, int index, String quote) throws JSONException {
        return new JSONObject().put("quote", quote).put("segment_id", index)
                .put("start", row.getDouble("start")).put("end", row.getDouble("end"));
    }

    private PhoneSummaryEvidence() {}
}
