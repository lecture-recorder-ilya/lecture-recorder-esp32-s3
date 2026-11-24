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
import android.media.PlaybackParams;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
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
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.ScrollView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.PopupMenu;
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
import java.util.function.BiConsumer;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

final class AudioTranscriptPage extends LinearLayout {
    private static final int BACKGROUND = StudioStyle.BACKGROUND;
    private static final int TEXT = StudioStyle.TEXT;
    private static final int MUTED = StudioStyle.MUTED;
    private static final int ACCENT = StudioStyle.ACCENT;

    private final Activity activity;
    private final ListeningLibrary library;
    private int lastSavedPosition;
    private final ForegroundAudio focus;
    private final BiConsumer<String, RecordingExport.Kind> export;
    private final boolean landscape;
    private final boolean largeText;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private final ExecutorService audioScan = Executors.newSingleThreadExecutor();
    private final Runnable playbackTick = this::refreshPlayback;
    private final Runnable repeatTick = this::repeatPhrase;
    private final Runnable transcriptTick = this::refreshTranscript;
    private Future<?> scan;
    private MediaPlayer player;
    private boolean prepared, audioAvailable;
    private boolean playWhenReady;
    private boolean visible;
    private boolean disposed;
    private int position;
    private int duration;
    private long nextPlaybackCheckpoint;
    private int phraseStart = -1, phraseEnd = -1;
    private boolean repeating, seeking;
    private float speed = 1f;
    private int speedIndex = 1;
    private String selected;
    private String lastExportFile;
    private RecordingExport.Kind lastExportKind;
    private String noteRevision;
    private boolean localSummaryPending;
    private Button play;
    private Button backTen;
    private Button aheadTen;
    private LinearLayout playbackControls;
    private Button transcribe;
    private Boolean primaryTranscribe;
    private boolean modelRequestStopping;
    private Button summary;
    private final TextView recordingTitle;
    private final Button playbackOptions;
    private final TextView recordingHint;
    private TextView times;
    private TextView waveStatus;
    private TextView transcriptStatus;
    private TextView phrasePreview;
    private List<PhoneAnalysisService.Phrase> previewRows = Collections.emptyList();
    private Dialog wordEditor;
    private final LinearLayout audioPanel;
    private final LinearLayout transcriptPanel;
    private ProgressBar transcriptSpinner;
    private TranscriptAdapter transcript;
    private CheckBox reviewFilter;
    private ListView transcriptList;
    private LinearLayout reviewNavigation;
    private Button previousReview;
    private Button nextReview;
    private TextView reviewPosition;
    private String reviewKey;
    private List<TranscriptEdits.Line> transcriptRows = Collections.emptyList();
    private List<TranscriptEdits.Line> reviewRows = Collections.emptyList();
    private Waveform waveform;

    AudioTranscriptPage(Activity activity, Bundle state, Runnable openLibraryPage, BiConsumer<String, RecordingExport.Kind> export) {
        super(activity);
        this.activity = activity;
        focus = new ForegroundAudio(activity, this::pausePlayback);
        this.export = export;
        library = new ListeningLibrary(activity);
        speedIndex = library.speed();
        speed = ListeningLibrary.SPEEDS[speedIndex];
        setOrientation(VERTICAL);
        setBackgroundColor(BACKGROUND);
        int inset = dp(StudioStyle.PAGE_INSET);
        setPadding(inset, dp(12), inset, dp(8));
        landscape = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        largeText = getResources().getConfiguration().fontScale >= 1.6f;


        LinearLayout playback = this;
        LinearLayout columns = null;
        if (landscape) {
            columns = new LinearLayout(activity);
            addView(columns, new LinearLayout.LayoutParams(-1, 0, 1));
            ScrollView playerScroll = new ScrollView(activity);
            playerScroll.setFillViewport(false);
            playback = column();
            playerScroll.addView(playback, new ScrollView.LayoutParams(-1, -2));
            columns.addView(playerScroll, new LinearLayout.LayoutParams(0, -1, 10));
        }

        Button openLibrary = button("‹  Библиотека", openLibraryPage);
        openLibrary.setTextColor(ACCENT);
        openLibrary.setBackground(StudioStyle.control(activity, Color.TRANSPARENT, 10));
        openLibrary.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        openLibrary.setPadding(dp(4), 0, dp(10), 0);
        openLibrary.setContentDescription("Вернуться в библиотеку");
        playback.addView(openLibrary, new LinearLayout.LayoutParams(-2, dp(48)));
        recordingTitle = StudioStyle.title(activity, "");
        recordingTitle.setTextSize(landscape ? 21 : 25);
        recordingTitle.setMaxLines(landscape || largeText ? 1 : 2);
        recordingTitle.setEllipsize(TextUtils.TruncateAt.END);
        recordingTitle.setVisibility(View.GONE);
        LinearLayout titleBar = new LinearLayout(activity);
        titleBar.setGravity(Gravity.CENTER_VERTICAL);
        titleBar.addView(recordingTitle, new LinearLayout.LayoutParams(0, -2, 1));
        playbackOptions = button("1×", this::showPlaybackOptions);
        StudioStyle.fitLabel(playbackOptions, 10, 13);
        playbackOptions.setPadding(0, 0, 0, 0);
        playbackOptions.setVisibility(View.GONE);
        titleBar.addView(playbackOptions, new LinearLayout.LayoutParams(dp(48), dp(48)));
        playback.addView(titleBar);
        updatePlaybackOptions();

        recordingHint = text("Выбери запись в библиотеке.", 15, MUTED);
        playback.addView(recordingHint, spaced(-1, -2, 12));

        audioPanel = card();
        audioPanel.setVisibility(View.GONE);
        playback.addView(audioPanel, spaced(-1, -2, 6));
        addAudioPanel(audioPanel);

        transcriptPanel = card();
        transcriptPanel.setVisibility(View.GONE);
        if (landscape) {
            LinearLayout.LayoutParams panel = new LinearLayout.LayoutParams(0, -1, 13);
            panel.setMarginStart(dp(8));
            columns.addView(transcriptPanel, panel);
        } else {
            transcriptPanel.setMinimumHeight(dp(128));
            addView(transcriptPanel, spaced(-1, 0, 8));
            LinearLayout.LayoutParams params = (LinearLayout.LayoutParams) transcriptPanel.getLayoutParams();
            params.weight = 1;
        }
        addTranscriptPanel(transcriptPanel);

        if (state != null) {
            lastExportFile = state.getString("last_export_file");
            String exportKind = state.getString("last_export_kind");
            if (exportKind != null) lastExportKind = RecordingExport.Kind.valueOf(exportKind);
            String name = state.getString("recording");
            if (LectureNotes.valid(name)) {
                select(name, state.getInt("position", -1));
                if (!reviewRows.isEmpty()) {
                    reviewKey = state.getString("review_key");
                    reviewFilter.setChecked(state.getBoolean("reviewOnly"));
                }
            }
        }
    }

    private void addAudioPanel(LinearLayout audio) {
        waveform = new Waveform(activity);
        audio.addView(waveform, new LinearLayout.LayoutParams(-1, dp(landscape || getResources().getConfiguration().fontScale > 1.25f ? 48 : 64)));
        waveStatus = text("", 13, MUTED);
        waveStatus.setVisibility(View.GONE);
        audio.addView(waveStatus);

        playbackControls = new LinearLayout(activity);
        playbackControls.setGravity(Gravity.CENTER_VERTICAL);
        playbackControls.setShowDividers(LinearLayout.SHOW_DIVIDER_MIDDLE);
        GradientDrawable gap = StudioStyle.surface(activity, Color.TRANSPARENT, 0);
        gap.setSize(dp(6), 1);
        playbackControls.setDividerDrawable(gap);
        backTen = skipButton("−10", "На 10 секунд назад", -10000);
        aheadTen = skipButton("+10", "На 10 секунд вперёд", 10000);
        play = button("Слушать", this::togglePlayback);
        StudioStyle.actionTone(play, ACCENT, StudioStyle.INK);
        StudioStyle.fitLabel(play, landscape && largeText ? 7 : 11, 15);
        play.setPadding(dp(2), 0, dp(2), 0);
        playbackControls.addView(backTen, new LinearLayout.LayoutParams(dp(48), dp(48)));
        playbackControls.addView(play, new LinearLayout.LayoutParams(0, dp(48), 1));
        playbackControls.addView(aheadTen, new LinearLayout.LayoutParams(dp(48), dp(48)));
        audio.addView(playbackControls, spaced(-1, dp(48), 4));

        LinearLayout info = new LinearLayout(activity);
        info.setGravity(Gravity.CENTER_VERTICAL);
        times = text("", 13, MUTED);
        times.setTypeface(Typeface.MONOSPACE);
        times.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);
        StudioStyle.fitLabel(times, 8, 13);
        times.setMinHeight(dp(30));
        info.addView(times, new LinearLayout.LayoutParams(0, -2, 1));
        if (!landscape && !largeText) addSummaryButton(info);
        audio.addView(info, spaced(-1, -2, 4));
        if (landscape || largeText) {
            addTranscribeButton(audio, spaced(-1, dp(48), 8));
        }
    }

    private Button skipButton(String label, String description, int millis) {
        Button control = button(label, () -> {
            if (!prepared) return;
            seek(position + millis, false);
        });
        control.setContentDescription(description);
        control.setPadding(0, 0, 0, 0);
        StudioStyle.fitLabel(control, 10, 15);
        control.setMinWidth(0);
        control.setMinimumWidth(0);
        return control;
    }

    private void addSummaryButton(LinearLayout host) {
        summary = button("Конспект", this::openSummary);
        StudioStyle.fitLabel(summary, 11, 15);
        summary.setVisibility(View.GONE);
        LinearLayout.LayoutParams action = new LinearLayout.LayoutParams(-2, dp(48));
        action.setMarginStart(dp(8));
        host.addView(summary, action);
    }

    private void openSummary() {
        if (selected == null) return;
        boolean local = LectureNotes.file(activity, selected, true).isFile();
        if (!local && !LectureNotes.file(activity, selected, false).isFile()) return;
        activity.startActivity(new Intent(activity, LectureReaderActivity.class)
                .putExtra("file", selected + ".json").putExtra("local", local).putExtra("tab", "summary"));
    }

    private void addTranscribeButton(LinearLayout host, LinearLayout.LayoutParams layout) {
        transcribe = button("Разобрать запись", () -> {
            if (selected != null && PhoneAnalysisService.busyFor(selected)) {
                if (!modelRequestStopping) {
                    modelRequestStopping = true;
                    refreshPhrasePreview();
                    transcribe.setEnabled(false);
                    activity.startService(PhoneAnalysisService.cancel(activity));
                }
            } else if (selected != null) {
                refreshTranscriptState();
                String title = Store.recordingTitle(activity, selected);
                if (localSummaryPending) PhoneAnalysisService.requestSummary(activity, selected, title);
                else if (Store.audio(activity, selected).isFile()) PhoneAnalysisService.request(activity, selected, title, true);
            }
        });
        StudioStyle.fitLabel(transcribe, 11, 15);
        host.addView(transcribe, layout);
    }

    void openRecording(String name) {
        if (LectureNotes.valid(name) && !name.equals(selected)) select(name, -1);
    }

    private void addTranscriptStatus(LinearLayout host) {
        transcriptStatus = text("", 14, MUTED);
        transcriptStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        host.addView(transcriptStatus, spaced(-1, -2, 4));
    }

    private void addTranscriptPanel(LinearLayout box) {
        LinearLayout header = new LinearLayout(activity);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView heading = text("Текст", 18, TEXT);
        heading.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(heading, new LinearLayout.LayoutParams(0, -2, 1));
        transcriptSpinner = new ProgressBar(activity);
        transcriptSpinner.setIndeterminateTintList(ColorStateList.valueOf(ACCENT));
        transcriptSpinner.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        transcriptSpinner.setVisibility(View.GONE);
        header.addView(transcriptSpinner, new LinearLayout.LayoutParams(dp(22), dp(22)));
        box.addView(header);

        if (landscape || largeText) addSummaryButton(header);
        addTranscriptStatus(box);
        if (!landscape && !largeText) addTranscribeButton(box, spaced(-1, dp(48), 8));
        phrasePreview = text("", 14, TEXT);
        phrasePreview.setLines(5);
        phrasePreview.setEllipsize(TextUtils.TruncateAt.END);
        phrasePreview.setVisibility(View.GONE);
        box.addView(phrasePreview, spaced(-1, -2, 6));

        reviewFilter = new CheckBox(activity);
        reviewFilter.setTextColor(TEXT);
        reviewFilter.setButtonTintList(ColorStateList.valueOf(ACCENT));
        reviewFilter.setMinHeight(dp(48));
        reviewFilter.setVisibility(View.GONE);
        box.addView(reviewFilter, spaced(-1, -2, 4));

        reviewNavigation = new LinearLayout(activity);
        reviewNavigation.setGravity(Gravity.CENTER_VERTICAL);
        reviewNavigation.setVisibility(View.GONE);
        previousReview = button("Назад", () -> moveReview(-1));
        StudioStyle.fitLabel(previousReview, 11, 15);
        previousReview.setPadding(dp(4), 0, dp(4), 0);
        previousReview.setContentDescription("Предыдущий сомнительный фрагмент");
        nextReview = button("Далее", () -> moveReview(1));
        StudioStyle.fitLabel(nextReview, 11, 15);
        nextReview.setPadding(dp(4), 0, dp(4), 0);
        nextReview.setContentDescription("Следующий сомнительный фрагмент");
        reviewPosition = text("", 13, MUTED);
        reviewPosition.setGravity(Gravity.CENTER);
        reviewPosition.setTypeface(Typeface.MONOSPACE);
        StudioStyle.fitLabel(reviewPosition,9,13);
        reviewPosition.setMinHeight(dp(28));
        reviewNavigation.addView(previousReview, new LinearLayout.LayoutParams(0, dp(48), 1));
        reviewNavigation.addView(reviewPosition, new LinearLayout.LayoutParams(dp(58), -2));
        reviewNavigation.addView(nextReview, new LinearLayout.LayoutParams(0, dp(48), 1));
        box.addView(reviewNavigation, spaced(-1, -2, 4));

        ListView lines = new ListView(activity);
        transcriptList = lines;
        transcript = new TranscriptAdapter(activity);
        lines.setAdapter(transcript);
        lines.setDivider(new android.graphics.drawable.ColorDrawable(StudioStyle.LINE));
        lines.setDividerHeight(dp(1));
        if (landscape) lines.setScrollbarFadingEnabled(false);
        box.addView(lines, new LinearLayout.LayoutParams(-1, 0, 1));
        reviewFilter.setOnCheckedChangeListener((filter, checked) -> {
            updateVisibleTranscript();
            int index = reviewIndex(checked ? reviewRows : transcriptRows);
            if (index >= 0) lines.setSelection(index);
            if (filter.isShown()) StudioStyle.enter(lines, false);
        });
    }

    boolean exitReview() {
        if (!reviewFilter.isChecked()) return false;
        reviewFilter.setChecked(false);
        reviewFilter.requestFocus();
        return true;
    }

    private void select(String name, int initialPosition) {
        rememberPosition();
        releasePlayer();
        if (scan != null) scan.cancel(true);
        selected = name;
        reviewKey = null;
        phraseStart = phraseEnd = -1;
        repeating = false;
        updatePlaybackOptions();
        recordingHint.setVisibility(View.GONE);
        noteRevision = null;
        modelRequestStopping = false;
        setTranscriptRows(Collections.emptyList());
        lastSavedPosition = library.position(name, 0);
        position = initialPosition >= 0 ? initialPosition : lastSavedPosition;
        duration = 0;
        File audioFile = Store.audio(activity, name);
        String title = RecordingLibraryPage.title(activity, name, audioFile);
        if ("Запись пары".equals(title)) title = Store.recordingTitle(name);
        recordingTitle.setText(title);
        recordingTitle.setTooltipText(title);
        recordingTitle.setVisibility(View.VISIBLE);
        waveform.setEnvelope(null);
        boolean hasAudio = audioAvailable = audioFile.isFile();
        transcriptPanel.setVisibility(View.VISIBLE);
        waveform.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        playbackOptions.setVisibility(View.VISIBLE);
        playbackControls.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        times.setVisibility(hasAudio ? View.VISIBLE : View.GONE);
        enablePlayback(false);
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

    private void preparePlayer(String name) {
        player = new MediaPlayer();
        player.setAudioAttributes(ForegroundAudio.SPEECH);
        try (RandomAccessFile audio = Store.openAudio(activity, name)) {
            player.setDataSource(audio.getFD());
            player.setOnPreparedListener(ready -> {
                if (ready != player) return;
                prepared = true;
                duration = ready.getDuration();
                position = ListeningLibrary.resumable(position, duration);
                lastSavedPosition = library.position(name, duration);
                enablePlayback(duration > 0);
                if (position > 0 || playWhenReady) seek(position, playWhenReady);
                playWhenReady = false;
                updatePosition();
            });
            player.setOnSeekCompleteListener(ready -> {
                if (ready != player) return;
                seeking = false;
                scheduleRepeat();
            });
            player.setOnCompletionListener(complete -> {
                if (complete != player) return;
                if (repeating && visible) {
                    seek(phraseStart, true);
                    return;
                }
                focus.release();
                position = 0;
                library.savePosition(name, 0, duration);
                lastSavedPosition = 0;
                seek(0, false);
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
        enablePlayback(false);
        times.setText("Аудио недоступно");
    }

    private void enablePlayback(boolean enabled) {
        play.setEnabled(enabled);
        backTen.setEnabled(enabled);
        aheadTen.setEnabled(enabled);

    }

    private void togglePlayback() {
        if (!prepared) return;
        if (player.isPlaying()) {
            pausePlayback();
        } else if (position >= duration) {
            seek(repeating ? phraseStart : 0, true);
        } else {
            startPlayback();
        }
        updatePosition();
    }

    private void seek(int target, boolean start) {
        position = Math.max(0, duration > 0 ? Math.min(target, duration) : target);
        if (repeating && (position < phraseStart || position >= phraseEnd)) {
            repeating = false;
            updatePlaybackOptions();
        }
        if (prepared) {
            seeking = true;
            ui.removeCallbacks(repeatTick);
            player.seekTo(position, MediaPlayer.SEEK_CLOSEST);
            if (start && visible) startPlayback();
        } else {
            playWhenReady |= start;
        }
        updatePosition();
    }

    private void updatePlaybackOptions() {
        String label = ListeningLibrary.SPEED_LABELS[speedIndex];
        playbackOptions.setText("⋯");
        playbackOptions.setContentDescription("Действия записи, скорость " + label
                + (repeating ? ", повтор фразы включён" : ""));
        playbackOptions.setSelected(repeating);
    }

    private void showPlaybackOptions() {
        PopupMenu menu = new PopupMenu(activity, playbackOptions);
        android.view.SubMenu speeds = menu.getMenu().addSubMenu("Скорость " + ListeningLibrary.SPEED_LABELS[speedIndex]);
        speeds.getItem().setEnabled(prepared);
        for (int index = 0; index < ListeningLibrary.SPEEDS.length; index++) {
            speeds.add(1, index + 1, index, ListeningLibrary.SPEED_LABELS[index]).setCheckable(true).setChecked(index == speedIndex);
        }
        speeds.setGroupCheckable(1, true, true);
        menu.getMenu().add(0, 100, 1, repeating ? "Выключить повтор фразы" : "Повторять фразу")
                .setEnabled(hasPhrase());
        File audio = Store.audio(activity, selected);
        boolean notes = LectureNotes.file(activity, selected, true).isFile()
                || LectureNotes.file(activity, selected, false).isFile();
        android.view.SubMenu exports = menu.getMenu().addSubMenu("Экспорт");
        for (RecordingExport.Kind kind : RecordingExport.Kind.values()) {
            boolean available = kind == RecordingExport.Kind.WAV ? audio.isFile() : notes;
            String label = kind == RecordingExport.Kind.WAV ? RecordingExport.audioLabel(audio) : kind.label;
            exports.add(0, 200 + kind.ordinal(), kind.ordinal(), label).setEnabled(available);
        }
        exports.getItem().setEnabled(audio.isFile() || notes);
        boolean savedText = !transcriptRows.isEmpty() && transcribe.getVisibility() == View.GONE;
        if ((localSummaryPending || savedText) && audio.isFile() && android.os.Process.is64Bit()) {
            menu.getMenu().add(0, 111, 4, "Расшифровать заново").setEnabled(!PhoneAnalysisService.busy());
        }
        if (selected.equals(lastExportFile) && lastExportKind != null) {
            menu.getMenu().add(0, 110, 3, "Повторить экспорт " + lastExportKind.format)
                    .setEnabled(lastExportKind == RecordingExport.Kind.WAV ? audio.isFile() : notes);
        }
        menu.setOnMenuItemClickListener(item -> {
            if (item.getItemId() >= 200) {
                lastExportFile = selected;
                lastExportKind = RecordingExport.Kind.values()[item.getItemId() - 200];
                export.accept(lastExportFile, lastExportKind);
            } else if (item.getItemId() == 110) {
                export.accept(lastExportFile, lastExportKind);
            } else if (item.getItemId() == 111) {
                PhoneAnalysisService.request(activity, selected, Store.recordingTitle(activity, selected), true);
            } else if (item.getItemId() == 100) {
                if (!hasPhrase()) return true;
                repeating = !repeating;
                updatePlaybackOptions();
                if (repeating) {
                    String range = LectureReaderActivity.clock(phraseStart / 1000.0) + "–"
                            + LectureReaderActivity.clock(phraseEnd / 1000.0);
                    announceForAccessibility("Повтор фразы " + range);
                    seek(phraseStart, true);
                } else ui.removeCallbacks(repeatTick);
            } else {
                if (item.getItemId() < 1 || item.getItemId() > ListeningLibrary.SPEEDS.length) return false;
                speedIndex = item.getItemId() - 1;
                library.speed(speedIndex);
                speed = ListeningLibrary.SPEEDS[speedIndex];
                if (prepared && player.isPlaying()) startPlayback();
                updatePlaybackOptions();
            }
            return true;
        });
        menu.show();
    }

    private void startPlayback() {
        if (!focus.acquire()) {
            announceForAccessibility("Аудио занято другим приложением.");
            return;
        }
        try {
            player.setPlaybackParams(new PlaybackParams().setSpeed(speed).setPitch(1f));
        } catch (IllegalArgumentException error) {
            speedIndex = ListeningLibrary.NORMAL;
            library.speed(speedIndex);
            speed = 1f;
            player.start();
            updatePlaybackOptions();
            announceForAccessibility("Скорость недоступна. Использую обычную скорость.");
        }
        scheduleRepeat();
    }

    private boolean hasPhrase() {
        return prepared && phraseStart >= 0 && phraseEnd > phraseStart;
    }

    private void selectPhrase(TranscriptEdits.Line line, boolean move) {
        if (Double.isFinite(line.start) && Double.isFinite(line.end)) {
            phraseStart = (int) Math.round(line.start * 1000);
            phraseEnd = (int) Math.min(duration, Math.round(line.end * 1000));
        } else {
            phraseStart = phraseEnd = -1;
        }
        if (!hasPhrase()) {
            repeating = false;
            updatePlaybackOptions();
        } else if (move && repeating) {
            seek(phraseStart, player.isPlaying());
        }
    }

    private void scheduleRepeat() {
        ui.removeCallbacks(repeatTick);
        if (!visible || !repeating || !hasPhrase() || seeking || !player.isPlaying()) return;
        int remaining = phraseEnd - player.getCurrentPosition();
        ui.postDelayed(repeatTick, Math.max(15, Math.round(remaining / speed)));
    }

    private void repeatPhrase() {
        if (!visible || !repeating || !hasPhrase() || seeking || !player.isPlaying()) return;
        if (player.getCurrentPosition() >= phraseEnd) seek(phraseStart, true);
        else scheduleRepeat();
    }

    private void refreshPlayback() {
        if (prepared && !seeking && player.isPlaying()) {
            position = player.getCurrentPosition();
            long now = SystemClock.elapsedRealtime();
            if (now >= nextPlaybackCheckpoint) {
                rememberPosition();
                nextPlaybackCheckpoint = now + 5000;
            }
        }
        if (selected != null) updatePosition();
        if (visible) ui.postDelayed(playbackTick, 120);
    }

    private void updatePosition() {
        if (player != null) {
            String elapsed = LectureReaderActivity.clock(position / 1000.0) + " / "
                    + LectureReaderActivity.clock(duration / 1000.0);
            if (!TextUtils.equals(times.getText(), elapsed)) times.setText(elapsed);
            String action = prepared && player.isPlaying() ? "Пауза" : "Слушать";
            if (!TextUtils.equals(play.getText(), action)) {
                play.setText(action);
                StudioStyle.changeAction(play);
            }
        }
        waveform.invalidate();
    }

    private void showWaveStatus(String status) {
        waveStatus.setText(status);
        waveStatus.setVisibility(status.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void refreshTranscript() {
        if (selected != null) refreshTranscriptState();
        if (visible) ui.postDelayed(transcriptTick, 700);
    }

    private void refreshTranscriptState() {
        File local = LectureNotes.file(activity, selected, true);
        File mac = LectureNotes.file(activity, selected, false);
        File edits = TranscriptEdits.file(activity, selected);
        String revision = TranscriptEdits.stamp(local) + "/" + TranscriptEdits.stamp(mac)
                + "/" + TranscriptEdits.stamp(edits);
        if (!revision.equals(noteRevision)) {
            JSONObject corrections;
            try {
                corrections = TranscriptEdits.read(edits);
            } catch (Exception error) {
                corrections = new JSONObject();
                Toast.makeText(activity, "Не удалось открыть правки", Toast.LENGTH_SHORT).show();
            }
            localSummaryPending = false;
            List<TranscriptEdits.Line> rows = readSegments(local, true, corrections);
            if (rows.isEmpty()) rows = readSegments(mac, false, corrections);
            setTranscriptRows(rows);
            noteRevision = revision;
        }

        boolean hasNotes = local.isFile() || mac.isFile();
        summary.setVisibility(hasNotes ? View.VISIBLE : View.GONE);
        boolean loading = PhoneAnalysisService.busyFor(selected);
        boolean supported = android.os.Process.is64Bit();
        boolean busy = PhoneAnalysisService.busy();
        boolean hasAudio = Store.audio(activity, selected).isFile();
        boolean showAction = landscape || largeText ? localSummaryPending || loading : hasNotes;
        audioPanel.setVisibility(hasAudio || showAction ? View.VISIBLE : View.GONE);
        transcriptSpinner.setVisibility(loading ? View.VISIBLE : View.GONE);
        String message = PhoneAnalysisService.statusFor(selected);
        boolean readyOffline = supported && (localSummaryPending ? PhoneModels.summaryReady(activity) : PhoneModels.ready(activity));
        if (!loading) modelRequestStopping = false;
        refreshPhrasePreview();
        boolean retry = message.startsWith("Не удалось") || message.contains("место")
                || message.contains("недоступен") || message.equals("Разбор отменён");
        if (modelRequestStopping) {
            message = "Останавливаю разбор…";
        } else if (loading) {
            if (message.startsWith("Скачиваю")) message = "Загрузка · " + message.substring(9);
            else if (message.isEmpty()) message = "Готовлю расшифровку…";
        } else if (busy) {
            message = "Жду завершения другой расшифровки";
        } else if (localSummaryPending && (message.isEmpty() || message.equals("Разбор отменён"))) {
            message = "Текст сохранён. Можно продолжить конспект.";
        } else if (message.equals("Разбор отменён")) {
            message = readyOffline ? "Разбор остановлен. Можно повторить."
                    : "Загрузка остановлена. При повторе загрузка начнётся заново.";
        } else if (message.contains("место")) {
            message = "Недостаточно места для моделей. Освободи память и повтори.";
        } else if (message.isEmpty() && transcriptRows.isEmpty()) {
            if (!supported) message = "Расшифровка появится после обработки на Mac.";
            else if (readyOffline) message = "Модели готовы. Разбор работает без сети.";
            else message = "До 570 МБ при первом запуске. После загрузки разбор работает офлайн.";
        }
        if (!TextUtils.equals(transcriptStatus.getText(), message)) transcriptStatus.setText(message);
        transcriptStatus.setTextColor(retry ? StudioStyle.WARNING : MUTED);
        transcriptStatus.setVisibility(message.isEmpty() ? View.GONE : View.VISIBLE);
        boolean showAnalysisAction = supported && (loading || localSummaryPending
                || (hasAudio && (transcriptRows.isEmpty() || retry)));
        transcribe.setVisibility(showAnalysisAction ? View.VISIBLE : View.GONE);
        boolean analysisEnabled = (!busy || loading) && !modelRequestStopping;
        transcribe.setEnabled(analysisEnabled);
        boolean primary = showAnalysisAction && analysisEnabled && transcriptRows.isEmpty() && !loading;
        if (primaryTranscribe == null || primaryTranscribe != primary) {
            primaryTranscribe = primary;
            StudioStyle.actionTone(transcribe, primary ? ACCENT : StudioStyle.CONTROL, primary ? StudioStyle.INK : TEXT);
            StudioStyle.actionTone(play, primary ? StudioStyle.CONTROL : ACCENT, primary ? TEXT : StudioStyle.INK);
        }
        String label = loading ? "Остановить" : localSummaryPending ? "Завершить конспект"
                : retry ? "Повторить разбор" : "Разобрать запись";
        if (!TextUtils.equals(transcribe.getText(), label)) transcribe.setText(label);
        if (!TextUtils.equals(transcribe.getContentDescription(), label)) transcribe.setContentDescription(label);
    }

    private void refreshPhrasePreview() {
        List<PhoneAnalysisService.Phrase> rows = modelRequestStopping ? Collections.emptyList()
                : PhoneAnalysisService.previewFor(selected);
        if (rows == previewRows) return;
        previewRows = rows;
        StringBuilder value = new StringBuilder();
        if (!rows.isEmpty()) {
            value.append("Последние готовые фразы");
            for (PhoneAnalysisService.Phrase row : rows) {
                value.append('\n').append(LectureReaderActivity.clock(row.start)).append("  ").append(row.text);
            }
        }
        phrasePreview.setText(value);
        phrasePreview.setVisibility(rows.isEmpty() ? View.GONE : View.VISIBLE);
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
        boolean showWaveform = audioAvailable && !(filtered && largeText && !landscape);
        waveform.setVisibility(showWaveform ? View.VISIBLE : View.GONE);
        transcript.replace(filtered ? reviewRows : transcriptRows);
        String filterLabel = "Сомнительные (" + reviewRows.size() + ")";
        reviewFilter.setText(filterLabel);
        reviewFilter.setContentDescription("Показать сомнительные (" + reviewRows.size() + ")");
        reviewNavigation.setVisibility(filtered && !reviewRows.isEmpty() ? View.VISIBLE : View.GONE);
        updateReviewNavigation();
    }

    private int reviewIndex(List<TranscriptEdits.Line> rows) {
        if (reviewKey == null) return -1;
        for (int i = 0; i < rows.size(); i++) {
            if (reviewKey.equals(rows.get(i).key)) return i;
        }
        return -1;
    }

    private void updateReviewNavigation() {
        int current = reviewIndex(reviewRows);
        previousReview.setEnabled(current > 0);
        nextReview.setEnabled(current < reviewRows.size() - 1);
        reviewPosition.setText(current < 0 ? String.valueOf(reviewRows.size()) : (current + 1) + " / " + reviewRows.size());
    }

    private void moveReview(int direction) {
        int next = reviewIndex(reviewRows) + direction;
        if (next < 0 || next >= reviewRows.size()) return;
        TranscriptEdits.Line line = reviewRows.get(next);
        reviewKey = line.key;
        selectPhrase(line, true);
        transcript.notifyDataSetChanged();
        if (android.animation.ValueAnimator.areAnimatorsEnabled()) transcriptList.smoothScrollToPositionFromTop(next, 0, 160);
        else transcriptList.setSelectionFromTop(next, 0);
        updateReviewNavigation();
        transcriptList.announceForAccessibility("Фрагмент " + (next + 1) + " из " + reviewRows.size());
    }

    private List<TranscriptEdits.Line> readSegments(File note, boolean local, JSONObject corrections) {
        List<TranscriptEdits.Line> rows = new ArrayList<>();
        if (!note.isFile()) return rows;
        try {
            JSONObject report = new JSONObject(Store.read(note)).getJSONObject("report");
            JSONArray segments = report.optJSONArray("segments");
            if (segments != null) for (int i = 0; i < segments.length(); i++) {
                JSONObject part = segments.optJSONObject(i);
                if (part != null && !part.optString("text").isEmpty()) {
                    rows.add(new TranscriptEdits.Line(part, i, local, corrections));
                }
            }
            if (local && !rows.isEmpty()) localSummaryPending = report.optBoolean(LectureNotes.SUMMARY_PENDING);
        } catch (Exception ignored) {
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

    private void rememberPosition() {
        if (selected == null || !prepared) return;
        if (!seeking && player.isPlaying()) position = player.getCurrentPosition();
        int saved = ListeningLibrary.resumable(position, duration);
        if (saved != lastSavedPosition) {
            library.savePosition(selected, saved, duration);
            lastSavedPosition = saved;
        }
    }

    private void pausePlayback() {
        playWhenReady = false;
        rememberPosition();
        if (prepared && player.isPlaying()) player.pause();
        focus.release();
        ui.removeCallbacks(repeatTick);
        updatePosition();
    }

    private void releasePlayer() {
        focus.release();
        ui.removeCallbacks(repeatTick);
        seeking = false;
        prepared = false;
        playWhenReady = false;
        if (player != null) player.release();
        player = null;
    }

    void setActive(boolean active) {
        if (active == visible) return;
        visible = active;
        if (active) {
            speedIndex = library.speed();
            speed = ListeningLibrary.SPEEDS[speedIndex];
            updatePlaybackOptions();
            if (selected != null) {
                int resume = library.position(selected, duration);
                if (resume != lastSavedPosition) {
                    lastSavedPosition = resume;
                    seek(resume, false);
                }
            }
            refreshPlayback();
            refreshTranscript();
            return;
        }
        if (wordEditor != null) wordEditor.dismiss();
        pausePlayback();
        ui.removeCallbacks(playbackTick);
        ui.removeCallbacks(repeatTick);
        ui.removeCallbacks(transcriptTick);
    }

    Bundle snapshot() {
        rememberPosition();
        Bundle state = new Bundle();
        state.putString("recording", selected);
        state.putInt("position", position);
        state.putBoolean("reviewOnly", reviewFilter.isChecked());
        state.putString("review_key", reviewKey);
        if (lastExportKind != null) {
            state.putString("last_export_file", lastExportFile);
            state.putString("last_export_kind", lastExportKind.name());
        }
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
        view.setBackground(StudioStyle.card(activity, StudioStyle.CARD_RADIUS));
        view.setPadding(dp(10), dp(8), dp(10), dp(8));
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
        return StudioStyle.action(activity, value, action, false);
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
            row.setBackgroundColor(line.key.equals(reviewKey) ? StudioStyle.ACTIVE : Color.TRANSPARENT);
            row.time.setVisibility(timed ? View.VISIBLE : View.GONE);
            row.time.setEnabled(audioAvailable);
            row.time.setTextColor(line.needsReview ? StudioStyle.WARNING : ACCENT);
            if (timed) {
                String time = LectureReaderActivity.clock(line.start);
                row.time.setText(time);
                row.time.setContentDescription((line.needsReview ? "Сомнительная фраза. " : "") + "Слушать с " + time);
                row.time.setOnClickListener(view -> {
                    selectPhrase(line, false);
                    if (reviewFilter.isChecked()) {
                        reviewKey = line.key;
                        notifyDataSetChanged();
                        updateReviewNavigation();
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
                        if (!recording.equals(selected)) return;
                        if (reviewFilter.isChecked()) {
                            reviewKey = line.key;
                            notifyDataSetChanged();
                            updateReviewNavigation();
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
            return row;
        }
    }

    private final class TranscriptRow extends LinearLayout {
        final Button time = button("", () -> {});
        final TextView words = text("", 16, TEXT);

        TranscriptRow() {
            super(activity);
            setLayoutParams(new android.widget.AbsListView.LayoutParams(-1, -2));
            setBaselineAligned(false);
            setGravity(Gravity.TOP);
            setPadding(0, dp(10), 0, dp(10));
            time.setTextSize(13);
            StudioStyle.fitLabel(time, 8, 13);
            time.setTextColor(ACCENT);
            time.setTypeface(Typeface.MONOSPACE);
            time.setBackground(StudioStyle.control(activity, StudioStyle.ACTIVE, 12));
            time.setPadding(dp(6), 0, dp(6), 0);
            time.setMinWidth(dp(54));
            time.setMinimumWidth(dp(54));
            LinearLayout badges = column();
            badges.addView(time, new LinearLayout.LayoutParams(-1, dp(48)));
            LinearLayout.LayoutParams badge = new LinearLayout.LayoutParams(dp(largeText ? 62 : 74), -2);
            badge.rightMargin = dp(8);
            addView(badges, badge);
            words.setLineSpacing(dp(3), 1);
            words.setMovementMethod(LinkMovementMethod.getInstance());
            words.setHighlightColor(0x557b58b4);
            addView(words, new LinearLayout.LayoutParams(0, -2, 1));
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
                paint.setColor(played ? StudioStyle.TEXT : peak > .6f ? 0xffcbb9a4 : 0xff899c9e);
                paint.setShader(played ? spectrum : null);
                canvas.drawLine(x, midpoint - height, x, midpoint + height, paint);
            }
            paint.setShader(null);
            paint.setStrokeWidth(dp(1));
            paint.setColor(ACCENT);
            canvas.drawLine(marker, dp(5), marker, getHeight() - dp(5), paint);
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
