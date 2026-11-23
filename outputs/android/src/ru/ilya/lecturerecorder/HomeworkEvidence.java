package ru.ilya.lecturerecorder;
import java.util.regex.Pattern;
import org.json.JSONObject;
final class HomeworkEvidence {
    private static final int FLAGS = Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE;
    private static final Pattern EXAMPLE = Pattern.compile("например|допустим|в качестве примера|для примера|представьте|если бы|пример\\s+(?:домашн|задани)", FLAGS);
    private static final Pattern CLARIFY = Pattern.compile("я\\s+(?:(?:правильно|верно)\\s+)?понял|правильно\\s+(?:я\\s+)?понимаю|вы\\s+(?:сказали|задали)|то есть\\s+(?:нам|на дом)", FLAGS);
    private static final Pattern PERSONAL = Pattern.compile("(?:мне|нам)\\s+(?:надо|нужно)|я\\s+(?:должен|должна)|в аудитории|(?<![\\p{L}\\p{N}_])(?:сосед|одногруппник|студент|кто-то|он|она)(?![\\p{L}\\p{N}_]).{0,35}(?:сказал[\\p{L}]*|говорит|надо)", FLAGS);
    private static final Pattern AFTER = Pattern.compile("домашн[\\p{L}]*\\s+(?:задани|работ)|(?<![\\p{L}])дома(?![\\p{L}])|на дом(?![\\p{L}])|(?:на|к) следующ|после (?:пары|занятия|урока)", FLAGS);
    private static final Pattern ACTION = Pattern.compile("(?<![\\p{L}])(?:подготовьте|прочитайте|решите|выучите|изучите|сдайте|напишите|повторите|сделайте|выполните)(?![\\p{L}])|(?:нужно|надо|следует)\\s+(?:будет\\s+)?(?:решить|прочитать|подготовить|написать|сдать|выучить|сделать|выполнить)(?![\\p{L}])", FLAGS);
    private static final Pattern LABEL = Pattern.compile("(?:^|[.!]\\s+)(?:ваше\\s+)?домашн[\\p{L}]*\\s+(?:задани[\\p{L}]*|работ[\\p{L}]*)\\s*[:—-]\\s*(?:задач|пример|глав|параграф|упражнен)", FLAGS);
    static String kind(String text, JSONObject row) {
        text = text.trim();
        if (text.contains("?"))return "question";
        if (EXAMPLE.matcher(text).find())return "example";
        if (CLARIFY.matcher(text).find())return "clarification";
        String role = row.optString("speaker_role");
        if (role.equals("student") || role.equals("audience") || PERSONAL.matcher(text).find())return "audience";
        if (!AFTER.matcher(text).find())return "classwork";
        if (!ACTION.matcher(text).find() && !LABEL.matcher(text).find())return "unsupported";
        return "assignment";
    }

    static String note(String kind) {
        if (kind.equals("question"))return "Это вопрос, выдача ДЗ не подтверждена.";
        if (kind.equals("example"))return "Это учебный пример, выдача ДЗ не подтверждена.";
        if (kind.equals("clarification"))return "Это переспрос, выдачу ДЗ нужно сверить.";
        if (kind.equals("classwork"))return "Самостоятельная работа после занятия не подтверждена.";
        if (kind.equals("unsupported"))return "Формулировку ДЗ нужно сверить.";
        return "Это личная или чужая реплика, выдачу ДЗ нужно сверить.";
    }
}
