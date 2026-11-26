package ru.ilya.lecturerecorder;

import org.json.JSONArray;
import org.json.JSONObject;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

final class RecordingGap {
    final int start;
    final int end;
    final boolean afterFile;

    private RecordingGap(int start, int end, boolean afterFile) {
        this.start = start;
        this.end = end;
        this.afterFile = afterFile;
    }

    static List<RecordingGap> read(JSONArray entries, int duration) {
        List<RecordingGap> result = new ArrayList<>();
        if (entries == null || duration <= 0) return result;
        for (int i = 0; i < entries.length(); i++) {
            JSONObject entry = entries.optJSONObject(i);
            if (entry == null) continue;
            double from = entry.optDouble("start");
            double to = entry.optDouble("end", from + entry.optDouble("seconds"));
            if (!Double.isFinite(from) || !Double.isFinite(to) || from < 0
                    || to <= from || to * 1000 > Integer.MAX_VALUE) continue;
            boolean tail = entry.optBoolean("unrecorded_tail");
            int start = (int) Math.floor(from * 1000);
            int end = (int) Math.ceil(to * 1000);
            if (tail) {
                if (Math.abs((long) start - duration) > 2) continue;
                result.add(new RecordingGap(duration, Math.max(duration, end), true));
            } else if (start < duration) {
                result.add(new RecordingGap(start, Math.min(end, duration), false));
            }
        }
        result.sort(Comparator.comparingInt(gap -> gap.start));
        return result;
    }

    int listenFrom() {
        return Math.max(0, start - 2000);
    }

    private static String timestamp(int millis) {
        String base = LectureReaderActivity.clock(millis / 1000.0);
        int fraction = millis % 1000;
        if (fraction == 0) return base;
        return base + String.format(Locale.ROOT, ",%03d", fraction).replaceFirst("0+$", "");
    }

    @Override public String toString() {
        if (afterFile) {
            String seconds = BigDecimal.valueOf(Math.max(1, end - start), 3)
                    .stripTrailingZeros().toPlainString().replace('.', ',');
            return "После окончания файла · " + seconds + " с";
        }
        return timestamp(start) + " — " + timestamp(end);
    }
}
