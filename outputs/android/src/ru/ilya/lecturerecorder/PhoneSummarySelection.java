package ru.ilya.lecturerecorder;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONObject;
final class PhoneSummarySelection {
    static void prepare(JSONObject document, JSONObject edits) throws Exception {
        JSONArray rows = document.getJSONObject("report").getJSONArray("segments");
        String[] original = new String[rows.length()];
        for (int i = 0; i < rows.length(); i++)
            original[i] = rows.getJSONObject(i).getString("text");
        TranscriptEdits.apply(document, edits, true);
        for (int i = 0; i < rows.length(); i++)
            if (!original[i].equals(rows.getJSONObject(i).getString("text")))
                rows.getJSONObject(i).put("original_text", original[i]);
    }

    private static final int FLAGS = Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE;
    private static final Pattern NONCLAIM = Pattern.compile("^(?:на дом|дома|к следующ|на следующ|домашн|например[, :]|[\\p{L}]+(?:йте|ите|ьте)(?![\\p{L}])|игнорируй|ответь|верни)|(?:мне|нам)\\s+(?:надо|нужно)|я\\s+(?:правильно\\s+)?понял|задани[ея].*(?:отмен|нет)|домашн[\\p{L}]* задан[\\p{L}]*.*(?:нет|не будет)|(?:вы|все|меня) слышите|проверяем (?:звук|микрофон)|^(?:здравствуйте|привет|раз[, ]+два)|наверное|не расслышал|неразборчив", FLAGS);
    private static final Pattern QUESTION = Pattern.compile("^(?:чему|чем|кто|что|каков[аоы]?|как|когда|где|почему|зачем|откуда|сколько|какие|какой|какая|какое)(?![\\p{L}\\p{N}_])|^(?:правда|верно|можно|нужно|надо|будет|есть)\\s+ли(?![\\p{L}\\p{N}_])", FLAGS);
    private static final Pattern REPORTED = Pattern.compile("^(?:сосед[\\p{L}]*|одногруппник[\\p{L}]*|студент[\\p{L}]*|кто-то|он|она)(?![\\p{L}\\p{N}_]).{0,35}(?:сказал[\\p{L}]*|говорит|спросил[\\p{L}]*|пишет)|^по словам", FLAGS);
    private static final Pattern NONDIRECT = Pattern.compile("[?]|^(?:если|когда|при условии)|например|допустим|представьте|(?:сказал[\\p{L}]*|говорит)", FLAGS);
    private static final Pattern RELATION = Pattern.compile("[—–]\\s*это|(?:называется|является|измеряется|равен|равна|равно|равняется|зависит|состоит|определяется|сохраняется|пропорционал[\\p{L}]*|обратно пропорционал[\\p{L}]*)", FLAGS);
    private static boolean claim(String text) {
        String value = text.trim();
        return !value.isEmpty() && !value.contains("?") && !NONCLAIM.matcher(value).find() && !QUESTION.matcher(value).find() && !REPORTED.matcher(value).find();
    }

    private static boolean directTask(String text) {
        return !NONDIRECT.matcher(text).find();
    }

    private static boolean strong(String text) {
        return claim(text) && RELATION.matcher(text).find();
    }

    static boolean hasContent(JSONArray rows) throws Exception {
        for (int i = 0; i < rows.length(); i++) {
            JSONObject row = rows.getJSONObject(i);
            String text = row.getString("text");
            if (!row.optBoolean("needs_review") && (claim(text) || directTask(text) && HomeworkEvidence.kind(text, row).equals("assignment")))
                return true;
        }
        return false;
    }

    static void add(String response, int first, int next, JSONArray rows, JSONArray summary, JSONArray sources, JSONArray homework, JSONArray review, Set<String> points, Set<String> tasks) throws Exception {
        JSONArray selected = new JSONArray(), anchors = new JSONArray(), work = new JSONArray(), pending = new JSONArray();
        PhoneSummaryEvidence.add(response, first, next, rows, selected, anchors, work, pending, new HashSet<>(), new HashSet<>());
        int kept = 0;
        for (int i = 0; i < selected.length(); i++) {
            String quote = selected.getString(i);
            if (claim(quote) && points.add(quote)) {
                summary.put(quote);
                sources.put(anchors.getJSONObject(i));
                kept++;
            }
        }
        int assigned = 0;
        for (int i = 0; i < work.length(); i++) {
            JSONObject item = work.getJSONObject(i);
            String quote = item.getString("quote");
            if (directTask(quote) && tasks.add(quote)) {
                homework.put(item);
                assigned++;
            }
        }
        for (int i = 0; i < pending.length(); i++)
            review.put(pending.getJSONObject(i));
        if (kept == 0) {
            for (int index = first; index < next && kept < 4; index++) {
                JSONArray values = new JSONArray(), citations = new JSONArray();
                PhoneSummaryEvidence.add("KEY: "+(index-first+1), first, next, rows, values, citations, new JSONArray(), new HashSet<>(), new HashSet<>());
                for (int i = 0; i < values.length() && kept < 4;i++) {
                    String quote = values.getString(i);
                    if (strong(quote) && points.add(quote)) {
                        summary.put(quote);
                        sources.put(citations.getJSONObject(i).put("selection_method", "verbatim_fallback"));
                        kept++;
                    }
                }
            }
        }
        if (assigned == 0) {
            for (int index = first; index < next; index++) {
                JSONObject row = rows.getJSONObject(index);
                if (!directTask(row.getString("text")) || !HomeworkEvidence.kind(row.getString("text"), row).equals("assignment"))
                    continue;
                JSONArray values = new JSONArray();
                PhoneSummaryEvidence.add("TASK: "+(index-first+1), first, next, rows, new JSONArray(), new JSONArray(), values, new HashSet<>(), new HashSet<>());
                for (int i = 0; i < values.length(); i++) {
                    JSONObject item = values.getJSONObject(i);
                    String quote = item.getString("quote");
                    if (directTask(quote) && tasks.add(quote))
                        homework.put(item.put("selection_method", "verbatim_fallback"));
                }
            }
        }
    }

    private PhoneSummarySelection() {
    }
}
