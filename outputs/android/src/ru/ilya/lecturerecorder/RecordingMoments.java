package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

final class RecordingMoments {
    static final int MERGE_MILLIS = 700;

    private static SharedPreferences preferences(Context context) {
        return context.getSharedPreferences("conversation_map", Context.MODE_PRIVATE);
    }

    static List<Integer> times(Context context, String file) {
        if (file == null || file.isEmpty()) return Collections.emptyList();
        List<Integer> result = new ArrayList<>();
        for (String raw : preferences(context).getStringSet(file, Collections.emptySet())) {
            try {
                int time = Integer.parseInt(raw);
                if (time >= 0) result.add(time);
            } catch (NumberFormatException ignored) {}
        }
        Collections.sort(result);
        return result;
    }

    static int add(Context context, String file, int millis) {
        if (millis < 0 || file == null || file.isEmpty()) return -1;
        for (int prior : times(context, file)) {
            if (Math.abs((long) millis - prior) <= MERGE_MILLIS) return prior;
        }
        SharedPreferences prefs = preferences(context);
        Set<String> marks = new HashSet<>(prefs.getStringSet(file, Collections.emptySet()));
        marks.add(Integer.toString(millis));
        return prefs.edit().putStringSet(file, marks).commit() ? millis : -1;
    }

    static boolean remove(Context context, String file, int millis) {
        SharedPreferences prefs = preferences(context);
        Set<String> marks = new HashSet<>(prefs.getStringSet(file, Collections.emptySet()));
        marks.remove(Integer.toString(millis));
        return prefs.edit().putStringSet(file, marks).commit();
    }

    static void clear(Context context, String file) {
        preferences(context).edit().remove(file).apply();
    }
}
