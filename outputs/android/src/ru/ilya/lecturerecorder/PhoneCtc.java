package ru.ilya.lecturerecorder;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

final class PhoneCtc {
    private static final int WIDTH = 5;
    private static final int LABELS = 5;
    private static final double EMPTY = Double.NEGATIVE_INFINITY;

    static int[] alignment(float[][] logits, int steps, int blank) {
        List<Path> beam = new ArrayList<>();
        Path initial = new Path("");
        initial.blank.add(0, 0, null);
        beam.add(initial);
        int[] labels = new int[LABELS];
        for (int t = 0; t < steps; t++) {
            float[] scores = logits[t];
            Arrays.fill(labels, -1);
            for (int id = 1; id < scores.length; id++) {
                if (id == blank) continue;
                for (int k = 0; k < labels.length; k++) {
                    if (labels[k] == -1 || scores[id] > scores[labels[k]]) {
                        System.arraycopy(labels, k, labels, k + 1, labels.length - k - 1);
                        labels[k] = id;
                        break;
                    }
                }
            }
            Map<String, Path> expanded = new HashMap<>();
            for (Path path : beam) {
                Path same = expanded.computeIfAbsent(path.tokens, Path::new);
                Emission best = path.best();
                same.blank.add(path.total() + scores[blank], best.viterbi + scores[blank], best.trace);
                int last = path.tokens.isEmpty() ? -1 : path.tokens.charAt(path.tokens.length() - 1);
                if (last >= 0) {
                    same.spoken.add(path.spoken.total + scores[last], path.spoken.viterbi + scores[last], path.spoken.trace);
                }
                for (int id : labels) {
                    if (id < 0 || scores[id] < Math.max(scores[blank], scores[labels[0]]) - 7) break;
                    double source = id == last ? path.blank.total : path.total();
                    if (source == EMPTY) continue;
                    Emission previous = id == last ? path.blank : best;
                    String key = path.tokens + (char) id;
                    Emission target = expanded.computeIfAbsent(key, Path::new).spoken;
                    double viterbi = previous.viterbi + scores[id];
                    Trace trace = viterbi > target.viterbi ? new Trace(previous.trace, t, id) : null;
                    target.add(source + scores[id], viterbi, trace);
                }
            }
            beam = new ArrayList<>(expanded.values());
            beam.sort((a, b) -> {
                int rank = Double.compare(b.total(), a.total());
                return rank != 0 ? rank : a.tokens.compareTo(b.tokens);
            });
            if (beam.size() > WIDTH) beam.subList(WIDTH, beam.size()).clear();
        }
        int[] ids = new int[steps];
        Arrays.fill(ids, blank);
        for (Trace trace = beam.get(0).best().trace; trace != null; trace = trace.previous) ids[trace.frame] = trace.id;
        return ids;
    }

    private static double sum(double a, double b) {
        if (a == EMPTY || b == EMPTY) return Math.max(a, b);
        return Math.max(a, b) + Math.log1p(Math.exp(-Math.abs(a - b)));
    }

    private static final class Trace {
        final Trace previous;
        final int frame;
        final int id;

        Trace(Trace previous, int frame, int id) {
            this.previous = previous;
            this.frame = frame;
            this.id = id;
        }
    }

    private static final class Emission {
        double total = EMPTY;
        double viterbi = EMPTY;
        Trace trace;

        void add(double probability, double best, Trace path) {
            total = sum(total, probability);
            if (best > viterbi) {
                viterbi = best;
                trace = path;
            }
        }
    }

    private static final class Path {
        final String tokens;
        final Emission blank = new Emission();
        final Emission spoken = new Emission();

        Path(String tokens) { this.tokens = tokens; }
        double total() { return sum(blank.total, spoken.total); }
        Emission best() { return blank.viterbi > spoken.viterbi ? blank : spoken; }
    }

    private PhoneCtc() {}
}
