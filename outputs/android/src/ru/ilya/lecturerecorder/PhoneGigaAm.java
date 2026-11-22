package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtException;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

final class PhoneGigaAm {
    private static final int RATE = PcmWave.SAMPLE_RATE;
    private static final int CORE = 18 * RATE;
    private static final int EDGE = 2 * RATE;
    private static final int BLANK = 256;
    private static final double FRAME_SECONDS = 0.04;

    private static final Pattern CRITICAL = Pattern.compile(".*[0-9+−=<>×÷/].*|не|ни|нет|без|нол.*|нул.*|один.*|одн.*|дв[аеу].*|три.*|тр[ёе]х.*|четыр.*|пят.*|шест.*|сем.*|вос[ье]м.*|девят.*|десят.*|сорок.*|сто|сот.*|тысяч.*|милли.*|минус|плюс|равно|меньше|больше");

    static JSONArray transcribe(Context context, PhoneAnalysisService.Job job, String name, File model)
            throws Exception {
        try (RandomAccessFile input = Store.openAudio(context, name)) {
            return transcribe(context, job, name, model, input);
        }
    }

    static JSONArray transcribe(Context context, PhoneAnalysisService.Job job, String name, File model,
                                RandomAccessFile input) throws Exception {
        long total = PcmWave.seekData(input) / 2;
        long data = input.getFilePointer();
        int workers = total >= 90L * RATE && Runtime.getRuntime().availableProcessors() >= 6 ? 2 : 1;
        try {
            return transcribe(context, job, model, input, total, data, workers);
        } catch (OrtException error) {
            job.check();
            if (workers == 1) throw error;
            job.preview.startSpeech();
            return transcribe(context, job, model, input, total, data, 1);
        }
    }

    static JSONArray transcribe(Context context, PhoneAnalysisService.Job job, File model,
                                RandomAccessFile input, long total, long data, int workers) throws Exception {
        PhonePhrases phrases = new PhonePhrases(job.preview::addPhrase);
        String[] tokens = readTokens(context);
        OrtEnvironment environment = OrtEnvironment.getEnvironment();
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(4);
            options.setInterOpNumThreads(1);
            options.addConfigEntry("session.intra_op.allow_spinning", "0");
            try (OrtSession frontend = environment.createSession(readFrontend(context), options);
                 OrtSession acoustic = environment.createSession(model.getPath(), options)) {
                if (workers == 1) {
                    int completed = -1;
                    for (long start = 0; start < total; ) {
                        job.check();
                        Window window = window(input, data, total, start);
                        int percent = (int)(100 * start / total);
                        if (percent != completed) {
                            completed = percent;
                            job.update("Распознаю речь · " + percent + "%");
                        }
                        phrases.accept(decode(job, environment, frontend, acoustic, tokens, window));
                        start = window.end;
                    }
                } else {
                    ExecutorService pool = Executors.newFixedThreadPool(workers);
                    ArrayDeque<Future<DecodedWindow>> pending = new ArrayDeque<>(workers * 2);
                    try {
                        int completed = 0;
                        job.update("Распознаю речь · 0%");
                        for (long start = 0; start < total; ) {
                            job.check();
                            Window window = window(input, data, total, start);
                            pending.addLast(pool.submit(() -> new DecodedWindow(window.end,
                                    decode(job, environment, frontend, acoustic, tokens, window))));
                            start = window.end;
                            if (pending.size() < workers * 2 && start < total) continue;
                            do {
                                DecodedWindow decoded = finish(pending.removeFirst());
                                phrases.accept(decoded.words);
                                int percent = (int)(100 * decoded.end / total);
                                if (percent != completed) {
                                    completed = percent;
                                    job.update("Распознаю речь · " + percent + "%");
                                }
                                job.check();
                            } while (start == total && !pending.isEmpty());
                        }
                    } finally {
                        stop(pool);
                    }
                }
            }
        }
        return phrases.finish();
    }

    private static Window window(RandomAccessFile input, long data, long total, long start) throws Exception {
        long end = Math.min(total, start + CORE);
        long left = Math.max(0, start - EDGE);
        long right = Math.min(total, end + EDGE + PhoneSpeechWindow.SEARCH);
        float[] raw = readWindow(input, data + left * 2, (int)(right - left));
        if (end + EDGE < total) end = left + PhoneSpeechWindow.boundary(raw, (int)(end - left));
        int length = (int)(Math.min(total, end + EDGE) - left);
        return new Window(start, end, left, length >= 400 && !PhoneSpeechWindow.constant(raw)
                ? Arrays.copyOf(raw, length) : new float[0]);
    }

    private static JSONArray decode(PhoneAnalysisService.Job job, OrtEnvironment environment, OrtSession frontend,
                                    OrtSession acoustic, String[] tokens, Window window) throws Exception {
        job.check();
        if (window.raw.length == 0) return new JSONArray();
        float level = PhoneSpeechWindow.level(window.raw);
        float[] wave = window.raw.clone();
        PhoneSpeechWindow.normalize(wave, level, 8);
        double first = window.start / (double) RATE, last = window.end / (double) RATE;
        double offset = window.left / (double) RATE;
        JSONArray words = recognize(environment, frontend, acoustic, wave, tokens, offset, first, last, true);
        if (words.length() > 1 && (level < .05f || weak(words))) {
            job.check();
            float[] clean = PhoneSpeechWindow.clean(window.raw);
            JSONArray alternate = recognize(environment, frontend, acoustic, clean, tokens, offset, first, last, true);
            reconcile(words, alternate);
        }
        return words;
    }

    private static DecodedWindow finish(Future<DecodedWindow> result) throws Exception {
        try {
            return result.get();
        } catch (ExecutionException error) {
            Throwable cause = error.getCause();
            if (cause instanceof Exception) throw (Exception) cause;
            if (cause instanceof Error) throw (Error) cause;
            throw error;
        }
    }

    private static void stop(ExecutorService workers) {
        workers.shutdownNow();
        boolean interrupted = false;
        // Native inference must finish before the shared sessions can close.
        while (!workers.isTerminated()) {
            try {
                workers.awaitTermination(1, TimeUnit.SECONDS);
            } catch (InterruptedException error) {
                interrupted = true;
            }
        }
        if (interrupted) Thread.currentThread().interrupt();
    }

    private static final class DecodedWindow {
        final long end;
        final JSONArray words;

        DecodedWindow(long end, JSONArray words) {
            this.end = end;
            this.words = words;
        }
    }

    private static final class Window {
        final long start, end, left;
        final float[] raw;

        Window(long start, long end, long left, float[] raw) {
            this.start = start;
            this.end = end;
            this.left = left;
            this.raw = raw;
        }
    }

    private static JSONArray recognize(OrtEnvironment environment, OrtSession frontend, OrtSession acoustic,
                                       float[] wave, String[] tokens, double left, double start, double end, boolean beam)
            throws Exception {
        Map<String, OnnxTensor> inputs = new HashMap<>();
        try (OnnxTensor samples = OnnxTensor.createTensor(environment, new float[][]{wave});
             OnnxTensor lengths = OnnxTensor.createTensor(environment, new long[]{wave.length})) {
            inputs.put("waveforms", samples);
            inputs.put("waveforms_lens", lengths);
            try (OrtSession.Result prepared = frontend.run(inputs)) {
                inputs.clear();
                inputs.put("features", (OnnxTensor) prepared.get("features").get());
                OnnxTensor frames = (OnnxTensor) prepared.get("features_lens").get();
                inputs.put("feature_lengths", frames);
                int steps = (int) ((((long[]) frames.getValue())[0] + 3) / 4);
                try (OrtSession.Result result = acoustic.run(inputs)) {
                    float[][] logits = ((float[][][]) result.get("log_probs").get().getValue())[0];
                    steps = Math.min(steps, logits.length);
                    int[] alignment = beam ? PhoneCtc.alignment(logits, steps, BLANK) : null;
                    return words(logits, steps, tokens, left, start, end, left + wave.length / (double) RATE, alignment);
                }
            }
        }
    }

    private static JSONArray words(float[][] logits, int steps, String[] tokens, double left, double start, double end,
                                   double audioEnd, int[] alignment) throws Exception {
        JSONArray result = new JSONArray();
        StringBuilder word = new StringBuilder();
        double wordStart = left;
        double wordEnd = left;
        double confidence = 0;
        int pieces = 0;
        int previous = BLANK;
        for (int frame = 0; frame < steps && frame < logits.length; frame++) {
            float[] scores = logits[frame];
            int best = alignment == null ? 0 : alignment[frame];
            if (alignment == null) {
                for (int i = 1; i < scores.length; i++) {
                    if (scores[i] > scores[best]) best = i;
                }
            }
            boolean emit = best != previous && best != BLANK && best != 0;
            previous = best;
            if (!emit) continue;
            String token = tokens[best];
            if (token.startsWith("▁")) {
                appendWord(result, word, wordStart, wordEnd, confidence, pieces, start, end);
                word.setLength(0);
                pieces = 0;
                confidence = 0;
                token = token.substring(1);
            }
            if (token.isEmpty()) continue;
            if (pieces == 0) wordStart = left + frame * FRAME_SECONDS;
            wordEnd = Math.min(audioEnd, left + (frame + 1) * FRAME_SECONDS);
            word.append(token);
            confidence += Math.exp(scores[best]);
            pieces++;
        }
        appendWord(result, word, wordStart, wordEnd, confidence, pieces, start, end);
        return result;
    }

    private static void appendWord(JSONArray result, StringBuilder word, double wordStart, double wordEnd,
                                   double confidence, int pieces, double start, double end) throws Exception {
        if (pieces == 0 || word.length() == 0) return;
        double midpoint = (wordStart + wordEnd) / 2;
        if (wordStart < wordEnd && midpoint >= start && midpoint < end) {
            result.put(new JSONObject().put("word", word.toString())
                    .put("start", wordStart).put("end", wordEnd)
                    .put("conf", confidence / pieces));
        }
    }

    private static float[] readWindow(RandomAccessFile input, long offset, int count) throws Exception {
        byte[] pcm = new byte[count * 2];
        input.seek(offset);
        input.readFully(pcm);
        float[] wave = new float[count];
        for (int i = 0; i < count; i++) {
            int sample = (short) ((pcm[2 * i] & 0xff) | (pcm[2 * i + 1] << 8));
            wave[i] = sample / 32768f;
        }
        return wave;
    }

    private static boolean weak(JSONArray words) throws Exception {
        for (int i = 0; i < words.length(); i++) {
            if (words.getJSONObject(i).getDouble("conf") < .66) return true;
        }
        return false;
    }

    private static String lexical(JSONObject word) throws Exception {
        return word.getString("word").toLowerCase(Locale.ROOT).replace('ё','е')
                .replaceAll("^[«(]+|[.,;:!?…)»]+$", "");
    }

    private static boolean anchor(JSONArray base, int i, JSONArray other, int j) throws Exception {
        if (i < 0 || i >= base.length() || j < 0 || j >= other.length()) return false;
        JSONObject first = base.getJSONObject(i), second = other.getJSONObject(j);
        return Math.abs(first.getDouble("start") - second.getDouble("start")) < .28
                && !lexical(first).isEmpty() && lexical(first).equals(lexical(second));
    }

    static void reconcile(JSONArray base, JSONArray other) throws Exception {
        int j = 0;
        for (int i = 0; i < base.length() && j < other.length(); i++) {
            JSONObject word = base.getJSONObject(i);
            double time = word.getDouble("start");
            while (j + 1 < other.length()
                    && Math.abs(other.getJSONObject(j + 1).getDouble("start") - time)
                    < Math.abs(other.getJSONObject(j).getDouble("start") - time)) j++;
            JSONObject candidate = other.getJSONObject(j);
            if (Math.abs(candidate.getDouble("start") - time) > .24) continue;
            String original = lexical(word), proposed = lexical(candidate);
            if (original.equals(proposed) || original.isEmpty() || proposed.isEmpty()) continue;
            boolean anchored = anchor(base, i - 1, other, j - 1) || anchor(base, i + 1, other, j + 1);
            if (!anchored) continue;
            word.put("needs_review", true);
            double firstScore = word.getDouble("conf"), secondScore = candidate.getDouble("conf");
            if (firstScore < .72 && secondScore >= .80 && secondScore >= firstScore + .15
                    && !CRITICAL.matcher(original).matches() && !CRITICAL.matcher(proposed).matches()) {
                word.put("word", candidate.getString("word"));
            }
            j++;
        }
    }

    private static byte[] readFrontend(Context context) throws Exception {
        try (InputStream input = context.getResources().openRawResource(R.raw.gigaam_frontend);
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            for (int read; (read = input.read(buffer)) != -1; ) output.write(buffer, 0, read);
            return output.toByteArray();
        }
    }

    private static String[] readTokens(Context context) throws Exception {
        String[] tokens = new String[BLANK + 1];
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                context.getResources().openRawResource(R.raw.gigaam_tokens), StandardCharsets.UTF_8))) {
            for (String line; (line = reader.readLine()) != null; ) {
                int separator = line.lastIndexOf(' ');
                int index = Integer.parseInt(line.substring(separator + 1));
                tokens[index] = line.substring(0, separator);
            }
        }
        return tokens;
    }

    private PhoneGigaAm() {}
}
