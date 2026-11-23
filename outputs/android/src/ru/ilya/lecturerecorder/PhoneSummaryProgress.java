package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashSet;
import java.util.Set;
final class PhoneSummaryProgress {
    private static final int VERSION = 2;
    private final File file;
    private final String transcript;
    private boolean canSave = true;
    final JSONArray summary, sources, homework, review;
    final Set<String> points = new HashSet<>();
    final Set<String> tasks = new HashSet<>();
    int next;
    static PhoneSummaryProgress open(Context context, String recording, JSONArray segments) throws Exception {
        return new PhoneSummaryProgress(file(context, recording), fingerprint(segments), segments);
    }

    private PhoneSummaryProgress(File file, String transcript, JSONArray segments) {
        this.file = file;
        this.transcript = transcript;
        JSONArray savedSummary = new JSONArray(), savedSources = new JSONArray(), savedHomework = new JSONArray(), savedReview = new JSONArray();
        if (file.isFile()) {
            try {
                JSONObject saved = new JSONObject(Store.read(file));
                int cursor = saved.optInt("next", -1);
                if (saved.optInt("version") == VERSION && transcript.equals(saved.optString("transcript")) && cursor > 0 && cursor <= segments.length()) {
                    JSONArray candidates = saved.getJSONArray("summary"), citations = saved.getJSONArray("sources");
                    JSONArray exercises = saved.getJSONArray("homework");
                    if (candidates.length() != citations.length()) throw new IllegalArgumentException("Checkpoint evidence mismatch");
                    JSONObject verified = new JSONObject().put("segments", segments).put("summary", candidates)
                    .put("summary_evidence", citations).put("homework", exercises);
                    SummarySources.reconcile(verified, false, true);
                    for (int i = 0; i < citations.length(); i++)if (!"confirmed".equals(verified.getJSONArray("summary_evidence").getJSONObject(i).optString("source_status")))throw new IllegalArgumentException("Checkpoint source mismatch");
                    for (int i = 0; i < exercises.length(); i++)if (!"confirmed".equals(verified.getJSONArray("homework").getJSONObject(i).optString("source_status")))throw new IllegalArgumentException("Checkpoint homework mismatch");
                    for (int i = 0; i < candidates.length(); i++) points.add(candidates.getString(i));
                    for (int i = 0; i < exercises.length(); i++) tasks.add(exercises.getJSONObject(i).getString("task"));
                    savedSummary = candidates;
                    savedSources = citations;
                    savedHomework = exercises;
                    savedReview = saved.optJSONArray("review");
                    if (savedReview == null)savedReview = new JSONArray();
                    next = cursor;
                }
            }
            catch (Exception unusable) {
                points.clear();
                tasks.clear();
            }
        }
        summary = savedSummary;
        sources = savedSources;
        homework = savedHomework;
        review = savedReview;
    }
    void checkpoint(int cursor) {
        next = cursor;
        if (!canSave) return;
        try {
            File parent = file.getParentFile();
            if (!parent.isDirectory() && !parent.mkdirs()) throw new java.io.IOException("Checkpoint folder unavailable");
            Store.write(file, new JSONObject().put("version", VERSION).put("transcript", transcript)
            .put("next", next).put("summary", summary).put("sources", sources).put("homework", homework).put("review", review));
        }
        catch (Exception unavailable) {
            canSave = false;
        }
    }

    static void clear(Context context, String recording) {
        file(context, recording).delete();
    }

    private static File file(Context context, String recording) {
        if (!LectureNotes.valid(recording)) throw new IllegalArgumentException("Invalid recording");
        return new File(new File(context.getFilesDir(), "phone-summary-progress"), recording + ".json");
    }

    private static String fingerprint(JSONArray segments) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(segments.toString().getBytes(StandardCharsets.UTF_8));
        StringBuilder result = new StringBuilder(64);
        for (byte value : digest) {
            result.append(Character.forDigit((value & 0xff) >>> 4, 16));
            result.append(Character.forDigit(value & 0xf, 16));
        }
        return result.toString();
    }
}
