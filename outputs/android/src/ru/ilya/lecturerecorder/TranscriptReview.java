package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class TranscriptReview {
    static final String[] KINDS = {"all", "number", "unit", "negation"};
    static final String[] LABELS = {"Сомнения", "Числа", "Единицы", "Отрицания"};
    private static final Pattern WORD = Pattern.compile("[+−-]?\\p{N}+(?:[.,:/]\\p{N}+)*(?:[%°]|\\p{L}+)?|[\\p{L}\\p{M}]+(?:['’‑-][\\p{L}\\p{M}]+)*|[%°₽]");
    private static final Set<String> NUMBERS = new HashSet<>(Arrays.asList((
            "ноль нуль ноля нуля нулю нулем нуле один одна одно одну одни одного одной одному одним одних одними "
            + "два две двух двум двумя три трех трем тремя четыре четырех четырем четырьмя пять пяти пятью "
            + "шесть шести шестью семь семи семью восемь восьми восемью девять девяти девятью десять десяти десятью "
            + "одиннадцать одиннадцати двенадцать двенадцати тринадцать тринадцати четырнадцать четырнадцати "
            + "пятнадцать пятнадцати шестнадцать шестнадцати семнадцать семнадцати восемнадцать восемнадцати "
            + "девятнадцать девятнадцати двадцать двадцати тридцать тридцати сорок сорока пятьдесят пятидесяти "
            + "шестьдесят шестидесяти семьдесят семидесяти восемьдесят восьмидесяти девяносто девяноста "
            + "сто ста двести двухсот триста трехсот четыреста четырехсот пятьсот пятисот шестьсот шестисот "
            + "семьсот семисот восемьсот восьмисот девятьсот девятисот тысяча тысячи тысяч тысячу тысячей "
            + "миллион миллиона миллионов миллиард миллиарда миллиардов").split(" ")));
    private static final Pattern UNITS = Pattern.compile(
            "(?:кило|санти|милли|деци)?метр(?:а|ы|ов|е|у|ом|ам|ами|ах)?|(?:кило|милли)?грамм(?:а|ы|ов|е|у|ом|ам|ами|ах)?"
            + "|(?:милли)?литр(?:а|ы|ов|е|у|ом|ам|ами|ах)?|секунд(?:а|ы|у|ой|е|ам|ами|ах)?|минут(?:а|ы|у|ой|е|ам|ами|ах)?"
            + "|час(?:а|ы|ов|е|у|ом|ам|ами|ах)?|рубл(?:ь|я|ей|ю|ем|е|ям|ями|ях)|копе(?:йка|йки|ек|йку|йке|йкой|йкам|йками|йках)"
            + "|доллар(?:а|ы|ов|е|у|ом|ам|ами|ах)?|евро|процент(?:а|ы|ов|е|у|ом|ам|ами|ах)?|градус(?:а|ы|ов|е|у|ом|ам|ами|ах)?"
            + "|(?:кило|милли)?(?:ампер|вольт|ватт|герц|ом)(?:а|ы|ов|е|у|ом|ам|ами|ах)?|(?:кило|мега|гига|тера)?байт(?:а|ы|ов|е|у|ом|ам|ами|ах)?"
            + "|кг|мг|км|см|мм|мл|сек|мин|руб|коп|квт|гц|мгц|%|°|₽");

    static String kind(String word) {
        String normalized = word.toLowerCase(Locale.ROOT).replace('ё', 'е');
        if (normalized.matches("не|ни|нет|без")) return "negation";
        if (NUMBERS.contains(normalized) || normalized.matches(".*\\p{N}.*")) return "number";
        if (UNITS.matcher(normalized).matches()) return "unit";
        return "word";
    }

    static List<Item> words(JSONObject row) {
        return words(row, false);
    }

    static List<Item> words(JSONObject row, boolean searchAllPhrases) {
        List<Item> result = new ArrayList<>();
        if (!searchAllPhrases && !row.optBoolean("needs_review")) return result;
        String text = row.optString("text");
        JSONArray reviews = row.optJSONArray("word_reviews");
        JSONArray times = row.optJSONArray("word_times");
        Matcher matcher = WORD.matcher(text);
        String previous = "";
        while (matcher.find()) {
            String token = matcher.group();
            String kind = kind(token);
            if (kind.equals("word") && token.toLowerCase(Locale.ROOT).matches("м|г|с|л|ч") && previous.equals("number")) kind = "unit";
            previous = kind;
            boolean direct = false;
            for (int i = 0; reviews != null && i < reviews.length(); i++) {
                JSONArray span = reviews.optJSONArray(i);
                if (span != null && span.optInt(0, -1) >= 0 && span.optInt(0, -1) <= matcher.start()
                        && span.optInt(1, -1) >= matcher.end() && span.optInt(1, -1) <= text.length()) direct = true;
            }
            if (!direct && kind.equals("word")) continue;
            long millis = -1;
            boolean timedWord = false;
            double start = row.optDouble("start", Double.NaN), end = row.optDouble("end", Double.NaN);
            if (Double.isFinite(start) && Double.isFinite(end) && start >= 0 && end >= start
                    && end * 1000 <= Integer.MAX_VALUE) {
                for (int i = 0; times != null && i < times.length(); i++) {
                    JSONArray time = times.optJSONArray(i);
                    if (time == null) continue;
                    long value = time.optLong(2, -1);
                    if (time.optInt(0, -1) >= 0 && time.optInt(0, -1) <= matcher.start()
                            && time.optInt(1, -1) >= matcher.end() && time.optInt(1, -1) <= text.length()
                            && value >= start * 1000 - 1 && value <= end * 1000 + 1 && value >= 0) {
                        millis = value;
                        timedWord = true;
                        break;
                    }
                }
                if (millis < 0) millis = Math.round(start * 1000);
            }
            result.add(new Item(token, kind, matcher.start(), matcher.end(), (int) millis, direct, timedWord));
        }
        return result;
    }

    static String label(String kind) {
        switch (kind) {
            case "number": return "Число";
            case "unit": return "Единица";
            case "negation": return "Отрицание";
            default: return "Слово";
        }
    }

    static final class Item {
        final String text, kind;
        final int first, last, millis;
        final boolean direct, timedWord;

        Item(String text, String kind, int first, int last, int millis, boolean direct, boolean timedWord) {
            this.text = text;
            this.kind = kind;
            this.first = first;
            this.last = last;
            this.millis = millis;
            this.direct = direct;
            this.timedWord = timedWord;
        }
    }

    private TranscriptReview() {}
}
