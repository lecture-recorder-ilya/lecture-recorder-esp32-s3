package ru.ilya.lecturerecorder;
import java.util.regex.Pattern;
import org.json.JSONObject;

final class HomeworkEvidence {
    private static boolean has(String pattern,String text) {
        return Pattern.compile(pattern,Pattern.CASE_INSENSITIVE|Pattern.UNICODE_CASE).matcher(text).find();
    }
    static String kind(String text,JSONObject row) {
        text=text.trim();
        if(text.contains("?"))return "question";
        if(has("например|допустим|в качестве примера|для примера|представьте|если бы|пример\\s+(?:домашн|задани)",text))return "example";
        if(has("я\\s+(?:(?:правильно|верно)\\s+)?понял|правильно\\s+(?:я\\s+)?понимаю|вы\\s+(?:сказали|задали)|то есть\\s+(?:нам|на дом)",text))return "clarification";
        String role=row.optString("speaker_role");
        if(role.equals("student")||role.equals("audience")||has("(?:мне|нам)\\s+(?:надо|нужно)|я\\s+(?:должен|должна)|в аудитории|(?<![\\p{L}\\p{N}_])(?:сосед|одногруппник|студент|кто-то|он|она)(?![\\p{L}\\p{N}_]).{0,35}(?:сказал[\\p{L}]*|говорит|надо)",text))return "audience";
        if(!has("домашн[\\p{L}]*\\s+(?:задани|работ)|на дом(?![\\p{L}])|(?:на|к) следующ|после (?:пары|занятия|урока)",text))return "classwork";
        if(!has("(?<![\\p{L}])(?:подготовьте|прочитайте|решите|выучите|изучите|сдайте|напишите|повторите|сделайте|выполните)(?![\\p{L}])|(?:нужно|надо|следует)\\s+(?:будет\\s+)?(?:решить|прочитать|подготовить|написать|сдать|выучить|сделать|выполнить)(?![\\p{L}])",text)
                &&!has("(?:^|[.!]\\s+)(?:ваше\\s+)?домашн[\\p{L}]*\\s+(?:задани[\\p{L}]*|работ[\\p{L}]*)\\s*[:—-]\\s*(?:задач|пример|глав|параграф|упражнен)",text))return "unsupported";
        return "assignment";
    }
    static String note(String kind) {
        if(kind.equals("question"))return "Это вопрос, выдача ДЗ не подтверждена.";
        if(kind.equals("example"))return "Это учебный пример, выдача ДЗ не подтверждена.";
        if(kind.equals("clarification"))return "Это переспрос, выдачу ДЗ нужно сверить.";
        if(kind.equals("classwork"))return "Самостоятельная работа после занятия не подтверждена.";
        if(kind.equals("unsupported"))return "Формулировку ДЗ нужно сверить.";
        return "Это личная или чужая реплика, выдачу ДЗ нужно сверить.";
    }
}
