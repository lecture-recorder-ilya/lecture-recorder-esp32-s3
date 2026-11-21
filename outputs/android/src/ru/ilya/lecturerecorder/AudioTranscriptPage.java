package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
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
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

final class AudioTranscriptPage extends LinearLayout {
    private static final int BACKGROUND = 0xff101113;
    private static final int PANEL = 0xff191b1f;
    private static final int TEXT = 0xfff5f3f1;
    private static final int MUTED = 0xffa7a9b2;
    private static final int ACCENT = 0xffff593b;

    private final Activity activity;
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
    private TextView times;
    private TextView waveStatus;
    private TextView transcriptStatus;
    private TextView editHint;
    private Dialog wordEditor;
    private LinearLayout details;
    private FrameLayout body;
    private View dropdownDismiss;
    private ProgressBar transcriptSpinner;
    private TranscriptAdapter transcript;
    private Waveform waveform;

    AudioTranscriptPage(Activity activity, Bundle state) {
        super(activity);
        this.activity = activity;
        setOrientation(VERTICAL);
        setBackgroundColor(BACKGROUND);
        setPadding(dp(16), dp(14), dp(16), dp(10));

        TextView heading = text("Аудио и текст", 23, TEXT);
        heading.setTypeface(Typeface.DEFAULT_BOLD);
        addView(heading);

        recordingDropdown = new ChoiceDropdown(activity, "Выбрать запись", "Сохранённых записей пока нет",
                this::recordingOptions, option -> {
                    if (!option.value.equals(selected)) select(option.value, 0, true);
                });
        addView(recordingDropdown.button, spaced(-1, dp(52), 10));

        body = new FrameLayout(activity);
        addView(body, new LinearLayout.LayoutParams(-1, 0, 1));
        details = column();
        details.setVisibility(View.GONE);
        body.addView(details, new FrameLayout.LayoutParams(-1, -1));
        addAudioPanel();
        addTranscriptPanel();
        addRecordingDropdown();

        if (state != null) {
            String name = state.getString("recording");
            if (LectureNotes.valid(name)) select(name, state.getInt("position"), false);
        }
    }

    private void addAudioPanel() {
        LinearLayout audio = card();
        details.addView(audio, spaced(-1, -2, 12));
        waveform = new Waveform(activity);
        int orientation = getResources().getConfiguration().orientation;
        audio.addView(waveform, new LinearLayout.LayoutParams(-1,
                dp(orientation == Configuration.ORIENTATION_LANDSCAPE ? 54 : 94)));
        waveStatus = text("", 13, MUTED);
        audio.addView(waveStatus);

        LinearLayout controls = new LinearLayout(activity);
        controls.setGravity(Gravity.CENTER_VERTICAL);
        play = button("Слушать", this::togglePlayback);
        controls.addView(play, new LinearLayout.LayoutParams(-2, dp(48)));
        times = text("", 14, MUTED);
        times.setGravity(Gravity.END | Gravity.CENTER_VERTICAL);
        controls.addView(times, new LinearLayout.LayoutParams(0, -1, 1));
        audio.addView(controls, spaced(-1, dp(48), 4));
    }

    private void addTranscriptPanel() {
        LinearLayout box = card();
        LinearLayout.LayoutParams available = new LinearLayout.LayoutParams(-1, 0, 1);
        available.topMargin = dp(12);
        details.addView(box, available);

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

        transcriptStatus = text("", 14, MUTED);
        transcriptStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        box.addView(transcriptStatus, spaced(-1, -2, 4));
        transcribe = button("Расшифровать", () ->
                PhoneAnalysisService.request(activity, selected, Store.recordingTitle(selected)));
        box.addView(transcribe, spaced(-1, dp(48), 6));

        editHint = text("Нажми на слово, чтобы исправить", 13, MUTED);
        editHint.setVisibility(View.GONE);
        box.addView(editHint, spaced(-1, -2, 4));

        ListView lines = new ListView(activity);
        transcript = new TranscriptAdapter(activity);
        lines.setAdapter(transcript);
        lines.setDivider(new android.graphics.drawable.ColorDrawable(0xff2b2d33));
        lines.setDividerHeight(dp(1));
        box.addView(lines, new LinearLayout.LayoutParams(-1, 0, 1));
    }

    private void addRecordingDropdown() {
        dropdownDismiss = new View(activity);
        dropdownDismiss.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        dropdownDismiss.setOnClickListener(view -> closeDropdown());
        dropdownDismiss.setVisibility(View.GONE);
        body.addView(dropdownDismiss, new FrameLayout.LayoutParams(-1, -1));

        recordingDropdown.setHeightLimit(() -> body.getHeight() - dp(12));
        recordingDropdown.setExpansionListener(open -> {
            details.setImportantForAccessibility(open ? View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
                    : View.IMPORTANT_FOR_ACCESSIBILITY_AUTO);
            dropdownDismiss.setBackgroundColor(selected == null ? 0 : 0x44000000);
            dropdownDismiss.setVisibility(open ? View.VISIBLE : View.GONE);
        });
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(6);
        body.addView(recordingDropdown.list, layout);
    }

    private List<ChoiceDropdown.Option> recordingOptions() {
        List<ChoiceDropdown.Option> options = new ArrayList<>();
        for (File file : Store.audioFiles(activity)) {
            long seconds = Math.max(0, file.length() - 44) / (PcmWave.SAMPLE_RATE * 2);
            options.add(new ChoiceDropdown.Option(file.getName(), Store.recordingTitle(file.getName()),
                    LectureReaderActivity.clock(seconds)));
        }
        return options;
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
        showWaveStatus("Строю звуковую дорожку…");
        details.setVisibility(View.VISIBLE);
        play.setEnabled(false);
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
            editHint.setVisibility(rows.isEmpty() ? View.GONE : View.VISIBLE);
            noteRevision = revision;
        }

        boolean loading = transcript.isEmpty() && PhoneAnalysisService.busyFor(selected);
        transcriptSpinner.setVisibility(loading ? View.VISIBLE : View.GONE);
        String message = "";
        boolean canTranscribe = transcript.isEmpty() && android.os.Process.is64Bit() && !PhoneAnalysisService.busy();
        if (transcript.isEmpty()) {
            if (loading) message = PhoneAnalysisService.statusFor(selected);
            else if (PhoneAnalysisService.busy()) message = "Сейчас обрабатывается другая запись.";
            else if (!android.os.Process.is64Bit()) message = "Расшифровка появится после обработки на Mac.";
            else {
                message = PhoneAnalysisService.statusFor(selected);
                if (message.isEmpty()) message = "У этой записи пока нет расшифровки.";
            }
        }
        if (!TextUtils.equals(transcriptStatus.getText(), message)) transcriptStatus.setText(message);
        transcriptStatus.setVisibility(message.isEmpty() ? View.GONE : View.VISIBLE);
        transcribe.setVisibility(canTranscribe ? View.VISIBLE : View.GONE);
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
        save.setBackground(new RippleDrawable(ColorStateList.valueOf(0x3321130e), surface(ACCENT, 10), null));
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
        view.setBackground(surface(PANEL, 14));
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
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x28ffffff), surface(0xff2b2d33, 10), null));
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
            setGravity(Gravity.TOP);
            setPadding(0, dp(10), 0, dp(10));
            time.setTextSize(13);
            time.setTextColor(MUTED);
            time.setPadding(dp(6), 0, dp(6), 0);
            time.setMinWidth(dp(54));
            time.setMinimumWidth(dp(54));
            LinearLayout.LayoutParams badge = new LinearLayout.LayoutParams(-2, dp(48));
            badge.rightMargin = dp(8);
            addView(time, badge);
            words.setLineSpacing(dp(3), 1);
            words.setMovementMethod(LinkMovementMethod.getInstance());
            words.setHighlightColor(0x55ff593b);
            addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        }
    }

    private final class Waveform extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private PcmWave.Envelope envelope;

        Waveform(Context context) {
            super(context);
            setBackground(surface(0xff131519, 10));
            setContentDescription("Звуковая дорожка");
            setFocusable(true);
            setClickable(true);
        }

        void setEnvelope(PcmWave.Envelope value) {
            envelope = value;
            invalidate();
        }

        @Override protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float left = dp(8);
            float width = getWidth() - 2 * left;
            float midpoint = getHeight() / 2f;
            paint.setColor(0xff353943);
            paint.setStrokeWidth(dp(1));
            canvas.drawLine(left, midpoint, left + width, midpoint, paint);
            if (envelope == null || envelope.peaks.length == 0 || width <= 0) return;

            float progress = duration == 0 ? 0 : (float) position / duration;
            float step = width / envelope.peaks.length;
            paint.setStrokeWidth(Math.max(1f, step * 0.68f));
            for (int i = 0; i < envelope.peaks.length; i++) {
                float proportion = (i + 0.5f) / envelope.peaks.length;
                float x = left + (i + 0.5f) * step;
                float height = Math.max(0.45f, envelope.peaks[i] * (midpoint - dp(7)));
                paint.setColor(proportion <= progress ? ACCENT : 0xff858b9b);
                canvas.drawLine(x, midpoint - height, x, midpoint + height, paint);
            }
            paint.setStrokeWidth(dp(1));
            paint.setColor(ACCENT);
            float marker = left + progress * width;
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
