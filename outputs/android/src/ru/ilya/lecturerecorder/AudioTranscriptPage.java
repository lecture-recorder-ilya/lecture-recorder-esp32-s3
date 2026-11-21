package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.content.Intent;
import android.app.Dialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Canvas;
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
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
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
    private final boolean landscape;
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
    private Button summary;
    private final Button importButton;
    private final TextView importStatus;
    private TextView times;
    private TextView waveStatus;
    private TextView transcriptStatus;
    private Dialog wordEditor;
    private final LinearLayout audioPanel;
    private final LinearLayout transcriptPanel;
    private ProgressBar transcriptSpinner;
    private TranscriptAdapter transcript;
    private Waveform waveform;

    AudioTranscriptPage(Activity activity, Bundle state, Runnable importAudio) {
        super(activity);
        this.activity = activity;
        setOrientation(VERTICAL);
        setBackgroundColor(BACKGROUND);
        setPadding(dp(16), dp(14), dp(16), dp(10));

        landscape = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        LinearLayout playback = this;
        LinearLayout columns = null;
        if (landscape) {
            columns = new LinearLayout(activity);
            addView(columns, new LinearLayout.LayoutParams(-1, 0, 1));
            playback = column();
            columns.addView(playback, new LinearLayout.LayoutParams(0, -1, 1));
        } else {
            TextView heading = text("Аудио и текст", 28, TEXT);
            heading.setTypeface(Typeface.DEFAULT_BOLD);
            heading.setLetterSpacing(-.025f);
            if (android.os.Build.VERSION.SDK_INT >= 28) heading.setAccessibilityHeading(true);
            addView(heading);
        }

        recordingDropdown = new ChoiceDropdown(activity, "Выбрать запись", "Сохранённых записей пока нет",
                this::recordingOptions, option -> {
                    if (!option.value.equals(selected)) select(option.value, 0, true);
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
        playback.addView(picker, spaced(-1, dp(52), landscape ? 0 : 10));
        importStatus = text("", 13, MUTED);
        importStatus.setVisibility(View.GONE);
        importStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        playback.addView(importStatus, spaced(-1, -2, 4));

        FrameLayout body = new FrameLayout(activity);
        playback.addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout details = column();
        body.addView(details, new FrameLayout.LayoutParams(-1, -1));

        audioPanel = card();
        audioPanel.setVisibility(View.GONE);
        details.addView(audioPanel, spaced(-1, -2, 12));
        addAudioPanel(audioPanel);

        transcriptPanel = card();
        transcriptPanel.setVisibility(View.GONE);
        View transcriptDismiss = null;
        if (landscape) {
            FrameLayout transcriptHost = new FrameLayout(activity);
            LinearLayout.LayoutParams panel = new LinearLayout.LayoutParams(0, -1, 2);
            panel.setMarginStart(dp(12));
            columns.addView(transcriptHost, panel);
            transcriptHost.addView(transcriptPanel, new FrameLayout.LayoutParams(-1, -1));
            transcriptDismiss = addDropdownDismiss(transcriptHost);
        } else {
            LinearLayout.LayoutParams panel = new LinearLayout.LayoutParams(-1, 0, 1);
            panel.topMargin = dp(12);
            details.addView(transcriptPanel, panel);
        }
        addTranscriptPanel(transcriptPanel);
        addRecordingDropdown(body, transcriptDismiss);

        if (state != null) {
            String name = state.getString("recording");
            if (LectureNotes.valid(name)) select(name, state.getInt("position"), false);
        }
    }

    private void addAudioPanel(LinearLayout audio) {
        waveform = new Waveform(activity);
        audio.addView(waveform, new LinearLayout.LayoutParams(-1, dp(landscape ? 54 : 94)));
        waveStatus = text("", 13, MUTED);
        audio.addView(waveStatus);

        LinearLayout controls = new LinearLayout(activity);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        play = button("Слушать", this::togglePlayback);
        controls.addView(play, new LinearLayout.LayoutParams(-2, dp(48)));
        times = text("", 13, MUTED);
        times.setTypeface(Typeface.MONOSPACE);
        times.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        controls.addView(times, new LinearLayout.LayoutParams(0, -1, 1));
        if (!landscape) addSummaryButton(controls);
        audio.addView(controls, spaced(-1, dp(48), 4));
        if (landscape) {
            addTranscribeButton(audio, spaced(-1, dp(48), 8));
        }
    }

    private void addSummaryButton(LinearLayout host) {
        summary = button("Конспект", this::openSummary);
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
        transcribe = button("Расшифровать", () -> {
            if (TextUtils.equals(transcribe.getText(), "Отменить")) {
                activity.startService(PhoneAnalysisService.cancel(activity));
            }
            else if (selected != null && Store.audio(activity, selected).isFile()) {
                PhoneAnalysisService.request(activity, selected, Store.recordingTitle(selected), true);
            }
        });
        host.addView(transcribe, layout);
    }

    private void addTranscriptStatus(LinearLayout host) {
        transcriptStatus = text("", 14, MUTED);
        transcriptStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        host.addView(transcriptStatus, spaced(-1, -2, 4));
    }

    private void addTranscriptPanel(LinearLayout box) {
        LinearLayout header = new LinearLayout(activity);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView heading = text("Расшифровка", 18, TEXT);
        heading.setTypeface(Typeface.DEFAULT_BOLD);
        header.addView(heading, new LinearLayout.LayoutParams(0, -2, 1));
        transcriptSpinner = new ProgressBar(activity);
        transcriptSpinner.setIndeterminateTintList(ColorStateList.valueOf(ACCENT));
        transcriptSpinner.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        transcriptSpinner.setVisibility(View.GONE);
        header.addView(transcriptSpinner, new LinearLayout.LayoutParams(dp(22), dp(22)));
        box.addView(header);

        if (!landscape) {
            LinearLayout.LayoutParams action = new LinearLayout.LayoutParams(-2, dp(48));
            action.setMarginStart(dp(8));
            addTranscribeButton(header, action);
        } else {
            addSummaryButton(header);
        }
        addTranscriptStatus(box);

        ListView lines = new ListView(activity);
        transcript = new TranscriptAdapter(activity);
        lines.setAdapter(transcript);
        lines.setDivider(new android.graphics.drawable.ColorDrawable(StudioStyle.LINE));
        lines.setDividerHeight(dp(1));
        if (landscape) lines.setScrollbarFadingEnabled(false);
        box.addView(lines, new LinearLayout.LayoutParams(-1, 0, 1));
    }

    private View addDropdownDismiss(FrameLayout host) {
        View dismiss = new View(activity);
        dismiss.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        dismiss.setOnClickListener(view -> closeDropdown());
        dismiss.setVisibility(View.GONE);
        host.addView(dismiss, new FrameLayout.LayoutParams(-1, -1));
        return dismiss;
    }

    private void addRecordingDropdown(FrameLayout body, View transcriptDismiss) {
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
            if (transcriptDismiss != null) {
                transcriptDismiss.setBackgroundColor(scrim);
                transcriptDismiss.setVisibility(visibility);
            }
        });
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(6);
        body.addView(recordingDropdown.list, layout);
    }

    private List<ChoiceDropdown.Option> recordingOptions() {
        TreeMap<String, ChoiceDropdown.Option> options = new TreeMap<>(Collections.reverseOrder());
        for (File file : Store.audioFiles(activity)) {
            long seconds = Math.max(0, file.length() - 44) / (PcmWave.SAMPLE_RATE * 2);
            String name = file.getName();
            options.put(name, new ChoiceDropdown.Option(name, Store.recordingTitle(name),
                    LectureReaderActivity.clock(seconds)));
        }
        for (boolean local : new boolean[]{true, false}) {
            for (File file : LectureNotes.files(activity, local)) {
                String name = file.getName().substring(0, file.getName().length() - 5);
                if (LectureNotes.valid(name)) {
                    options.putIfAbsent(name, new ChoiceDropdown.Option(name, Store.recordingTitle(name), "Только текст"));
                }
            }
        }
        return new ArrayList<>(options.values());
    }

    boolean closeDropdown() {
        return recordingDropdown.close();
    }

    private void select(String name, int initialPosition, boolean autoTranscribe) {
        releasePlayer();
        if (scan != null) scan.cancel(true);
        selected = name;
        noteRevision = null;
        transcript.replace(new ArrayList<>());
        position = initialPosition;
        duration = 0;
        recordingDropdown.setSelected(new ChoiceDropdown.Option(name, Store.recordingTitle(name), ""));
        waveform.setEnvelope(null);
        boolean hasAudio = Store.audio(activity, name).isFile();
        transcriptPanel.setVisibility(View.VISIBLE);
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
        if (autoTranscribe && transcript.isEmpty() && android.os.Process.is64Bit()
                && !PhoneAnalysisService.busy() && PhoneModels.ready(activity)) {
            PhoneAnalysisService.request(activity, name, Store.recordingTitle(name));
        }
        updatePosition();
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
    }

    private void refreshPlayback() {
        if (prepared && player.isPlaying()) position = player.getCurrentPosition();
        if (selected != null) updatePosition();
        if (visible) ui.postDelayed(playbackTick, 120);
    }

    private void updatePosition() {
        if (player != null) {
            times.setText(LectureReaderActivity.clock(position / 1000.0) + " / "
                    + LectureReaderActivity.clock(duration / 1000.0));
            play.setText(prepared && player.isPlaying() ? "Пауза" : "Слушать");
        }
        waveform.invalidate();
    }

    private void showWaveStatus(String status) {
        waveStatus.setText(status);
        waveStatus.setVisibility(status.isEmpty() ? View.GONE : View.VISIBLE);
    }

    private void refreshTranscript() {
        String importMessage = AudioImport.status;
        if (!TextUtils.equals(importStatus.getText(), importMessage)) importStatus.setText(importMessage);
        importStatus.setVisibility(importMessage.isEmpty() ? View.GONE : View.VISIBLE);
        importButton.setEnabled(!AudioImport.busy);
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
            List<TranscriptEdits.Line> rows = readSegments(local, true, corrections);
            if (rows.isEmpty()) rows = readSegments(mac, false, corrections);
            transcript.replace(rows);
            noteRevision = revision;
        }

        summary.setVisibility(local.isFile() || mac.isFile() ? View.VISIBLE : View.GONE);
        boolean loading = PhoneAnalysisService.busyFor(selected);
        boolean supported = android.os.Process.is64Bit();
        boolean busy = PhoneAnalysisService.busy();
        boolean hasAudio = Store.audio(activity, selected).isFile();
        audioPanel.setVisibility(hasAudio || !landscape || busy ? View.VISIBLE : View.GONE);
        transcriptSpinner.setVisibility(loading ? View.VISIBLE : View.GONE);
        String message = PhoneAnalysisService.statusFor(selected);
        if (busy && !loading) message = "Обрабатывается другая запись";
        else if (message.isEmpty() && transcript.isEmpty()) {
            if (!supported) message = "Расшифровка появится после обработки на Mac.";
            else message = "У этой записи пока нет расшифровки.";
        }
        if (!TextUtils.equals(transcriptStatus.getText(), message)) transcriptStatus.setText(message);
        transcriptStatus.setVisibility(message.isEmpty() ? View.GONE : View.VISIBLE);
        transcribe.setVisibility(supported && (hasAudio || busy) ? View.VISIBLE : View.GONE);
        String label = busy ? "Отменить" : "Расшифровать";
        if (!TextUtils.equals(transcribe.getText(), label)) transcribe.setText(label);
        String action = !busy && !transcript.isEmpty() ? "Расшифровать заново" : label;
        if (!TextUtils.equals(transcribe.getContentDescription(), action)) transcribe.setContentDescription(action);
    }

    private List<TranscriptEdits.Line> readSegments(File note, boolean local, JSONObject corrections) {
        List<TranscriptEdits.Line> rows = new ArrayList<>();
        if (!note.isFile()) return rows;
        try {
            JSONArray segments = new JSONObject(Store.read(note)).getJSONObject("report").optJSONArray("segments");
            if (segments != null) for (int i = 0; i < segments.length(); i++) {
                JSONObject part = segments.optJSONObject(i);
                if (part != null && !part.optString("text").isEmpty()) {
                    rows.add(new TranscriptEdits.Line(part, i, local, corrections));
                }
            }
        } catch (Exception ignored) {
            // The other transcript may still be available.
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
        replacement.setBackground(surface(0xff2b2d33, 10));
        replacement.setText(word.value);
        replacement.setSelectAllOnFocus(true);
        sheet.addView(replacement, spaced(-1, dp(50), 12));

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
        save.setTextColor(0xff21130e);
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
            row.time.setVisibility(timed ? View.VISIBLE : View.GONE);
            if (timed) {
                String time = LectureReaderActivity.clock(line.start);
                row.time.setText(time);
                row.time.setContentDescription("Слушать с " + time);
                row.time.setOnClickListener(view -> seek((int) (Math.max(0, line.start) * 1000), true));
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
                        if (recording.equals(selected)) editWord(line, wordIndex);
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
            time.setTextColor(ACCENT);
            time.setTypeface(Typeface.MONOSPACE);
            time.setBackground(StudioStyle.control(activity, StudioStyle.ACTIVE, 12));
            time.setPadding(dp(6), 0, dp(6), 0);
            time.setMinWidth(dp(54));
            time.setMinimumWidth(dp(54));
            LinearLayout.LayoutParams badge = new LinearLayout.LayoutParams(-2, dp(48));
            badge.rightMargin = dp(8);
            addView(time, badge);
            words.setLineSpacing(dp(3), 1);
            words.setMovementMethod(LinkMovementMethod.getInstance());
            words.setHighlightColor(0x55c5b5ff);
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
                paint.setColor(played ? StudioStyle.TEXT : peak > .6f ? 0xffaaa0cf : 0xff77728e);
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
