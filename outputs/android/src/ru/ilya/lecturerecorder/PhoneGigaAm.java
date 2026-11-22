package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import ai.onnxruntime.OnnxTensor;
import ai.onnxruntime.OrtEnvironment;
import ai.onnxruntime.OrtSession;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Locale;
import java.util.regex.Pattern;
import java.util.Map;

final class PhoneGigaAm {
    private static final int RATE = PcmWave.SAMPLE_RATE;
    private static final int ONSET_PAD = 10240;
    private static final Pattern CONTENT = Pattern.compile("[\\p{L}\\p{N}]");
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
        PhonePhrases phrases = new PhonePhrases();
        PhoneWordTimeline timeline = new PhoneWordTimeline(phrases, EDGE / (double) RATE);
        String[] tokens = readTokens(context);
        OrtEnvironment environment = OrtEnvironment.getEnvironment();
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(4);
            options.setInterOpNumThreads(1);
            options.addConfigEntry("session.intra_op.allow_spinning", "0");
            try (OrtSession frontend = environment.createSession(readFrontend(context), options);
                 OrtSession acoustic = environment.createSession(model.getPath(), options)) {
                int progress = -1;
                for (long start = 0; start < total; ) {
                    job.check();
                    long end = Math.min(total, start + CORE);
                    int percent = (int) (100 * start / total);
                    if (progress != percent) {
                        progress = percent;
                        job.update("Распознаю речь · " + percent + "%");
                    }
                    long left = Math.max(0, start - EDGE);
                    long right = Math.min(total, end + EDGE + PhoneSpeechWindow.SEARCH);
                    float[] raw = readWindow(input, data + left * 2, (int) (right - left));
                    if (end + EDGE < total) {
                        end = left + PhoneSpeechWindow.boundary(raw, (int) (end - left));
                    }
                    int length = (int) (Math.min(total, end + EDGE) - left);
                    if (length >= 400 && !PhoneSpeechWindow.constant(raw, length)) {
                        raw = Arrays.copyOf(raw, length);
                        float level = PhoneSpeechWindow.level(raw);
                        float[] wave = raw.clone();
                        PhoneSpeechWindow.normalize(wave, level, 8);
                        double first = start / (double) RATE, last = end / (double) RATE;
                        double offset = left / (double) RATE;
                        JSONArray words = recognize(environment, frontend, acoustic, wave, tokens, offset, first, last, true);
                        if (words.length() == 1 && words.getJSONObject(0).optBoolean("verify_onset")) {
                            job.check();
                            float[] shifted = new float[ONSET_PAD + wave.length];
                            System.arraycopy(wave, 0, shifted, ONSET_PAD, wave.length);
                            JSONArray check = recognize(environment, frontend, acoustic, shifted, tokens,
                                    0, 0, shifted.length / (double) RATE, true);
                            if (hasSpeechAfterPadding(check)) words.getJSONObject(0).put("needs_review", true);
                            else words = new JSONArray();
                        }
                        if (shouldRefine(level, words)) {
                            job.check();
                            float[] clean = PhoneSpeechWindow.clean(raw);
                            JSONArray alternate = recognize(environment, frontend, acoustic, clean, tokens, offset, first, last, true);
                            reconcile(words, alternate);
                        }
                        for (int i = 0; i < words.length(); i++) {
                            JSONObject word = words.getJSONObject(i);
                            double startTime = word.getDouble("start");
                            double trimmed = PhoneSpeechWindow.trimSilentStart(raw, offset, startTime, word.getDouble("end"));
                            if (trimmed > startTime) word.put("start", trimmed);
                        }
                        timeline.accept(words, last);
                    }
                    start = end;
                }
            }
        }
        timeline.finish();
        return phrases.finish();
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
        double textStart = left, textEnd = left, openingTextEnd = left;
        double confidence = 0;
        int pieces = 0, speechPieces = 0;
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
                appendWord(result, word, speechPieces > 0 ? wordStart : textStart,
                        speechPieces > 0 ? wordEnd : textEnd, textStart, textEnd,
                        confidence, pieces, start, end);
                word.setLength(0);
                pieces = speechPieces = 0;
                confidence = 0;
                token = token.substring(1);
            }
            if (token.isEmpty()) continue;
            if (pieces == 0) textStart = left + frame * FRAME_SECONDS;
            textEnd = Math.min(audioEnd, left + (frame + 1) * FRAME_SECONDS);
            if (result.length() == 0) openingTextEnd = textEnd;
            // Пунктуация остаётся в тексте и уверенности, но не растягивает речь.
            if (CONTENT.matcher(token).find()) {
                if (speechPieces++ == 0) wordStart = left + frame * FRAME_SECONDS;
                wordEnd = textEnd;
            }
            word.append(token);
            confidence += Math.exp(scores[best]);
            pieces++;
        }
        appendWord(result, word, speechPieces > 0 ? wordStart : textStart,
                speechPieces > 0 ? wordEnd : textEnd, textStart, textEnd,
                confidence, pieces, start, end);
        if (steps > 0 && alignment != null && result.length() == 1) {
            JSONObject only = result.getJSONObject(0);
            int onset = alignment[0];
            // Короткая речевая граница не отменяет проверку старого длинного следа.
            if (onset != BLANK && onset != 0 && only.getDouble("start") == left
                    && PhoneCtc.weakOpeningLetter(only.getString("word"), tokens[onset], logits[0][onset],
                                                  openingTextEnd - left)) {
                only.put("verify_onset", true);
            }
        }
        return result;
    }

    private static boolean hasSpeechAfterPadding(JSONArray check) throws Exception {
        double earliest = ONSET_PAD / (double) RATE - 3 * FRAME_SECONDS;
        for (int i = 0; i < check.length(); i++) {
            JSONObject word = check.getJSONObject(i);
            if (word.getDouble("start") >= earliest && CONTENT.matcher(word.getString("word")).find()) return true;
        }
        return false;
    }

    private static void appendWord(JSONArray result, StringBuilder word, double wordStart, double wordEnd,
                                   double textStart, double textEnd,
                                   double confidence, int pieces, double start, double end) throws Exception {
        if (pieces == 0 || word.length() == 0) return;
        // Первая буква бывает в нулевом кадре. Окно выбирает последний речевой кадр,
        // а не середина между этой буквой и концом слова.
        double speechFrame = Math.max(wordStart, wordEnd - FRAME_SECONDS / 2);
        double textMidpoint = (textStart + textEnd) / 2;
        boolean legacyCore = textMidpoint >= start && textMidpoint < end;
        // Старый проход может лучше разобрать слово из перекрытия. Сверяем его
        // с соседом до выдачи фраз, вместо потери при новой привязке к кадру.
        if (wordStart < wordEnd && (legacyCore || speechFrame >= start && speechFrame < end)) {
            result.put(new JSONObject().put("word", word.toString())
                    .put("start", wordStart).put("end", wordEnd)
                    .put("conf", confidence / pieces).put("_legacy_core", legacyCore));
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

    static boolean shouldRefine(float level, JSONArray words) throws Exception {
        // С одним словом нет соседнего якоря: reconcile не может ни заменить,
        // ни пометить его. Пустой проход также не получает слов из alternate.
        return words.length() >= 2 && (level < .05f || weak(words));
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
