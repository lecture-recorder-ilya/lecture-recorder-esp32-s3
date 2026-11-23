package ru.ilya.lecturerecorder;

import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;
import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.Arrays;
import java.util.regex.Pattern;

final class PhraseReplayAudio {
    private static final int RATE = PcmWave.SAMPLE_RATE;
    private static final long CONTEXT = RATE * 3 / 2;
    private static final long MAX_TARGET = RATE * 15;
    private static final Pattern WORD = Pattern.compile("[\\p{L}\\p{N}]");

    static final class Window {
        final long left, start, end, right;
        Window(long left, long start, long end, long right) {
            this.left = left;
            this.start = start;
            this.end = end;
            this.right = right;
        }

        boolean containsMidpoint(double from, double to) {
            if (!Double.isFinite(from) || !Double.isFinite(to) || from >= to) return false;
            double midpoint = (from + to) * .5 * RATE;
            return midpoint >= start && midpoint < end;
        }
    }

    static Window window(long samples, double from, double to, double anchor) throws IOException {
        if (samples <= 0 || !Double.isFinite(from) || !Double.isFinite(to) || from < 0 || to <= from)
            throw new IOException("У фрагмента нет подходящего таймкода");
        long start = (long)Math.floor(from * RATE), end = Math.min(samples, (long)Math.ceil(to * RATE));
        if (start >= end) throw new IOException("Фрагмент за пределами аудиозаписи");
        if (end - start > MAX_TARGET) {
            if (Double.isFinite(anchor) && anchor >= from && anchor < end / (double)RATE)
                start = Math.max(start, Math.min(end - MAX_TARGET, Math.round(anchor * RATE) - MAX_TARGET / 2));
            end = start + MAX_TARGET;
        }
        return new Window(Math.max(0, start - CONTEXT), start, end, end + Math.min(samples - end, CONTEXT));
    }

    static String decode(Context context, RandomAccessFile audio, long data, Window section, File model,
                         OrtSession.RunOptions run, PhoneAnalysisService.Job job) throws Exception {
        float[] wave = PhoneGigaAm.readWindow(audio, data + section.left * 2, (int)(section.right - section.left));
        int offset = (int)(section.start - section.left), last = (int)(section.end - section.left);
        if (wave.length < 400 || PhoneSpeechWindow.constant(Arrays.copyOfRange(wave, offset, last), last - offset)) return "";
        PhoneSpeechWindow.normalize(wave, PhoneSpeechWindow.level(wave), 8);
        job.check();
        OrtEnvironment environment = OrtEnvironment.getEnvironment();
        String[] tokens = PhoneGigaAm.readTokens(context);
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(2);
            options.setInterOpNumThreads(1);
            options.addConfigEntry("session.intra_op.allow_spinning", "0");
            try (OrtSession frontend = environment.createSession(PhoneGigaAm.readFrontend(context), options);
                 OrtSession acoustic = environment.createSession(model.getPath(), options)) {
                job.check();
                JSONArray words = PhoneGigaAm.recognize(environment, frontend, acoustic, wave, tokens,
                        section.left / (double)RATE, section.start / (double)RATE, section.end / (double)RATE, true, run);
                job.check();
                return text(section, words);
            }
        }
    }

    static String text(Window window, JSONArray words) throws Exception {
        StringBuilder result = new StringBuilder();
        for (int index = 0; index < words.length(); index++) {
            JSONObject word = words.getJSONObject(index);
            String value = word.getString("word");
            if (word.optBoolean("verify_onset") || !window.containsMidpoint(word.getDouble("start"), word.getDouble("end"))
                    || !WORD.matcher(value).find()) continue;
            if (result.length() > 0) result.append(' ');
            result.append(value);
        }
        return result.toString();
    }

    private PhraseReplayAudio() {}
}
