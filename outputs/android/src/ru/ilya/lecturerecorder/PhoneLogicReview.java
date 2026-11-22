package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class PhoneLogicReview {
    private static final Pattern TOKEN = Pattern.compile("[0-9]+(?:[.,][0-9]+)?|[\\p{L}\\p{M}]+");
    private static final List<String> CARDINALS = Arrays.asList("ноль", "один", "два", "три", "четыре", "пять", "шесть",
            "семь", "восемь", "девять", "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
            "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать", "двадцать");
    private static final List<String> OBLIQUE_CARDINALS = Arrays.asList("нуля", "одного", "двух", "трех",
            "четырех", "пяти", "шести", "семи", "восьми", "девяти", "десяти", "одиннадцати", "двенадцати",
            "тринадцати", "четырнадцати", "пятнадцати", "шестнадцати", "семнадцати", "восемнадцати",
            "девятнадцати", "двадцати");
    private static final List<String> NEGATIONS = Arrays.asList("не", "ни", "нет", "без");
    private static final int MAX_REVIEW = 12;

    static JSONArray evaluate(JSONArray segments) throws JSONException {
        JSONArray review = new JSONArray();
        if (segments == null) return review;
        Map<String, Wording> matches = new HashMap<>();
        for (int i = 0; i < segments.length() && review.length() < MAX_REVIEW; i++) {
            JSONObject row = segments.optJSONObject(i);
            if (row == null) continue;
            double time = row.optDouble("start", -1);
            if (!Double.isFinite(time) || time < 0) continue;
            Wording current = new Wording(i, time, row.optString("text"));
            if (current.words < 5) continue;
            Wording previous = matches.put(current.skeleton.toString(), current);
            if (previous == null || time < previous.time || time - previous.time > 180) continue;
            boolean differentNumbers = !previous.numbers.isEmpty() && !current.numbers.isEmpty()
                    && !previous.numbers.equals(current.numbers);
            boolean differentNegation = !previous.negations.equals(current.negations);
            if (differentNumbers || differentNegation) {
                review.put(new JSONObject().put("before", previous.index).put("after", current.index)
                        .put("numbers", differentNumbers).put("negation", differentNegation));
            }
        }
        return review;
    }

    private static final class Wording {
        final int index;
        final double time;
        final StringBuilder skeleton = new StringBuilder();
        final List<String> numbers = new ArrayList<>();
        final List<String> negations = new ArrayList<>();
        int words;

        Wording(int index, double time, String text) {
            this.index = index;
            this.time = time;
            Matcher matcher = TOKEN.matcher(text.toLowerCase(Locale.ROOT).replace('ё', 'е'));
            while (matcher.find()) {
                String word = matcher.group();
                int cardinal = CARDINALS.indexOf(word);
                if (cardinal < 0) cardinal = OBLIQUE_CARDINALS.indexOf(word);
                if (cardinal >= 0 || Character.isDigit(word.charAt(0))) {
                    numbers.add(words + ":" + (cardinal >= 0 ? Integer.toString(cardinal) : word.replace(',', '.')));
                    skeleton.append("# ");
                } else if (NEGATIONS.contains(word)) {
                    negations.add(words + ":" + word);
                } else {
                    skeleton.append(word).append(' ');
                    words++;
                }
            }
        }
    }

    private PhoneLogicReview() {}
}
