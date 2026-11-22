package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.*;
import javax.net.ssl.HttpsURLConnection;

final class MireaSchedule {
    static final ZoneId MOSCOW = ZoneId.of("Europe/Moscow");
    static final String SITE = "https://schedule-of.mirea.ru";
    private static final DateTimeFormatter ICS_TIME = DateTimeFormatter.ofPattern("uuuuMMdd'T'HHmmss", Locale.ROOT);
    private static final DateTimeFormatter LABEL = DateTimeFormatter.ofPattern("HH:mm", Locale.ROOT);
    private static final long CACHE_AGE = 6 * 60 * 60 * 1000L;
    private static final int LIMIT = 1024 * 1024;

    static SharedPreferences profile(Context context) {
        return context.getSharedPreferences("mirea_profile", Context.MODE_PRIVATE);
    }

    static String group(String value) {
        return value.trim().toUpperCase(Locale.ROOT).replace('‐', '-').replace('‑', '-').replace('–', '-').replace('—', '-').replace('−', '-');
    }

    static boolean validGroup(String value) {
        return value.matches("[А-ЯЁA-Z0-9]{1,12}(?:-[А-ЯЁA-Z0-9]{1,8}){2,4}");
    }

    static final class Lesson {
        final ZonedDateTime start;
        final ZonedDateTime end;
        final String subject;
        final String type;
        final String room;

        Lesson(ZonedDateTime start, ZonedDateTime end, String subject, String type, String room) {
            this.start = start;
            this.end = end;
            this.subject = subject;
            this.type = type;
            this.room = room;
        }

        String time() { return start.format(LABEL) + "–" + end.format(LABEL); }
        String detail() { return time() + (type.isEmpty() ? "" : " · " + type) + (room.isEmpty() ? "" : " · " + room); }

        JSONObject metadata(String group) throws Exception {
            return new JSONObject().put("subject", subject).put("type", type)
                    .put("start", start.format(LABEL)).put("end", end.format(LABEL))
                    .put("date", start.toLocalDate().toString()).put("room", room)
                    .put("group", group).put("source", "mirea");
        }
    }

    private static String fetch(String path) throws IOException {
        HttpsURLConnection request = (HttpsURLConnection) new URL(SITE + path).openConnection();
        request.setInstanceFollowRedirects(false);
        request.setConnectTimeout(4500);
        request.setReadTimeout(5000);
        try {
            if (request.getResponseCode() != 200) throw new IOException("Расписание МИРЭА временно недоступно");
            try (InputStream in = request.getInputStream(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[8192];
                for (int count; (count = in.read(buffer)) != -1; ) {
                    if (out.size() + count > LIMIT) throw new IOException("Расписание слишком большое");
                    out.write(buffer, 0, count);
                }
                return new String(out.toByteArray(), StandardCharsets.UTF_8);
            }
        } finally {
            request.disconnect();
        }
    }

    static String load(Context context, String group) throws Exception {
        if (!validGroup(group)) throw new IOException("Проверь код группы");
        File cache = new File(context.getFilesDir(), "mirea-schedule.json");
        JSONObject saved = null;
        try {
            JSONObject value = new JSONObject(Store.read(cache));
            if (group.equals(value.optString("group")) && value.optString("ics").startsWith("BEGIN:VCALENDAR")) saved = value;
        } catch (Exception ignored) {}
        if (saved != null && System.currentTimeMillis() - saved.optLong("updated") < CACHE_AGE) return saved.getString("ics");

        try {
            String query = URLEncoder.encode(group, "UTF-8");
            JSONArray results = new JSONObject(fetch("/schedule/api/search?limit=15&match=" + query)).getJSONArray("data");
            long id = 0;
            for (int i = 0; i < results.length(); i++) {
                JSONObject result = results.getJSONObject(i);
                if (result.optInt("scheduleTarget") == 1 && group.equals(group(result.optString("targetTitle")))) {
                    id = result.optLong("id");
                    break;
                }
            }
            if (id <= 0) throw new IOException("Группа не найдена в расписании МИРЭА");
            String calendar = fetch("/schedule/api/ical/1/" + id);
            if (!calendar.startsWith("BEGIN:VCALENDAR") || !calendar.trim().endsWith("END:VCALENDAR")) {
                throw new IOException("Не удалось прочитать расписание МИРЭА");
            }
            try {
                Store.write(cache, new JSONObject().put("group", group).put("ics", calendar)
                        .put("updated", System.currentTimeMillis()));
            } catch (IOException ignored) {}
            return calendar;
        } catch (Exception error) {
            if (saved != null) return saved.getString("ics");
            throw error;
        }
    }

    static List<Lesson> lessons(String calendar, LocalDate day) {
        List<Lesson> list = new ArrayList<>();
        Map<String, List<String>> event = null;
        for (String line : calendar.replaceAll("\\r?\\n[ \\t]", "").split("\\r?\\n")) {
            if (line.equals("BEGIN:VEVENT")) {
                event = new HashMap<>();
            } else if (line.equals("END:VEVENT") && event != null) {
                try {
                    Lesson lesson = parse(event, day);
                    if (lesson != null) list.add(lesson);
                } catch (DateTimeException | NumberFormatException ignored) {}
                event = null;
            } else if (event != null) {
                int split = line.indexOf(':');
                if (split > 0) {
                    String key = line.substring(0, split).split(";", 2)[0];
                    event.computeIfAbsent(key, ignored -> new ArrayList<>()).add(line.substring(split + 1));
                }
            }
        }
        list.sort(Comparator.comparing((Lesson lesson) -> lesson.start)
                .thenComparing(lesson -> lesson.subject).thenComparing(lesson -> lesson.type)
                .thenComparing(lesson -> lesson.room));
        return list;
    }

    private static Lesson parse(Map<String, List<String>> event, LocalDate day) {
        String from = first(event, "DTSTART");
        String to = first(event, "DTEND");
        if (!from.contains("T") || !to.contains("T") || "CANCELLED".equals(first(event, "STATUS"))) return null;
        ZonedDateTime base = moment(from);
        Duration duration = Duration.between(base, moment(to));
        if (duration.isZero() || duration.isNegative() || duration.toHours() >= 24 || day.isBefore(base.toLocalDate())) return null;
        ZonedDateTime start = ZonedDateTime.of(day, base.toLocalTime(), MOSCOW);
        boolean occurs = day.equals(base.toLocalDate());
        String recurrence = first(event, "RRULE");
        if (!recurrence.isEmpty()) occurs = repeats(recurrence, day, base, start);
        if (!occurs) {
            for (String line : event.getOrDefault("RDATE", Collections.emptyList())) {
                if (includes(line, start)) occurs = true;
            }
        }
        if (!occurs) return null;
        for (String line : event.getOrDefault("EXDATE", Collections.emptyList())) {
            if (includes(line, start)) return null;
        }
        String type = unescape(first(event, "CATEGORIES"));
        String subject = unescape(first(event, "SUMMARY"));
        if (!type.isEmpty() && subject.startsWith(type + " ")) subject = subject.substring(type.length() + 1);
        if (subject.trim().isEmpty()) return null;
        return new Lesson(start, start.plus(duration), subject, type, unescape(first(event, "LOCATION")));
    }

    private static boolean repeats(String recurrence, LocalDate day, ZonedDateTime base, ZonedDateTime start) {
        Map<String, String> rule = new HashMap<>();
        for (String field : recurrence.split(";")) {
            String[] part = field.split("=", 2);
            if (part.length == 2) rule.put(part[0], part[1]);
        }
        long delta = ChronoUnit.DAYS.between(base.toLocalDate(), day);
        int interval = Integer.parseInt(rule.getOrDefault("INTERVAL", "1"));
        String frequency = rule.get("FREQ");
        if (interval <= 0 || (!"DAILY".equals(frequency) && !"WEEKLY".equals(frequency))) return delta == 0;
        for (String key : rule.keySet()) {
            if (!key.equals("FREQ") && !key.equals("INTERVAL") && !key.equals("UNTIL") && !key.equals("COUNT")) {
                return delta == 0;
            }
        }
        long step = ("WEEKLY".equals(frequency) ? 7L : 1L) * interval;
        return delta % step == 0
                && (!rule.containsKey("UNTIL") || beforeRecurrenceEnd(start, rule.get("UNTIL")))
                && (!rule.containsKey("COUNT") || delta / step < Integer.parseInt(rule.get("COUNT")));
    }

    private static boolean beforeRecurrenceEnd(ZonedDateTime start, String limit) {
        if (limit.length() == 8) return !start.toLocalDate().isAfter(LocalDate.parse(limit, DateTimeFormatter.BASIC_ISO_DATE));
        return !start.isAfter(moment(limit));
    }

    private static boolean includes(String line, ZonedDateTime start) {
        for (String value : line.split(",")) {
            if (value.length() == 8 ? value.equals(start.format(DateTimeFormatter.BASIC_ISO_DATE)) : moment(value).isEqual(start)) return true;
        }
        return false;
    }

    private static ZonedDateTime moment(String value) {
        if (value.endsWith("Z")) {
            return LocalDateTime.parse(value.substring(0, value.length() - 1), ICS_TIME)
                    .atZone(ZoneOffset.UTC).withZoneSameInstant(MOSCOW);
        }
        return LocalDateTime.parse(value, ICS_TIME).atZone(MOSCOW);
    }

    private static String first(Map<String, List<String>> event, String key) {
        return event.containsKey(key) ? event.get(key).get(0) : "";
    }

    private static String unescape(String value) {
        return value.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",")
                .replace("\\;", ";").replace("\\\\", "\\").trim();
    }

    static int suggestion(List<Lesson> lessons, ZonedDateTime recordedAt, long seconds) {
        int found = -1;
        for (int i = 0; i < lessons.size(); i++) {
            Lesson lesson = lessons.get(i);
            boolean inside = !recordedAt.isBefore(lesson.start) && recordedAt.isBefore(lesson.end);
            boolean justBefore = recordedAt.isBefore(lesson.start)
                    && Duration.between(recordedAt, lesson.start).toMinutes() < 10
                    && recordedAt.plusSeconds(seconds).isAfter(lesson.start.plusMinutes(1));
            if (inside || justBefore) {
                if (found >= 0) return -1;
                found = i;
            }
        }
        return found;
    }

    private MireaSchedule() {}
}
