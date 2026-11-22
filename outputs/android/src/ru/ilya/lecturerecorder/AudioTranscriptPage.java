package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.content.Intent;
import android.app.Dialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.LinearGradient;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputFilter;
import android.text.InputType;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.TextUtils;
import android.text.method.LinkMovementMethod;
import android.text.style.ClickableSpan;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.AbsListView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.TreeMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

final class AudioTranscriptPage extends LinearLayout {
    private static final int BACKGROUND = StudioStyle.BACKGROUND;
    private static final int TEXT = StudioStyle.TEXT;
    private static final int MUTED = StudioStyle.MUTED;
    private static final int ACCENT = StudioStyle.ACCENT;

    private final Activity activity;
    private final boolean landscape, analysis;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService audioScan = Executors.newSingleThreadExecutor();
    private final Runnable playbackTick = this::refreshPlayback;
    private final Runnable transcriptTick = this::refreshTranscript;
    private Future<?> scan;
    private MediaPlayer player;
    private boolean prepared;
    private boolean playWhenReady;
    private boolean visible;
    private boolean disposed;
    private int position;
    private int duration;
    private String selected;
    private String noteRevision;
    private ChoiceDropdown recordingDropdown;
    private Button play;
    private Button transcribe;
    private Button openReader, textTab, summaryTab;
    private Button importButton;
    private TextView importStatus, recordingHint, analysisTitle;
    private TextView summaryStatus, summaryText;
    private ScrollView summaryPanel;
    private boolean showingSummary;
    private JSONObject savedReport, summaryReport;
    private JSONObject savedCorrections = new JSONObject();
    private boolean savedLocally;
    private Object renderedSummary;
    private String liveSummary;
    private AnalysisPreview.Transcript preview;
    private final List<TranscriptEdits.Line> liveRows = new ArrayList<>();
    private String playingKey;
    private long manualScrollUntil;
    private int animatedThrough = -1;
    private TextView times;
    private TextView waveStatus, recordingDate;
    private TextView transcriptStatus;
    private LinearLayout transcriptProgress;
    private Dialog wordEditor;
    private final LinearLayout audioPanel;
    private LinearLayout transcriptPanel;
    private ProgressBar transcriptSpinner;
    private TranscriptAdapter transcript;
    private CheckBox reviewFilter;
    private ListView transcriptList;
    private Button nextReview;
    private String reviewKey;
    private List<TranscriptEdits.Line> transcriptRows = Collections.emptyList();
    private List<TranscriptEdits.Line> reviewRows = Collections.emptyList();
    private Waveform waveform;

    AudioTranscriptPage(Activity activity, Bundle state, Runnable importAudio) {
        this(activity, state, importAudio, false);
    }

    AudioTranscriptPage(Activity activity, Bundle state, Runnable importAudio, boolean analysis) {
        super(activity);
        this.activity = activity;
        this.analysis = analysis;
        setOrientation(VERTICAL);
        setBackgroundColor(BACKGROUND);
        setPadding(dp(16), dp(analysis ? 6 : 14), dp(16), dp(10));
        landscape = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;

        LinearLayout playback = this;
        LinearLayout columns = null;
        if (analysis) {
            addAnalysisHeader();
            if (landscape) {
                columns = new LinearLayout(activity);
                addView(columns, new LinearLayout.LayoutParams(-1, 0, 1));
                playback = column();
                columns.addView(playback, new LinearLayout.LayoutParams(0, -1, 1));
            }
        } else {
            TextView heading = text("Аудио", landscape ? 24 : 28, TEXT);
            heading.setTypeface(Typeface.DEFAULT_BOLD);
            heading.setLetterSpacing(-.025f);
            if (android.os.Build.VERSION.SDK_INT >= 28) heading.setAccessibilityHeading(true);
            addView(heading);
            addLibraryPicker(importAudio);
        }

        FrameLayout playbackHost = new FrameLayout(activity);
        playback.addView(playbackHost, new LinearLayout.LayoutParams(-1,
                !analysis || landscape ? 0 : -2, !analysis || landscape ? 1 : 0));
        LinearLayout details = column();
        playbackHost.addView(details, new FrameLayout.LayoutParams(-1, analysis && !landscape ? -2 : -1));
        if (!analysis) {
            recordingHint = text("", 15, MUTED);
            details.addView(recordingHint, spaced(-1, -2, 12));
            updateRecordingHint();
        }

        audioPanel = card();
        audioPanel.setVisibility(View.GONE);
        details.addView(audioPanel, spaced(-1, -2, analysis ? 4 : 12));
        addAudioPanel(audioPanel);
        addAnalysisAction(details);

        if (analysis) {
            LinearLayout content = column();
            if (landscape) {
                LinearLayout.LayoutParams area = new LinearLayout.LayoutParams(0, -1, 2);
                area.setMarginStart(dp(12));
                columns.addView(content, area);
            } else addView(content, new LinearLayout.LayoutParams(-1, 0, 1));
            addAnalysisTabs(content);
            FrameLayout panels = new FrameLayout(activity);
            content.addView(panels, new LinearLayout.LayoutParams(-1, 0, 1));
            transcriptPanel = card();
            panels.addView(transcriptPanel, new FrameLayout.LayoutParams(-1, -1));
            addTranscriptPanel(transcriptPanel);
            addSummaryPanel(panels);
            showSummary(state != null && state.getBoolean("show_summary"));
        } else addRecordingDropdown(playbackHost);

        if (state != null) {
            String name = state.getString("recording");
            if (LectureNotes.valid(name)) {
                select(name, state.getInt("position"));
                if (analysis && !reviewRows.isEmpty()) {
                    reviewKey = state.getString("review_key");
                    reviewFilter.setChecked(state.getBoolean("reviewOnly"));
                }
            }
        }
    }

    void addInsets(WindowInsets insets) {
        setPadding(dp(16) + insets.getSystemWindowInsetLeft(), dp(6) + insets.getSystemWindowInsetTop(),
                dp(16) + insets.getSystemWindowInsetRight(), dp(10) + insets.getSystemWindowInsetBottom());
    }

    private void addAnalysisHeader() {
        LinearLayout header = new LinearLayout(activity);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.addView(button("‹ Аудио", activity::finish), new LinearLayout.LayoutParams(-2, dp(44)));
        LinearLayout titles = column();
        analysisTitle = text("", 20, TEXT);
        analysisTitle.setTypeface(Typeface.DEFAULT_BOLD);
        analysisTitle.setMaxLines(2);
        analysisTitle.setEllipsize(TextUtils.TruncateAt.END);
        titles.addView(analysisTitle);
        recordingDate = text("", 12, MUTED);
        titles.addView(recordingDate);
        LinearLayout.LayoutParams slot = new LinearLayout.LayoutParams(0, -2, 1);
        slot.setMarginStart(dp(12));
        header.addView(titles, slot);
        addView(header, spaced(-1, -2, 0));
    }

    private void addLibraryPicker(Runnable importAudio) {
        recordingDropdown = new ChoiceDropdown(activity, "Выбрать запись", "Сохранённых записей пока нет",
                this::recordingOptions, option -> {
                    if (!option.value.equals(selected)) select(option.value, 0);
                });
        LinearLayout picker = new LinearLayout(activity);
        picker.addView(recordingDropdown.button, new LinearLayout.LayoutParams(0, -1, 1));
        importButton = button("Импорт", () -> {
            closeDropdown();
            importAudio.run();
        });
        importButton.setContentDescription("Импорт аудиозаписи");
        LinearLayout.LayoutParams importAction = new LinearLayout.LayoutParams(-2, -1);
        importAction.setMarginStart(dp(8));
        picker.addView(importButton, importAction);
        int pickerHeight = getResources().getConfiguration().fontScale > 1.25f ? 72 : 52;
        addView(picker, spaced(-1, dp(pickerHeight), 10));
        recordingDate = text("", 12, MUTED);
        recordingDate.setVisibility(View.GONE);
        addView(recordingDate, spaced(-1, -2, 3));
        importStatus = text("", 13, MUTED);
        importStatus.setVisibility(View.GONE);
        importStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        addView(importStatus, spaced(-1, -2, 4));
    }

    private void addAudioPanel(LinearLayout audio) {
        waveform = new Waveform(activity);
        audio.addView(waveform, new LinearLayout.LayoutParams(-1, dp(analysis ? 56 : landscape ? 62 : 110)));
        waveStatus = text("", 13, MUTED);
        waveStatus.setVisibility(View.GONE);
        audio.addView(waveStatus);

        LinearLayout controls = new LinearLayout(activity);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        play = button("Слушать", this::togglePlayback);
        controls.addView(play, new LinearLayout.LayoutParams(-2, dp(48)));
        times = text("", 13, MUTED);
        times.setTypeface(Typeface.MONOSPACE);
        times.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        controls.addView(times, new LinearLayout.LayoutParams(0, -1, 1));
        audio.addView(controls, spaced(-1, dp(44), 4));
    }

    private void addAnalysisAction(LinearLayout host) {
        transcribe = button(analysis ? "Расшифровать заново" : "Разобрать", () -> {
            if (selected == null) return;
            if (!analysis) {
                closeDropdown();
                AudioAnalysisActivity.open(activity, selected, position);
            } else if (PhoneAnalysisService.busyFor(selected)) {
                activity.startService(PhoneAnalysisService.cancel(activity));
            } else if (!PhoneAnalysisService.busy()) {
                if (savedLocally && savedReport != null && savedReport.optBoolean(LectureNotes.SUMMARY_PENDING))
                    PhoneAnalysisService.requestSummary(activity, selected, Store.recordingTitle(activity, selected));
                else if (Store.audio(activity, selected).isFile())
                    PhoneAnalysisService.request(activity, selected, Store.recordingTitle(activity, selected), true);
            }
        });
        transcribe.setVisibility(View.GONE);
        transcribe.setBackground(StudioStyle.control(activity, analysis ? StudioStyle.ACTIVE : ACCENT, 16));
        transcribe.setTextColor(analysis ? ACCENT : StudioStyle.INK);
        transcribe.setTextSize(analysis ? 14 : 19);
        host.addView(transcribe, spaced(-1, dp(analysis ? 42 : landscape ? 52 : 62), analysis ? 2 : 10));
    }

    void startInitialAnalysis() {
        if (!analysis || selected == null || PhoneAnalysisService.busy() || !android.os.Process.is64Bit()) return;
        String title = Store.recordingTitle(activity, selected);
        File local = LectureNotes.file(activity, selected, true);
        if (savedReport == null && Store.audio(activity, selected).isFile()) {
            PhoneAnalysisService.request(activity, selected, title, local.isFile());
        } else if (local.isFile() && savedReport != null && savedReport.optBoolean(LectureNotes.SUMMARY_PENDING)) {
            PhoneAnalysisService.requestSummary(activity, selected, title);
        }
    }

    private void addAnalysisTabs(LinearLayout content) {
        LinearLayout tabs = new LinearLayout(activity);
        tabs.setPadding(dp(4), dp(4), dp(4), dp(4));
        tabs.setBackground(StudioStyle.card(activity, 16));
        textTab = button("Расшифровка", () -> showSummary(false));
        summaryTab = button("Конспект", () -> showSummary(true));
        for (Button tab : new Button[]{textTab, summaryTab})
            tabs.addView(tab, new LinearLayout.LayoutParams(0, dp(40), 1));
        LinearLayout.LayoutParams placement = spaced(-1, -2, 7);
        placement.bottomMargin = dp(7);
        content.addView(tabs, placement);
    }

    private void showSummary(boolean summary) {
        showingSummary = summary;
        transcriptPanel.setVisibility(summary ? View.GONE : View.VISIBLE);
        summaryPanel.setVisibility(summary ? View.VISIBLE : View.GONE);
        textTab.setSelected(!summary);
        summaryTab.setSelected(summary);
        textTab.setTextColor(summary ? MUTED : ACCENT);
        summaryTab.setTextColor(summary ? ACCENT : MUTED);
        textTab.setBackground(StudioStyle.control(activity, summary ? Color.TRANSPARENT : StudioStyle.ACTIVE, 12));
        summaryTab.setBackground(StudioStyle.control(activity, summary ? StudioStyle.ACTIVE : Color.TRANSPARENT, 12));
        if (!summary) syncPlayback(false);
    }

    private void addSummaryPanel(FrameLayout host) {
        summaryPanel = new ScrollView(activity);
        summaryPanel.setFillViewport(true);
        LinearLayout content = card();
        summaryPanel.addView(content, new ScrollView.LayoutParams(-1, -2));
        host.addView(summaryPanel, new FrameLayout.LayoutParams(-1, -1));
        summaryStatus = text("Конспект появится после расшифровки", 15, MUTED);
        summaryStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        content.addView(summaryStatus, spaced(-1, -2, 6));
        summaryText = text("", 16, TEXT);
        summaryText.setLineSpacing(dp(5), 1);
        content.addView(summaryText, spaced(-1, -2, 4));
        openReader = button("Полный конспект и проверка", this::openSummary);
        openReader.setVisibility(View.GONE);
        content.addView(openReader, spaced(-1, dp(48), 10));
    }

    private void openSummary() {
        if (selected == null) return;
        boolean local = LectureNotes.file(activity, selected, true).isFile();
        if (!local && !LectureNotes.file(activity, selected, false).isFile()) return;
        activity.startActivity(new Intent(activity, LectureReaderActivity.class)
                .putExtra("file", selected + ".json").putExtra("local", local).putExtra("tab", "summary"));
    }

    void openRecording(String name) {
        if (LectureNotes.valid(name)) select(name, 0);
    }

    void restorePosition(Bundle result) {
        if (result != null && selected != null && selected.equals(result.getString("recording"))) {
            seek(result.getInt("position"), false);
            noteRevision = null;
            refreshTranscriptState();
        }
    }

    private void addTranscriptPanel(LinearLayout box) {
        transcriptProgress = new LinearLayout(activity);
        transcriptProgress.setGravity(Gravity.CENTER_VERTICAL);
        transcriptStatus = text("", 14, MUTED);
        transcriptStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        transcriptProgress.addView(transcriptStatus, new LinearLayout.LayoutParams(0, -2, 1));
        transcriptSpinner = new ProgressBar(activity);
        transcriptSpinner.setIndeterminateTintList(ColorStateList.valueOf(ACCENT));
        transcriptSpinner.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        transcriptSpinner.setVisibility(View.GONE);
        transcriptProgress.addView(transcriptSpinner, new LinearLayout.LayoutParams(dp(18), dp(18)));
        box.addView(transcriptProgress);

        reviewFilter = new CheckBox(activity);
        reviewFilter.setTextColor(TEXT);
        reviewFilter.setButtonTintList(ColorStateList.valueOf(ACCENT));
        reviewFilter.setMinHeight(dp(48));
        reviewFilter.setVisibility(View.GONE);
        box.addView(reviewFilter, spaced(-1, -2, 4));

        nextReview = button("Следующий сомнительный фрагмент", this::nextReviewFragment);
        nextReview.setMinHeight(dp(48));
        nextReview.setVisibility(View.GONE);
        box.addView(nextReview, spaced(-1, -2, 4));

        ListView lines = new ListView(activity);
        transcriptList = lines;
        transcript = new TranscriptAdapter(activity);
        lines.setAdapter(transcript);
        lines.setDivider(null);
        lines.setDividerHeight(0);
        lines.setOnScrollListener(new AbsListView.OnScrollListener() {
            @Override public void onScroll(AbsListView view, int first, int count, int total) {}
            @Override public void onScrollStateChanged(AbsListView view, int state) {
                if (state == SCROLL_STATE_TOUCH_SCROLL || state == SCROLL_STATE_FLING)
                    manualScrollUntil = android.os.SystemClock.uptimeMillis() + 4500;
            }
        });
        lines.setScrollBarStyle(View.SCROLLBARS_INSIDE_INSET);
        box.addView(lines, new LinearLayout.LayoutParams(-1, 0, 1));
        reviewFilter.setOnCheckedChangeListener((filter, checked) -> {
            updateVisibleTranscript();
            int index = reviewIndex(checked ? reviewRows : transcriptRows);
            if (index >= 0) lines.setSelection(index);
            if (filter.isShown()) StudioStyle.enter(lines, false);
        });
    }

    private View addDropdownDismiss(FrameLayout host) {
        View dismiss = new View(activity);
        dismiss.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        dismiss.setOnClickListener(view -> closeDropdown());
        dismiss.setVisibility(View.GONE);
        host.addView(dismiss, new FrameLayout.LayoutParams(-1, -1));
        return dismiss;
    }

    private void addRecordingDropdown(FrameLayout body) {
        View audioDismiss = addDropdownDismiss(body);
        recordingDropdown.setHeightLimit(() -> body.getHeight() - dp(12));
        recordingDropdown.setExpansionListener(open -> {
            int accessibility = open ? View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
                    : View.IMPORTANT_FOR_ACCESSIBILITY_AUTO;
            audioPanel.setImportantForAccessibility(accessibility);
            transcriptPanel.setImportantForAccessibility(accessibility);
            int scrim = selected == null ? 0 : 0x44000000;
            int visibility = open ? View.VISIBLE : View.GONE;
            audioDismiss.setBackgroundColor(scrim);
            audioDismiss.setVisibility(visibility);
        });
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(6);
        body.addView(recordingDropdown.list, layout);
    }

    private String libraryName(String name, File audio) {
        String recognized = Store.recordingName(activity, name);
        if (!recognized.isEmpty()) return recognized;
        try {
            JSONObject metadata = Store.readObject(new File(audio.getPath() + ".json"));
            String title = metadata.optString("title").trim();
            if (metadata.optBoolean("imported") && !title.isEmpty()) {
                return title;
            }
        } catch (Exception ignored) {
            // The recording can still be opened with its date as the title.
        }
        return "";
    }

    private List<ChoiceDropdown.Option> recordingOptions() {
        TreeMap<String, ChoiceDropdown.Option> options = new TreeMap<>(Collections.reverseOrder());
        for (File file : Store.audioFiles(activity)) {
            long seconds = Math.max(0, file.length() - 44) / (PcmWave.SAMPLE_RATE * 2);
            String name = file.getName();
            String label = libraryName(name, file);
            String date = Store.recordingTitle(name);
            options.put(name, new ChoiceDropdown.Option(name, label.isEmpty() ? date : label + " · " + date,
                    LectureReaderActivity.clock(seconds)));
        }
        for (boolean local : new boolean[]{true, false}) {
            for (File file : LectureNotes.files(activity, local)) {
                String name = file.getName().substring(0, file.getName().length() - 5);
                if (LectureNotes.valid(name) && !options.containsKey(name)) {
                    options.put(name, new ChoiceDropdown.Option(name, Store.recordingTitle(activity, name), "Только текст"));
                }
            }
        }
        return new ArrayList<>(options.values());
    }

    private void updateRecordingHint() {
        if (recordingHint == null) return;
        recordingHint.setVisibility(selected == null ? View.VISIBLE : View.GONE);
        if (selected == null) recordingHint.setText(recordingOptions().isEmpty()
                ? "Записей пока нет. Запиши пару или импортируй аудиофайл."
                : "Выбери запись, чтобы открыть аудио и текст.");
    }

    boolean closeDropdown() {
        return recordingDropdown != null && recordingDropdown.close();
    }

    private void select(String name, int initialPosition) {
        releasePlayer();
        if (scan != null) scan.cancel(true);
        selected = name;
        reviewKey = null;
        updateRecordingHint();
        noteRevision = null;
        preview = null;
        liveRows.clear();
        liveSummary = null;
        renderedSummary = null;
        position = initialPosition;
        if (analysis) setTranscriptRows(Collections.emptyList());
        duration = 0;
        File audioFile = Store.audio(activity, name);
        updateRecordingTitle();
        waveform.setEnvelope(null);
        boolean hasAudio = audioFile.isFile();
        waveform.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        play.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        times.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        play.setEnabled(false);
        if (!hasAudio) {
            showWaveStatus("");
            refreshTranscriptState();
            return;
        }
        showWaveStatus("Строю звуковую дорожку…");
        preparePlayer(name);
        scan = audioScan.submit(() -> {
            try (RandomAccessFile audio = Store.openAudio(activity, name)) {
                PcmWave.Envelope envelope = PcmWave.envelope(audio, 280);
                ui.post(() -> {
                    if (!name.equals(selected) || disposed) return;
                    if (!prepared) duration = (int) envelope.durationMillis;
                    waveform.setEnvelope(envelope);
                    showWaveStatus(envelope.peaks.length == 0 ? "Запись пуста" : "");
                    updatePosition();
                });
            } catch (IOException error) {
                if (!Thread.currentThread().isInterrupted()) ui.post(() -> {
                    if (name.equals(selected) && !disposed) showWaveStatus("Дорожка недоступна");
                });
            }
        });
        refreshTranscriptState();
        updatePosition();
    }

    private void updateRecordingTitle() {
        String name = libraryName(selected, Store.audio(activity, selected));
        String date = Store.recordingTitle(selected);
        if (analysis) analysisTitle.setText(name.isEmpty() ? date : name);
        else recordingDropdown.setSelected(new ChoiceDropdown.Option(selected, name.isEmpty() ? date : name, date));
        recordingDate.setText(date);
        recordingDate.setVisibility(name.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void preparePlayer(String name) {
        player = new MediaPlayer();
        try (RandomAccessFile audio = Store.openAudio(activity, name)) {
            player.setDataSource(audio.getFD());
            player.setOnPreparedListener(ready -> {
                if (ready != player) return;
                prepared = true;
                duration = ready.getDuration();
                play.setEnabled(duration > 0);
                if (position > 0 || playWhenReady) seek(position, playWhenReady);
                playWhenReady = false;
                updatePosition();
            });
            player.setOnCompletionListener(complete -> {
                if (complete != player) return;
                position = duration;
                updatePosition();
            });
            player.setOnErrorListener((failed, what, extra) -> {
                if (failed == player) playbackError();
                return true;
            });
            player.prepareAsync();
        } catch (IOException | RuntimeException error) {
            playbackError();
        }
    }

    private void playbackError() {
        releasePlayer();
        play.setText("Слушать");
        play.setEnabled(false);
        times.setText("Аудио недоступно");
    }

    private void togglePlayback() {
        if (!prepared) return;
        if (player.isPlaying()) {
            player.pause();
        } else if (position >= duration) {
            seek(0, true);
        } else {
            player.start();
        }
        updatePosition();
    }

    private void seek(int target, boolean start) {
        position = Math.max(0, duration > 0 ? Math.min(target, duration) : target);
        if (prepared) {
            player.seekTo(position, MediaPlayer.SEEK_CLOSEST);
            if (start && visible) player.start();
        } else {
            playWhenReady |= start;
        }
        updatePosition();
        syncPlayback(true);
    }

    private void refreshPlayback() {
        if (prepared && player.isPlaying()) position = player.getCurrentPosition();
        if (selected != null) updatePosition();
        if (visible) ui.postDelayed(playbackTick, 120);
    }

    private void updatePosition() {
        if (player != null) {
            String elapsed = LectureReaderActivity.clock(position / 1000.0) + " / "
                    + LectureReaderActivity.clock(duration / 1000.0);
            if (!TextUtils.equals(times.getText(), elapsed)) times.setText(elapsed);
            String action = prepared && player.isPlaying() ? "Пауза" : "Слушать";
            if (!TextUtils.equals(play.getText(), action)) play.setText(action);
        }
        waveform.invalidate();
        syncPlayback(false);
    }

    private void syncPlayback(boolean seek) {
        if (!analysis || transcript == null || showingSummary || player == null || preview != null && !seek && !prepared) return;
        int match = -1;
        double seconds = position / 1000.0;
        for (int i = 0; i < transcript.getCount(); i++) {
            TranscriptEdits.Line row = transcript.getItem(i);
            if (Double.isFinite(row.start) && row.start <= seconds && (Double.isNaN(row.end) || row.end >= seconds))
                match = i;
        }
        String key = match < 0 ? null : transcript.getItem(match).key;
        boolean changed = !java.util.Objects.equals(playingKey, key);
        if (changed) {
            playingKey = key;
            transcript.notifyDataSetChanged();
        }
        if (match >= 0 && (seek || changed && prepared && player.isPlaying()
                && android.os.SystemClock.uptimeMillis() >= manualScrollUntil)
                && (match < transcriptList.getFirstVisiblePosition() || match > transcriptList.getLastVisiblePosition())) {
            transcriptList.setSelectionFromTop(match, dp(6));
        }
    }

    private void showWaveStatus(String status) {
        waveStatus.setText(status);
        waveStatus.setVisibility(status.isEmpty() ? View.GONE : View.VISIBLE);
        waveStatus.setVisibility(status.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void refreshTranscript() {
        if (!analysis) {
            String importMessage = AudioImport.status;
            if (!TextUtils.equals(importStatus.getText(), importMessage)) {
                importStatus.setText(importMessage);
                if (!AudioImport.busy) updateRecordingHint();
            }
            importStatus.setVisibility(importMessage.isEmpty() ? View.GONE : View.VISIBLE);
            importButton.setEnabled(!AudioImport.busy);
        }
        if (selected != null) refreshTranscriptState();
        if (visible) ui.postDelayed(transcriptTick, 700);
    }

    private void refreshTranscriptState() {
        File local = LectureNotes.file(activity, selected, true);
        File mac = LectureNotes.file(activity, selected, false);
        File edits = TranscriptEdits.file(activity, selected);
        String revision = TranscriptEdits.stamp(local) + "/" + TranscriptEdits.stamp(mac)
                + "/" + TranscriptEdits.stamp(edits) + "/" + TranscriptEdits.stamp(Store.lessonFile(activity, selected));
        boolean savedChanged = !revision.equals(noteRevision);
        if (savedChanged) {
            JSONObject document = readNote(local);
            savedLocally = document != null;
            if (document == null) document = readNote(mac);
            savedReport = document == null ? null : document.optJSONObject("report");
            summaryReport = savedReport;
            if (analysis) {
                try {
                    savedCorrections = TranscriptEdits.read(edits);
                    if (savedReport != null && savedCorrections.length() > 0) {
                        JSONObject corrected = new JSONObject(document.toString());
                        TranscriptEdits.apply(corrected, savedCorrections, savedLocally);
                        summaryReport = corrected.getJSONObject("report");
                    }
                } catch (Exception invalid) {
                    savedCorrections = new JSONObject();
                }
            }
            updateRecordingTitle();
            if (!analysis) recordingDropdown.refreshOptions();
            noteRevision = revision;
        }

        boolean supported = android.os.Process.is64Bit();
        boolean hasAudio = Store.audio(activity, selected).isFile();
        boolean loading = PhoneAnalysisService.busyFor(selected);
        audioPanel.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        transcribe.setVisibility(savedReport != null || hasAudio ? View.VISIBLE : View.GONE);
        if (!analysis) {
            transcribe.setEnabled(savedReport != null || supported && hasAudio);
            transcribe.setText(loading ? "Открыть разбор" : "Разобрать");
            return;
        }

        AnalysisPreview live = PhoneAnalysisService.previewFor(selected);
        AnalysisPreview.Transcript stream = live == null ? null : live.transcript(preview);
        if (stream != null) {
            if (stream != preview) updateLiveRows(stream);
        } else if (preview != null || savedChanged) {
            preview = null;
            liveRows.clear();
            setTranscriptRows(readSegments(savedReport, savedLocally, savedCorrections));
        }

        String message = PhoneAnalysisService.statusFor(selected);
        String inProgress = live == null ? null : live.summary;
        boolean summarizing = inProgress != null;
        transcriptSpinner.setVisibility(loading && !summarizing ? View.VISIBLE : View.GONE);
        String speechMessage = summarizing ? "" : message;
        if (speechMessage.isEmpty() && transcriptRows.isEmpty()) {
            if (loading) speechMessage = "Ожидаю первые фразы";
            else if (!supported) speechMessage = "Для расшифровки нужна 64-битная версия Android";
            else speechMessage = "Здесь появится расшифровка записи";
        }
        setLabel(transcriptStatus, speechMessage);
        transcriptProgress.setVisibility(speechMessage.isEmpty() ? View.GONE : View.VISIBLE);
        boolean pending = savedLocally && savedReport != null && savedReport.optBoolean(LectureNotes.SUMMARY_PENDING);
        transcribe.setVisibility(supported && (hasAudio || pending || loading) ? View.VISIBLE : View.GONE);
        transcribe.setEnabled(loading || !PhoneAnalysisService.busy());
        transcribe.setText(loading ? "Отменить разбор" : pending ? "Продолжить разбор"
                : savedReport == null ? "Разобрать" : "Расшифровать заново");
        updateSummary(inProgress, message, loading, pending);
    }

    private JSONObject readNote(File file) {
        try {
            JSONObject note = Store.readObject(file);
            return note.optJSONObject("report") == null ? null : note;
        } catch (Exception invalid) {
            return null;
        }
    }

    private void updateLiveRows(AnalysisPreview.Transcript stream) {
        boolean same = preview != null && preview.stream == stream.stream;
        boolean follow = !showingSummary && !(prepared && player.isPlaying())
                && android.os.SystemClock.uptimeMillis() >= manualScrollUntil
                && (!same || transcriptList.getLastVisiblePosition() >= transcript.getCount() - 2);
        if (!same) {
            liveRows.clear();
            animatedThrough = -1;
        }
        JSONObject noEdits = new JSONObject();
        for (int i = liveRows.size(); i < stream.rows.size(); i++) {
            try {
                liveRows.add(new TranscriptEdits.Line(new JSONObject(stream.rows.get(i)), i, true, noEdits));
            } catch (Exception malformed) {
                break;
            }
        }
        preview = stream;
        setTranscriptRows(liveRows);
        if (follow && transcript.getCount() > 0) transcriptList.smoothScrollToPositionFromTop(transcript.getCount() - 1, 0, 140);
    }

    private void updateSummary(String inProgress, String message, boolean loading, boolean pending) {
        if (inProgress != null && !inProgress.equals(liveSummary)) {
            liveSummary = inProgress;
            try { renderSummary(new JSONObject(inProgress)); }
            catch (org.json.JSONException invalid) { renderSummary(null); }
        } else if (inProgress == null) {
            liveSummary = null;
            Object source = preview == null ? summaryReport : null;
            if (source != renderedSummary) renderSummary((JSONObject)source);
        }
        String label;
        if (inProgress != null) label = message;
        else if (pending && !loading) label = message.isEmpty() ? "Конспект ожидает продолжения" : message;
        else if (summaryText.length() > 0) label = "";
        else label = "Конспект появится после расшифровки";
        setLabel(summaryStatus, label);
        openReader.setVisibility(savedReport != null && !pending && preview == null ? View.VISIBLE : View.GONE);
        summaryTab.setContentDescription(inProgress == null ? "Конспект" : "Конспект формируется");
    }

    private void renderSummary(JSONObject report) {
        renderedSummary = report;
        StringBuilder text = new StringBuilder();
        String overview = report == null ? "" : report.optString("overview");
        if (!overview.isEmpty()) text.append(overview).append("\n\n");
        JSONArray points = report == null ? null : report.optJSONArray("summary");
        JSONArray homework = report == null ? null : report.optJSONArray("homework");
        if (points != null) for (int i = 0; i < points.length(); i++) {
            String line = points.optString(i);
            if (!line.isEmpty()) text.append("• ").append(line).append("\n\n");
        }
        if (homework != null && homework.length() > 0) {
            text.append("Задания из записи\n\n");
            for (int i = 0; i < homework.length(); i++) {
                JSONObject assignment = homework.optJSONObject(i);
                if (assignment != null) text.append("• ").append(assignment.optString("task")).append("\n\n");
            }
        }
        setLabel(summaryText, text.toString().trim());
    }

    private void setLabel(TextView label, String value) {
        if (!TextUtils.equals(label.getText(), value)) label.setText(value);
        label.setVisibility(value.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void setTranscriptRows(List<TranscriptEdits.Line> rows) {
        transcriptRows = rows;
        reviewRows = new ArrayList<>();
        for (TranscriptEdits.Line row : rows) {
            if (row.needsReview) reviewRows.add(row);
        }
        reviewFilter.setVisibility(reviewRows.isEmpty() ? View.GONE : View.VISIBLE);
        if (reviewRows.isEmpty()) reviewFilter.setChecked(false);
        if (reviewIndex(reviewRows) < 0) reviewKey = null;
        updateVisibleTranscript();
    }

    private void updateVisibleTranscript() {
        boolean filtered = reviewFilter.isChecked();
        transcript.replace(filtered ? reviewRows : transcriptRows);
        reviewFilter.setText(filtered ? "Только сомнительные (" + reviewRows.size() + ") · снять для полного текста"
                : "Показать сомнительные (" + reviewRows.size() + ")");
        nextReview.setVisibility(filtered && !reviewRows.isEmpty() ? View.VISIBLE : View.GONE);
        updateNextReview();
    }

    private int reviewIndex(List<TranscriptEdits.Line> rows) {
        if (reviewKey == null) return -1;
        for (int i = 0; i < rows.size(); i++) {
            if (reviewKey.equals(rows.get(i).key)) return i;
        }
        return -1;
    }

    private void updateNextReview() {
        int current = reviewIndex(reviewRows);
        nextReview.setEnabled(current < reviewRows.size() - 1);
        nextReview.setText(current < 0 ? "К первой сомнительной фразе"
                : current == reviewRows.size() - 1 ? "Последняя сомнительная фраза"
                : "К следующей фразе · " + (current + 2) + " из " + reviewRows.size());
    }

    private void nextReviewFragment() {
        int next = reviewIndex(reviewRows) + 1;
        if (next >= reviewRows.size()) return;
        reviewKey = reviewRows.get(next).key;
        transcript.notifyDataSetChanged();
        transcriptList.setSelectionFromTop(next, 0);
        updateNextReview();
        transcriptList.announceForAccessibility("Фрагмент " + (next + 1) + " из " + reviewRows.size());
    }

    private List<TranscriptEdits.Line> readSegments(JSONObject report, boolean local, JSONObject corrections) {
        List<TranscriptEdits.Line> rows = new ArrayList<>();
        JSONArray segments = report == null ? null : report.optJSONArray("segments");
        if (segments != null) for (int i = 0; i < segments.length(); i++) {
            JSONObject part = segments.optJSONObject(i);
            if (part != null && !part.optString("text").isEmpty())
                rows.add(new TranscriptEdits.Line(part, i, local, corrections));
        }
        return rows;
    }

    private void editWord(TranscriptEdits.Line line, int index) {
        if (wordEditor != null || selected == null) return;
        String recording = selected;
        TranscriptEdits.Word word = line.words.get(index);
        Dialog editor = new Dialog(activity);
        wordEditor = editor;
        editor.requestWindowFeature(Window.FEATURE_NO_TITLE);
        editor.setOnDismissListener(dialog -> wordEditor = null);
        LinearLayout sheet = card();
        sheet.setPadding(dp(16), dp(16), dp(16), dp(18));
        TextView title = text("Исправить слово", 19, TEXT);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        sheet.addView(title);
        if (!word.original.equals(word.value)) {
            sheet.addView(text("Исходное: " + word.original, 14, MUTED), spaced(-1, -2, 6));
        }

        EditText replacement = new EditText(activity);
        replacement.setContentDescription("Исправление");
        replacement.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        replacement.setImeOptions(EditorInfo.IME_ACTION_DONE);
        replacement.setFilters(new InputFilter[]{new InputFilter.LengthFilter(TranscriptEdits.MAX_REPLACEMENT)});
        replacement.setSingleLine();
        replacement.setTextColor(TEXT);
        replacement.setTextSize(18);
        replacement.setPadding(dp(12), dp(6), dp(12), dp(6));
        replacement.setBackground(surface(StudioStyle.CONTROL, 10));
        replacement.setText(word.value);
        replacement.setSelectAllOnFocus(true);
        sheet.addView(replacement, spaced(-1, dp(50), 12));

        int audioStart = word.audioStartMillis >= 0 ? (int) word.audioStartMillis
                : Double.isFinite(line.start) && line.start >= 0 ? (int) (line.start * 1000) : -1;
        if (audioStart >= 0 && Store.audio(activity, recording).isFile()) {
            String time = LectureReaderActivity.clock(audioStart / 1000.0);
            String label = word.audioStartMillis >= 0 ? "Слушать с " : "Слушать фразу с ";
            Button listen = button(label + time, () -> {
                if (recording.equals(selected) && player != null) seek(audioStart, true);
            });
            sheet.addView(listen, spaced(-1, dp(48), 8));
        }

        if (!word.original.equals(word.value)) {
            sheet.addView(button("Вернуть исходное", () ->
                    saveWord(editor, recording, line, index, word.original)), spaced(-1, dp(48), 6));
        }

        LinearLayout actions = new LinearLayout(activity);
        Button cancel = button("Отмена", editor::dismiss);
        actions.addView(cancel, new LinearLayout.LayoutParams(0, dp(48), 1));
        Runnable commit = () -> {
            String value = replacement.getText().toString().trim();
            if (value.isEmpty()) replacement.setError("Введи слово или короткую фразу");
            else saveWord(editor, recording, line, index, value);
        };
        Button save = button("Сохранить", commit);
        save.setTextColor(StudioStyle.INK);
        save.setBackground(StudioStyle.control(activity, ACCENT, 12));
        LinearLayout.LayoutParams saveLayout = new LinearLayout.LayoutParams(0, dp(48), 1);
        saveLayout.leftMargin = dp(8);
        actions.addView(save, saveLayout);
        sheet.addView(actions, spaced(-1, -2, 12));
        replacement.setOnEditorActionListener((input, action, event) -> {
            if (action != EditorInfo.IME_ACTION_DONE) return false;
            commit.run();
            return true;
        });

        editor.setContentView(sheet);
        Window window = editor.getWindow();
        window.setBackgroundDrawableResource(android.R.color.transparent);
        window.setGravity(Gravity.BOTTOM);
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
                | WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
        replacement.requestFocus();
        editor.show();
        window.setLayout(-1, -2);
    }

    private void saveWord(Dialog editor, String recording, TranscriptEdits.Line line, int index, String value) {
        try {
            TranscriptEdits.save(activity, recording, line, index, value);
            editor.dismiss();
            if (recording.equals(selected)) {
                noteRevision = null;
                refreshTranscriptState();
            }
        } catch (Exception error) {
            Toast.makeText(activity, "Не удалось сохранить правку", Toast.LENGTH_SHORT).show();
        }
    }

    private void releasePlayer() {
        prepared = false;
        playWhenReady = false;
        if (player != null) player.release();
        player = null;
    }

    void setActive(boolean active) {
        if (active == visible) return;
        visible = active;
        if (active) {
            updateRecordingHint();
            refreshPlayback();
            refreshTranscript();
            return;
        }
        closeDropdown();
        if (wordEditor != null) wordEditor.dismiss();
        playWhenReady = false;
        if (prepared && player.isPlaying()) {
            position = player.getCurrentPosition();
            player.pause();
            updatePosition();
        }
        ui.removeCallbacks(playbackTick);
        ui.removeCallbacks(transcriptTick);
    }

    Bundle snapshot() {
        Bundle state = new Bundle();
        state.putString("recording", selected);
        state.putInt("position", position);
        state.putBoolean("show_summary", showingSummary);
        state.putBoolean("reviewOnly", analysis && reviewFilter.isChecked());
        state.putString("review_key", reviewKey);
        return state;
    }

    void dispose() {
        setActive(false);
        disposed = true;
        if (scan != null) scan.cancel(true);
        audioScan.shutdownNow();
        releasePlayer();
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private LinearLayout column() {
        LinearLayout view = new LinearLayout(activity);
        view.setOrientation(LinearLayout.VERTICAL);
        return view;
    }

    private LinearLayout card() {
        LinearLayout view = column();
        view.setBackground(StudioStyle.card(activity, 20));
        view.setPadding(dp(12), dp(12), dp(12), dp(12));
        return view;
    }

    private LinearLayout.LayoutParams spaced(int width, int height, int gap) {
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(width, height);
        params.topMargin = dp(gap);
        return params;
    }

    private GradientDrawable surface(int color, int radius) {
        GradientDrawable surface = new GradientDrawable();
        surface.setColor(color);
        surface.setCornerRadius(dp(radius));
        return surface;
    }

    private Button button(String value, Runnable action) {
        Button button = new Button(activity);
        button.setText(value);
        button.setTextSize(15);
        button.setAllCaps(false);
        button.setTextColor(TEXT);
        button.setPadding(dp(12), 0, dp(12), 0);
        button.setBackground(StudioStyle.control(activity, StudioStyle.CONTROL, 12));
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(activity);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private final class TranscriptAdapter extends ArrayAdapter<TranscriptEdits.Line> {
        TranscriptAdapter(Context context) {
            super(context, 0);
        }

        void replace(List<TranscriptEdits.Line> rows) {
            setNotifyOnChange(false);
            clear();
            addAll(rows);
            notifyDataSetChanged();
        }

        @Override public View getView(int index, View reusable, ViewGroup parent) {
            TranscriptRow row = reusable == null ? new TranscriptRow() : (TranscriptRow) reusable;
            TranscriptEdits.Line line = getItem(index);
            boolean timed = Double.isFinite(line.start);
            boolean playing = line.key.equals(playingKey);
            row.bubble.setBackground(surface(playing || line.key.equals(reviewKey)
                    ? StudioStyle.ACTIVE : StudioStyle.CONTROL, 15));
            row.time.setVisibility(timed ? View.VISIBLE : View.GONE);
            row.review.setVisibility(line.needsReview ? View.VISIBLE : View.GONE);
            row.time.setTextColor(line.needsReview ? StudioStyle.WARNING : ACCENT);
            if (timed) {
                String time = LectureReaderActivity.clock(line.start);
                String end = Double.isFinite(line.end) ? " – " + LectureReaderActivity.clock(line.end) : "";
                row.time.setText(time + end);
                row.time.setContentDescription((line.needsReview ? "Сомнительная фраза. " : "") + "Слушать с " + time);
                row.time.setOnClickListener(view -> {
                    if (reviewFilter.isChecked()) {
                        reviewKey = line.key;
                        notifyDataSetChanged();
                        updateNextReview();
                    }
                    seek((int) (Math.max(0, line.start) * 1000), true);
                });
            }
            SpannableStringBuilder display = new SpannableStringBuilder();
            int offset = 0;
            String recording = selected;
            for (int i = 0; i < line.words.size(); i++) {
                final int wordIndex = i;
                TranscriptEdits.Word word = line.words.get(i);
                display.append(line.original, offset, word.start);
                int from = display.length();
                display.append(word.value);
                display.setSpan(new ClickableSpan() {
                    @Override public void onClick(View widget) {
                        if (!recording.equals(selected) || preview != null) return;
                        if (reviewFilter.isChecked()) {
                            reviewKey = line.key;
                            notifyDataSetChanged();
                            updateNextReview();
                        }
                        editWord(line, wordIndex);
                    }

                    @Override public void updateDrawState(TextPaint paint) {
                        paint.setColor(word.original.equals(word.value) ? TEXT : ACCENT);
                        paint.setUnderlineText(false);
                    }
                }, from, display.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                offset = word.end;
            }
            display.append(line.original, offset, line.original.length());
            row.words.setText(display);
            if (preview != null && index > animatedThrough) {
                animatedThrough = index;
                StudioStyle.enter(row, false);
            }
            return row;
        }
    }

    private final class TranscriptRow extends LinearLayout {
        final LinearLayout bubble = column();
        final Button time = button("", () -> {});
        final TextView words = text("", 16, TEXT);
        final TextView review = text("Проверить", 10, StudioStyle.WARNING);

        TranscriptRow() {
            super(activity);
            setLayoutParams(new android.widget.AbsListView.LayoutParams(-1, -2));
            setOrientation(VERTICAL);
            setPadding(0, dp(3), 0, dp(4));
            bubble.setPadding(dp(11), dp(5), dp(11), dp(10));
            addView(bubble, new LinearLayout.LayoutParams(-1, -2));
            LinearLayout stamp = new LinearLayout(activity);
            stamp.setGravity(Gravity.CENTER_VERTICAL);
            time.setTextSize(12);
            time.setTextColor(ACCENT);
            time.setTypeface(Typeface.MONOSPACE);
            time.setBackground(StudioStyle.control(activity, Color.TRANSPARENT, 12));
            time.setPadding(0, 0, dp(8), 0);
            time.setMinHeight(0);
            time.setMinimumHeight(0);
            stamp.addView(time, new LinearLayout.LayoutParams(-2, dp(36)));
            review.setPadding(dp(8), 0, 0, 0);
            stamp.addView(review);
            bubble.addView(stamp);
            words.setLineSpacing(dp(3), 1);
            words.setMovementMethod(LinkMovementMethod.getInstance());
            words.setHighlightColor(0x55c5b5ff);
            bubble.addView(words, new LinearLayout.LayoutParams(-1, -2));
        }
    }

    private final class Waveform extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private PcmWave.Envelope envelope;
        private Shader spectrum;

        Waveform(Context context) {
            super(context);
            setBackground(surface(BACKGROUND, 14));
            setContentDescription("Звуковая дорожка");
            setFocusable(true);
            setClickable(true);
        }

        void setEnvelope(PcmWave.Envelope value) {
            envelope = value;
            invalidate();
        }

        @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
            super.onSizeChanged(width, height, oldWidth, oldHeight);
            spectrum = new LinearGradient(0, 0, Math.max(1, width), 0,
                    StudioStyle.SPECTRUM, null, Shader.TileMode.CLAMP);
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float left = dp(8);
            float width = getWidth() - 2 * left;
            float midpoint = getHeight() / 2f;
            if (width <= 0) return;

            paint.setColor(StudioStyle.LINE);
            paint.setStrokeWidth(dp(1));
            for (int index = 1; index < 8; index++) {
                float x = left + index * width / 8;
                canvas.drawLine(x, dp(6), x, getHeight() - dp(6), paint);
            }
            canvas.drawLine(left, midpoint, left + width, midpoint, paint);
            if (envelope == null || envelope.peaks.length == 0) return;

            float progress = duration == 0 ? 0 : Math.max(0, Math.min(1, (float) position / duration));
            float marker = left + progress * width;
            float step = width / envelope.peaks.length;
            paint.setStrokeWidth(Math.max(1f, step * 0.66f));
            for (int i = 0; i < envelope.peaks.length; i++) {
                float x = left + (i + .5f) * step;
                float peak = envelope.peaks[i];
                float height = Math.max(.5f, peak * (midpoint - dp(7)));
                boolean played = x <= marker;
                paint.setColor(played ? StudioStyle.TEXT : peak > .6f ? 0xffaaa0cf : 0xff77728e);
                paint.setShader(played ? spectrum : null);
                canvas.drawLine(x, midpoint - height, x, midpoint + height, paint);
            }
            paint.setShader(null);
            paint.setStrokeWidth(dp(1));
            paint.setColor(ACCENT);
            canvas.drawLine(marker, dp(5), marker, getHeight() - dp(5), paint);
            canvas.drawCircle(marker, midpoint, dp(3), paint);
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            float width = getWidth() - 2 * dp(8);
            if (duration <= 0 || width <= 0) return false;
            switch (event.getActionMasked()) {
                case MotionEvent.ACTION_DOWN:
                case MotionEvent.ACTION_MOVE:
                case MotionEvent.ACTION_UP:
                    float fraction = Math.max(0, Math.min(1, (event.getX() - dp(8)) / width));
                    seek(Math.round(fraction * duration), false);
                    if (event.getActionMasked() == MotionEvent.ACTION_UP) performClick();
                    return true;
                default:
                    return super.onTouchEvent(event);
            }
        }

        @Override public boolean performClick() {
            super.performClick();
            return true;
        }

        @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
            super.onInitializeAccessibilityNodeInfo(info);
            if (duration > 0) {
                info.setClassName("android.widget.SeekBar");
                info.setRangeInfo(AccessibilityNodeInfo.RangeInfo.obtain(
                        AccessibilityNodeInfo.RangeInfo.RANGE_TYPE_INT, 0, duration / 1000f, position / 1000f));
                info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS);
            }
        }

        @Override public boolean performAccessibilityAction(int action, Bundle arguments) {
            if (action == AccessibilityNodeInfo.AccessibilityAction.ACTION_SET_PROGRESS.getId()
                    && arguments != null && duration > 0) {
                seek(Math.round(1000 * arguments.getFloat(AccessibilityNodeInfo.ACTION_ARGUMENT_PROGRESS_VALUE)), false);
                return true;
            }
            return super.performAccessibilityAction(action, arguments);
        }
    }
}
