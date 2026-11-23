package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.SharedPreferences;
import java.util.Locale;

final class ListeningLibrary {
    static final float[] SPEEDS = {.75f, 1f, 1.25f, 1.5f, 2f};
    static final String[] SPEED_LABELS = {"0,75×", "1×", "1,25×", "1,5×", "2×"};
    static final int NORMAL = 1;
    private final SharedPreferences positions, settings;

    ListeningLibrary(Context context) {
        positions = context.getSharedPreferences("playback_positions", Context.MODE_PRIVATE);
        settings = context.getSharedPreferences("listening_library", Context.MODE_PRIVATE);
    }

    int position(String file, int duration) {
        int old = positions.getInt(file, 0);
        int valid = resumable(old, duration);
        if (old != valid) positions.edit().remove(file).apply();
        return valid;
    }

    void savePosition(String file, int value, int duration) {
        int valid = resumable(value, duration);
        if (valid != positions.getInt(file, 0)) {
            if (valid == 0) positions.edit().remove(file).apply();
            else positions.edit().putInt(file, valid).apply();
        }
    }

    static int resumable(int position, int duration) {
        return position > 0 && (duration <= 0 || position < duration) ? position : 0;
    }

    boolean favorite(String file) { return settings.getBoolean("star:" + file, false); }

    void favorite(String file, boolean value) {
        if (value) settings.edit().putBoolean("star:" + file, true).apply();
        else settings.edit().remove("star:" + file).apply();
    }

    int speed() {
        int index = settings.getInt("playback_speed", NORMAL);
        return index >= 0 && index < SPEEDS.length ? index : NORMAL;
    }

    void speed(int index) {
        if (index >= 0 && index < SPEEDS.length) settings.edit().putInt("playback_speed", index).apply();
    }

    static String normalize(String value) { return value.toLowerCase(Locale.ROOT).replace('ё','е'); }

    static String[] terms(String query) {
        String value = normalize(query.trim());
        return value.isEmpty() ? new String[0] : value.split("\\s+");
    }

    static boolean matches(String indexed, String[] terms) {
        for (String term : terms) if (!indexed.contains(term)) return false;
        return true;
    }
}
