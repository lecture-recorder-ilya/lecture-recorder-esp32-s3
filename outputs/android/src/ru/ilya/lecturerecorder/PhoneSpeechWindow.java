package ru.ilya.lecturerecorder;

import java.util.Arrays;

final class PhoneSpeechWindow {
    static final int RATE = 16000;
    static final int FRAME = RATE / 50;
    static final int SEARCH = RATE;
    private static final int BAND_COUNT = 3;
    private static final float RUMBLE = (float) Math.exp(-2 * Math.PI * 80 / RATE);
    private static final float LOW = 1 - (float) Math.exp(-2 * Math.PI * 600 / RATE);
    private static final float MID = 1 - (float) Math.exp(-2 * Math.PI * 2400 / RATE);

    static int boundary(float[] wave, int nominal) {
        int from = Math.max(0, nominal - SEARCH);
        int to = Math.min(wave.length, nominal + SEARCH);
        int frames = (to - from) / FRAME;
        if (frames < 15) return nominal;
        double[] energy = new double[frames];
        for (int f = 0; f < frames; f++) {
            int start = from + f * FRAME;
            for (int i = start + 1; i < start + FRAME; i++) {
                float difference = wave[i] - wave[i - 1];
                energy[f] += difference * difference;
            }
        }
        double[] sorted = energy.clone();
        Arrays.sort(sorted);
        double limit = Math.max(1e-11, sorted[(int) (frames * .80)] * .18);
        int best = nominal;
        int distance = Integer.MAX_VALUE;
        for (int f = 0; f < frames; ) {
            int first = f;
            while (f < frames && energy[f] <= limit) f++;
            if (f - first >= 6) {
                int center = from + (first + f) * FRAME / 2;
                if (Math.abs(center - nominal) < distance) {
                    best = center;
                    distance = Math.abs(center - nominal);
                }
            }
            f++;
        }
        return best;
    }

    static float level(float[] wave) {
        int[] histogram = new int[32769];
        for (int i = 0; i < wave.length; i += 4) {
            histogram[Math.min(32768, Math.round(Math.abs(wave[i]) * 32768))]++;
        }
        int remaining = (int) Math.ceil(((wave.length + 3) / 4) * .995);
        int bin = 0;
        while (remaining > histogram[bin]) remaining -= histogram[bin++];
        return bin / 32768f;
    }

    static void normalize(float[] wave, float level, float maxGain) {
        float gain = Math.min(maxGain, .39f / Math.max(level, .001f));
        for (int i = 0; i < wave.length; i++) wave[i] = Math.max(-1f, Math.min(1f, wave[i] * gain));
    }

    static boolean constant(float[] wave, int length) {
        for (int i = 1; i < length; i++) if (wave[i] != wave[0]) return false;
        return true;
    }

    static float[] clean(float[] raw) {
        int frames = (raw.length + FRAME - 1) / FRAME;
        float[][] bands = new float[BAND_COUNT][raw.length];
        double[][] powers = new double[BAND_COUNT][frames];
        float highpass = 0;
        float previous = raw[0];
        float low = 0;
        float mid = 0;
        for (int i = 0; i < raw.length; i++) {
            highpass = RUMBLE * (highpass + raw[i] - previous);
            previous = raw[i];
            low += LOW * (highpass - low);
            mid += MID * (highpass - mid);
            bands[0][i] = low;
            bands[1][i] = mid - low;
            bands[2][i] = highpass - mid;
            for (int b = 0; b < BAND_COUNT; b++) {
                powers[b][i / FRAME] += bands[b][i] * bands[b][i];
            }
        }

        float[] clean = new float[raw.length];
        for (int b = 0; b < BAND_COUNT; b++) {
            double[] power = powers[b];
            for (int f = 0; f < frames; f++) power[f] /= Math.min(FRAME, raw.length - f * FRAME);
            double[] sorted = power.clone();
            Arrays.sort(sorted);
            double floor = sorted[frames / 5];
            float previousGain = 1;
            for (int f = 0; f < frames; f++) {
                double energy = (power[Math.max(0, f - 1)] + 2 * power[f] + power[Math.min(frames - 1, f + 1)]) * .25;
                float gain = (float) Math.sqrt(Math.max(.09, 1 - floor / Math.max(energy, 1e-14)));
                int length = Math.min(FRAME, raw.length - f * FRAME);
                for (int j = 0; j < length; j++) {
                    int i = f * FRAME + j;
                    clean[i] += bands[b][i] * (previousGain + (gain - previousGain) * (j + 1) / length);
                }
                previousGain = gain;
            }
        }
        normalize(clean, level(clean), 32f);
        return clean;
    }

    private PhoneSpeechWindow() {}
}
