package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

public final class AudioAnalysisActivity extends Activity {
    static final int REQUEST = 12;
    private AudioTranscriptPage page;
    private boolean startOnResume;

    static void open(Activity activity, String name, int position) {
        activity.startActivityForResult(new Intent(activity, AudioAnalysisActivity.class)
                .putExtra("recording", name).putExtra("position", position), REQUEST);
    }

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        Bundle state = saved == null ? getIntent().getExtras() : saved.getBundle("page");
        if (state == null || !LectureNotes.valid(state.getString("recording"))) {
            finish();
            return;
        }
        getWindow().setStatusBarColor(StudioStyle.BACKGROUND);
        getWindow().setNavigationBarColor(StudioStyle.BACKGROUND);
        page = new AudioTranscriptPage(this, state, null, true);
        page.setOnApplyWindowInsetsListener((view, insets) -> {
            page.addInsets(insets);
            return insets.consumeSystemWindowInsets();
        });
        setContentView(page);
        page.requestApplyInsets();
        startOnResume = saved == null;
    }

    @Override protected void onPostResume() {
        super.onPostResume();
        if (page == null) return;
        page.setActive(true);
        if (startOnResume) {
            startOnResume = false;
            page.startInitialAnalysis();
        }
    }

    @Override protected void onPause() {
        if (page != null) page.setActive(false);
        super.onPause();
    }

    @Override protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (page != null) out.putBundle("page", page.snapshot());
    }

    @Override public void finish() {
        if (page != null) setResult(RESULT_OK, new Intent().putExtras(page.snapshot()));
        super.finish();
    }

    @Override protected void onDestroy() {
        if (page != null) page.dispose();
        super.onDestroy();
    }
}
