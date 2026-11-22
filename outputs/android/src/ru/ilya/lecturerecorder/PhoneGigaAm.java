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
import java.util.HashMap;
import java.util.Map;

final class PhoneGigaAm {
    private static final int RATE = PcmWave.SAMPLE_RATE;
    private static final int CORE = 18 * RATE;
    private static final int EDGE = 2 * RATE;
    private static final int BLANK = 256;
    private static final double FRAME_SECONDS = 0.04;

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
        JSONArray segments = new JSONArray();
        String[] tokens = readTokens(context);
        OrtEnvironment environment = OrtEnvironment.getEnvironment();
        try (OrtSession.SessionOptions options = new OrtSession.SessionOptions()) {
            options.setIntraOpNumThreads(4);
            options.setInterOpNumThreads(1);
            options.addConfigEntry("session.intra_op.allow_spinning", "0");
            try (OrtSession frontend = environment.createSession(readFrontend(context), options);
                 OrtSession acoustic = environment.createSession(model.getPath(), options)) {
                int progress = -1;
                for (long start = 0; start < total; start += CORE) {
                    job.check();
                    long end = Math.min(total, start + CORE);
                    int percent = (int) (100 * start / total);
                    if (progress != percent) {
                        progress = percent;
                        job.update("Распознаю речь · " + percent + "%");
                    }
                    long left = Math.max(0, start - EDGE);
                    long right = Math.min(total, end + EDGE);
                    int count = (int) (right - left);
                    if (count < 400) continue;
                    float[] wave = readWindow(input, data + left * 2, count);
                    JSONArray words = recognize(environment, frontend, acoustic, wave, tokens,
                            left / (double) RATE, start / (double) RATE, end / (double) RATE);
                    PhoneLectureAnalysis.append(segments, words);
                }
            }
        }
        return segments;
    }

    private static JSONArray recognize(OrtEnvironment environment, OrtSession frontend, OrtSession acoustic,
                                       float[] wave, String[] tokens, double left, double start, double end)
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
                    return words(logits, steps, tokens, left, start, end, left + wave.length / (double) RATE);
                }
            }
        }
    }

    private static JSONArray words(float[][] logits, int steps, String[] tokens, double left, double start, double end,
                                   double audioEnd) throws Exception {
        JSONArray result = new JSONArray();
        StringBuilder word = new StringBuilder();
        double wordStart = left;
        double wordEnd = left;
        double confidence = 0;
        int pieces = 0;
        int previous = BLANK;
        for (int frame = 0; frame < steps && frame < logits.length; frame++) {
            float[] scores = logits[frame];
            int best = 0;
            for (int i = 1; i < scores.length; i++) {
                if (scores[i] > scores[best]) best = i;
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
        if (midpoint >= start && midpoint < end) {
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
        int[] magnitudes = new int[32769];
        for (int i = 0; i < count; i++) {
            int sample = (short) ((pcm[2 * i] & 0xff) | (pcm[2 * i + 1] << 8));
            wave[i] = sample / 32768f;
            if (i % 4 == 0) magnitudes[Math.abs(sample)]++;
        }
        int percentile = (int) Math.ceil(((count + 3) / 4) * 0.995);
        int level = 0;
        while (percentile > magnitudes[level]) percentile -= magnitudes[level++];
        float gain = Math.min(8f, 0.39f / Math.max(level / 32768f, 0.007f));
        for (int i = 0; i < count; i++) wave[i] = Math.max(-1f, Math.min(1f, wave[i] * gain));
        return wave;
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
