package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Typeface;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.media.MediaPlayer;
import android.media.PlaybackParams;
import android.os.SystemClock;
import android.widget.PopupMenu;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.SeekBar;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

public class LectureReaderActivity extends Activity {
    private static final int BACKGROUND = StudioStyle.BACKGROUND;
    private static final int CONTROL = StudioStyle.CONTROL;
    private static final int DIVIDER = StudioStyle.LINE;
    private static final int TEXT = StudioStyle.TEXT;
    private static final int MUTED = StudioStyle.MUTED;
    private static final int ACCENT = StudioStyle.ACCENT;
    private static final int ACTIVE = StudioStyle.ACTIVE;
    private static final String[] TABS = {"summary", "text", "review"};
    private static final String[] TAB_LABELS = {"Конспект", "Текст", "Проверить"};

    private final Handler timer = new Handler(Looper.getMainLooper());
    private final Button[] tabButtons = new Button[TABS.length];
    private LinearLayout body;
    private ScrollView scroll;
    private TextView status, elapsed;
    private TextView pendingSummaryStatus;
    private SeekBar position;
    private Button toggle, speedButton;
    private ListeningLibrary library;
    private int speedIndex;
    private boolean seekPending, finishedListening;
    private long nextCheckpoint;
    private Button finishSummary;
    private JSONObject document;
    private File note, edits;
    private String recording;
    private boolean local, fromLibrary, chooseReadingTab;
    private String stamp = "";
    private String searchQuery = "";
    private AlertDialog searchDialog;
    private final android.util.SparseArray<View> textRows = new android.util.SparseArray<>();
    private int highlightedSegment = -1;
    private String tab = "text";
    private String reviewKind = "all";
    private int reviewPage;
    private static final int REVIEW_PAGE_SIZE = 24;
    private MediaPlayer player;
    private ForegroundAudio focus;
    private int pendingSeek, contentScroll;
    private boolean ready, foreground;
    private AlertDialog replayDialog;
    private PhraseReplay replay;
    private int replayAudioEnd = -1;
    private boolean replaySeeking;

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        focus = new ForegroundAudio(this, this::pausePlayback);
        String file = getIntent().getStringExtra("file");
        if (file == null || !file.endsWith(".json")) {
            finish();
            return;
        }
        recording = file.substring(0, file.length() - 5);
        if (!LectureNotes.valid(recording)) {
            finish();
            return;
        }
        library = new ListeningLibrary(this);
        speedIndex = library.speed();
        pendingSeek = library.position(recording, 0);
        local = getIntent().getBooleanExtra("local", false);
        fromLibrary = getIntent().getBooleanExtra("from_library", false);
        note = LectureNotes.file(this, recording, local);
        edits = TranscriptEdits.file(this, recording);
        String requestedTab = saved == null ? getIntent().getStringExtra("tab") : saved.getString("reader_tab");
        chooseReadingTab = "read".equals(requestedTab);
        if ("summary".equals(requestedTab) || "review".equals(requestedTab)) tab = requestedTab;
        if (saved != null) {
            String selectedKind = saved.getString("reader_review_kind", "all");
            for (String kind : TranscriptReview.KINDS) if (kind.equals(selectedKind)) reviewKind = kind;
            reviewPage = Math.max(0, saved.getInt("review_page"));
            pendingSeek = saved.getInt("reader_seek", pendingSeek);
            finishedListening = saved.getBoolean("reader_finished");
            searchQuery = saved.getString("text_query", "");
            contentScroll = saved.getInt("reader_scroll");
        }

        boolean landscape = getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        LinearLayout page = column();
        page.setBackgroundColor(BACKGROUND);
        StudioStyle.fitWindow(getWindow(), page, dp(StudioStyle.PAGE_INSET), dp(8), dp(8));
        addNavigation(page, landscape);

        scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        scroll.setFocusableInTouchMode(true);
        body = column();
        body.setPadding(0, dp(8), 0, dp(8));
        scroll.addView(body, new ScrollView.LayoutParams(-1, -2));
        page.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));

        status = text("", 13, MUTED);
        status.setVisibility(View.GONE);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        page.addView(status, spaced(-1, -2, 4));
        File audio = Store.audio(this, recording);
        if (audio.isFile()) addPlayer(page, audio);
        setContentView(page);
        page.requestApplyInsets();
        if (saved == null) StudioStyle.enter(body, true);
    }

    private void addNavigation(LinearLayout page, boolean landscape) {
        LinearLayout navigation = new LinearLayout(this);
        boolean compact = getResources().getConfiguration().screenWidthDp < 560
                || getResources().getConfiguration().fontScale > 1.25f;
        Button back = button(fromLibrary ? "‹ Библиотека" : "‹ К записи", this::finish);
        back.setTextColor(ACCENT);
        back.setBackground(StudioStyle.control(this, Color.TRANSPARENT, 10));
        navigation.addView(back, new LinearLayout.LayoutParams(compact ? 0 : -2, -2, compact ? 1.6f : 0));
        Button search = button("Найти", this::findInTranscript);
        search.setContentDescription("Найти в тексте лекции");
        LinearLayout.LayoutParams searchSize = withGap(compact ? 0 : -2, -2, 4);
        searchSize.weight = compact ? 1 : 0;
        navigation.addView(search, searchSize);
        boolean alternate = LectureNotes.file(this, recording, !local).isFile();
        boolean audioDetails = fromLibrary && Store.audio(this, recording).isFile();
        if (alternate || audioDetails) {
            Button more = button("Ещё");
            more.setContentDescription("Действия с записью");
            more.setOnClickListener(view -> {
                PopupMenu menu = new PopupMenu(this, more);
                if (audioDetails) menu.getMenu().add(0, 1, 0, "Аудио и правки");
                if (alternate) menu.getMenu().add(0, 2, 1, local ? "Версия с Mac" : "Версия с телефона");
                menu.setOnMenuItemClickListener(item -> {
                    if (item.getItemId() == 1) {
                        setResult(RESULT_OK, new Intent().putExtra("audio", recording));
                    } else {
                        Intent version = new Intent(this, LectureReaderActivity.class)
                                .putExtra("file", note.getName()).putExtra("local", !local)
                                .putExtra("from_library", fromLibrary).putExtra("tab", tab);
                        if (fromLibrary) version.addFlags(Intent.FLAG_ACTIVITY_FORWARD_RESULT);
                        startActivity(version);
                    }
                    finish();
                    return true;
                });
                menu.show();
            });
            navigation.addView(more, withGap(-2, -2, 4));
        }
        page.addView(navigation);
        LinearLayout tabs = new LinearLayout(this);
        tabs.setBackground(StudioStyle.card(this, 15));
        tabs.setPadding(dp(3), dp(3), dp(3), dp(3));
        for (int index = 0; index < TABS.length; index++) {
            String target = TABS[index];
            Button button = button(TAB_LABELS[index], () -> {
                if (tab.equals(target)) return;
                tab = target;
                scroll.scrollTo(0, 0);
                contentScroll = 0;
                updateTabs();
                render();
                StudioStyle.enter(body, false);
            });
            StudioStyle.fitLabel(button, 9, 14);
            button.setPadding(dp(3), 0, dp(3), 0);
            tabButtons[index] = button;
            tabs.addView(button, new LinearLayout.LayoutParams(0, dp(48), 1));
        }
        if (landscape && !compact && getResources().getConfiguration().screenWidthDp >= 760) {
            LinearLayout.LayoutParams area = withGap(0, -2, 12);
            area.weight = 1;
            navigation.addView(tabs, area);
        } else {
            page.addView(tabs, spaced(-1, -2, 8));
        }
        updateTabs();
    }

    private void updateTabs() {
        for (int index = 0; index < TABS.length; index++) {
            boolean active = tab.equals(TABS[index]);
            Button button = tabButtons[index];
            button.setSelected(active);
            button.setTextColor(active ? ACCENT : MUTED);
            button.setBackground(control(active ? ACTIVE : Color.TRANSPARENT));
        }
    }

    private void addPlayer(LinearLayout page, File audio) {
        int duration = (int)Math.min(Integer.MAX_VALUE, Math.max(0L, audio.length() - 44) / 32);
        pendingSeek = ListeningLibrary.resumable(pendingSeek, duration);
        library.position(recording, duration);
        boolean compact = getResources().getConfiguration().screenWidthDp < 560
                || getResources().getConfiguration().fontScale > 1.25f;
        LinearLayout panel = column();
        panel.setPadding(dp(8), dp(4), dp(8), dp(4));
        panel.setBackground(StudioStyle.card(this, 16));
        LinearLayout commands = new LinearLayout(this);
        commands.setGravity(Gravity.CENTER_VERTICAL);
        panel.addView(commands);
        toggle = button(idlePlayLabel(), () -> {
            if (ready && player.isPlaying()) pausePlayback();
            else playAt(actualPosition());
        });
        StudioStyle.actionTone(toggle, ACCENT, StudioStyle.INK);
        commands.addView(toggle, new LinearLayout.LayoutParams(compact ? 0 : -2, -2, compact ? 1 : 0));
        speedButton = button(ListeningLibrary.SPEED_LABELS[speedIndex], this::chooseSpeed);
        updateSpeedLabel();
        commands.addView(speedButton, withGap(-2, -2, 6));
        LinearLayout trackRow = compact ? new LinearLayout(this) : commands;
        trackRow.setGravity(Gravity.CENTER_VERTICAL);
        if (compact) panel.addView(trackRow);

        position = new SeekBar(this);
        position.setContentDescription("Позиция записи");
        position.setProgressTintList(ColorStateList.valueOf(ACCENT));
        position.setThumbTintList(ColorStateList.valueOf(ACCENT));
        position.setEnabled(false);
        position.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
            @Override public void onStartTrackingTouch(SeekBar bar) {}
            @Override public void onStopTrackingTouch(SeekBar bar) {}
            @Override public void onProgressChanged(SeekBar bar, int value, boolean user) {
                if (user) playAt(value);
            }
        });
        LinearLayout.LayoutParams track = withGap(0, dp(48), 4);
        track.weight = 1;
        position.setMax(duration);
        position.setProgress(pendingSeek);
        trackRow.addView(position, track);
        elapsed = text(clock(pendingSeek / 1000.0) + " / " + clock(duration / 1000.0), 13, MUTED);
        elapsed.setTypeface(Typeface.MONOSPACE);
        StudioStyle.fitLabel(elapsed, 8, 12);
        trackRow.addView(elapsed, withGap(dp(100), dp(36), 4));
        page.addView(panel, spaced(-1, -2, 8));
    }

    private void render() {
        if (document == null) return;
        JSONObject report = document.optJSONObject("report");
        if (report == null) return;
        if (chooseReadingTab) {
            JSONArray points = report.optJSONArray("summary");
            tab = !report.optBoolean("draft") && !report.optBoolean(LectureNotes.SUMMARY_PENDING)
                    && (!report.optString("overview").trim().isEmpty() || points != null && points.length() > 0)
                    ? "summary" : "text";
            chooseReadingTab = false;
            updateTabs();
        }
        if (replayDialog != null) replayDialog.dismiss();
        int offset = Math.max(scroll.getScrollY(), contentScroll);
        contentScroll = 0;
        body.removeAllViews();
        textRows.clear();
        pendingSummaryStatus = null;
        finishSummary = null;
        TextView heading = heading(report.optString("topic", LectureNotes.title(document)), 24);
        body.addView(heading, spaced(-1, -2, 4));
        if ("summary".equals(tab)) renderSummary(report);
        else renderTranscript(report, "review".equals(tab));
        scroll.post(() -> scroll.scrollTo(0, offset));
    }

    private void renderSummary(JSONObject report) {
        if (local && report.optBoolean(LectureNotes.SUMMARY_PENDING)) {
            pendingSummaryStatus = text("", 16, MUTED);
            pendingSummaryStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
            body.addView(pendingSummaryStatus, spaced(-1, -2, 12));
            if (android.os.Process.is64Bit()) {
                finishSummary = button("Завершить конспект", () ->
                        PhoneAnalysisService.requestSummary(this, recording, LectureNotes.title(document)));
                body.addView(finishSummary, spaced(-1, dp(48), 8));
            }
            updatePendingSummary();
            return;
        }
        if (report.optBoolean("draft")) {
            body.addView(text("Конспект готовится", 16, MUTED), spaced(-1, -2, 12));
            return;
        }

        String overview = report.optString("overview");
        JSONArray points = report.optJSONArray("summary");
        JSONArray sources = report.optJSONArray("summary_evidence");
        boolean hasPoints = points != null && points.length() > 0;
        if (!overview.isEmpty()) {
            TextView lead = text(overview, 16, TEXT);
            lead.setLineSpacing(dp(5), 1);
            lead.setPadding(dp(16), dp(14), dp(16), dp(14));
            lead.setBackground(surface(ACTIVE, 18));
            body.addView(lead, spaced(-1, -2, 10));
        }
        if (hasPoints) {
            LinearLayout list = card();
            for (int index = 0; index < points.length(); index++) {
                if (index > 0) divider(list);
                LinearLayout row = new LinearLayout(this);
                row.setGravity(Gravity.TOP);
                row.setPadding(0, dp(10), 0, dp(10));
                TextView marker = text("•", 16, ACCENT);
                row.addView(marker, new LinearLayout.LayoutParams(dp(18), -2));
                String point = points.optString(index);
                LinearLayout content = new LinearLayout(this);
                content.setOrientation(LinearLayout.VERTICAL);
                content.addView(text(point, 16, TEXT));
                JSONObject source = sources == null ? null : sources.optJSONObject(index);
                if (source != null && point.equals(source.optString("quote"))) {
                    int start = (int) (source.optDouble("start", -1) * 1000);
                    if (start >= 0) {
                        content.addView(button("Слушать с " + clock(start / 1000.0), () -> playAt(start)),
                                spaced(-2, dp(48), 6));
                    }
                }
                row.addView(content, new LinearLayout.LayoutParams(0, -2, 1));
                list.addView(row);
            }
            body.addView(list, spaced(-1, -2, 14));
        }

        JSONArray tasks = report.optJSONArray("homework");
        boolean hasTasks = tasks != null && tasks.length() > 0;
        if (hasTasks) {
            body.addView(heading("Задания из записи", 18), spaced(-1, -2, 18));
            for (int index = 0; index < tasks.length(); index++) {
                JSONObject task = tasks.optJSONObject(index);
                if (task == null) continue;
                LinearLayout block = card();
                block.addView(text(task.optString("task"), 16, TEXT));
                if (task.has("start")) {
                    int start = (int) (task.optDouble("start") * 1000);
                    block.addView(button("Слушать с " + clock(start / 1000.0), () -> playAt(start)),
                            spaced(-2, dp(48), 6));
                }
                body.addView(block, spaced(-1, -2, 8));
            }
        }

        if (!overview.isEmpty() || hasPoints || hasTasks) {
            body.addView(button("Поделиться конспектом", this::shareSummary), spaced(-1, dp(48), 12));
        } else {
            body.addView(text("Конспекта пока нет", 16, MUTED), spaced(-1, -2, 12));
        }
    }

    private void updatePendingSummary() {
        if (pendingSummaryStatus == null) return;
        String message = PhoneAnalysisService.busyFor(recording)
                ? PhoneAnalysisService.statusFor(recording) : "Конспект не готов";
        if (!message.contentEquals(pendingSummaryStatus.getText())) pendingSummaryStatus.setText(message);
        if (finishSummary != null) finishSummary.setEnabled(!PhoneAnalysisService.busy());
    }

    private void shareSummary() {
        try {
            Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain");
            send.putExtra(Intent.EXTRA_TEXT, LectureNotes.summary(document));
            startActivity(Intent.createChooser(send, "Сохранить или отправить"));
        } catch (Exception error) {
            showStatus("Не удалось подготовить текст");
        }
    }

    private void renderTranscript(JSONObject report, boolean reviewOnly) {
        if (reviewOnly) {
            LinearLayout filters = new LinearLayout(this);
            for (int index = 0; index < TranscriptReview.KINDS.length; index++) {
                String kind = TranscriptReview.KINDS[index];
                Button filter = button(TranscriptReview.LABELS[index], () -> {
                    reviewKind = kind;
                    showReviewPage(0);
                });
                StudioStyle.fitLabel(filter, 9, 13);
                filter.setPadding(dp(2), 0, dp(2), 0);
                filter.setSelected(kind.equals(reviewKind));
                filter.setTextColor(kind.equals(reviewKind) ? ACCENT : TEXT);
                filters.addView(filter, new LinearLayout.LayoutParams(0, dp(48), 1));
            }
            body.addView(filters, spaced(-1, -2, 8));
            String guidance = reviewKind.equals("all") ? "Отметки распознавания. Нажми слово, чтобы свериться с записью."
                    : "Совпадения по всей расшифровке, включая уверенно распознанные фразы.";
            body.addView(text(guidance, 13, MUTED), spaced(-1, -2, 6));
        }
        JSONArray rows = report.optJSONArray("segments");
        boolean searchTerms = reviewOnly && !reviewKind.equals("all");
        int count = 0, matchesBeforePage = 0;
        boolean more = false;
        if (rows != null) for (int index = 0; index < rows.length(); index++) {
            JSONObject row = rows.optJSONObject(index);
            if (row == null || reviewOnly && !searchTerms && (!row.optBoolean("needs_review") || reviewed(row))) continue;
            List<TranscriptReview.Item> candidates = reviewOnly ? TranscriptReview.words(row, searchTerms) : Collections.emptyList();
            if (searchTerms) {
                boolean matches = false;
                for (TranscriptReview.Item item : candidates) matches |= item.kind.equals(reviewKind);
                if (!matches) continue;
                if (matchesBeforePage++ < reviewPage * REVIEW_PAGE_SIZE) continue;
                if (count == REVIEW_PAGE_SIZE) { more = true; break; }
            }
            count++;
            LinearLayout block = card();
            if (!reviewOnly) {
                textRows.put(index, block);
                if (index == highlightedSegment) block.setBackground(StudioStyle.control(this, StudioStyle.ACTIVE, 12));
            }
            boolean timed = row.has("start") && row.has("end");
            int start = (int) (row.optDouble("start") * 1000);
            TextView phrase = text(row.optString("text"), 16, TEXT);
            if (timed) {
                phrase.setOnClickListener(view -> playAt(start));
                phrase.setFocusable(true);
                phrase.setContentDescription("Слушать с " + clock(start / 1000.0) + ". " + phrase.getText());
            }
            TextView timestamp = text(timed ? clock(start / 1000.0) : "Без таймкода", 13, timed ? ACCENT : MUTED);
            if (timed) {
                timestamp.setTypeface(Typeface.MONOSPACE);
                timestamp.setPadding(dp(8), dp(3), dp(8), dp(3));
                timestamp.setBackground(surface(ACTIVE, 8));
            }
            block.addView(timestamp, new LinearLayout.LayoutParams(-2, -2));
            block.addView(phrase, spaced(-1, -2, 5));
            if (reviewOnly) for (TranscriptReview.Item item : candidates) {
                if (!reviewKind.equals("all") && !item.kind.equals(reviewKind)) continue;
                String reason = item.direct ? "сомнение в слове"
                        : row.optBoolean("needs_review") ? "сомнение по фразе" : "совпадение в тексте";
                String location = item.millis < 0 ? "без таймкода"
                        : clock(item.millis / 1000.0) + (item.timedWord ? "" : " · начало фразы");
                Button listen = button(TranscriptReview.label(item.kind) + " «" + item.text + "» · " + location,
                        () -> playAt(item.millis));
                listen.setEnabled(item.millis >= 0);
                listen.setContentDescription("Слушать: " + item.text + ". " + reason + ". " + location);
                block.addView(listen, spaced(-1, -2, 6));
                block.addView(text(reason, 12, MUTED), spaced(-1, -2, 2));
            }
            if (reviewOnly && timed && Double.isFinite(row.optDouble("start")) && Double.isFinite(row.optDouble("end"))
                    && row.optDouble("end") > row.optDouble("start") && Store.audio(this, recording).isFile()) {
                block.addView(button("Разобрать фрагмент ещё раз", () -> repeatFragment(row, candidates)), spaced(-1, -2, 6));
            }
            if (row.optBoolean("needs_review")) {
                boolean checked = reviewed(row);
                block.addView(text(checked ? "Проверено по записи" : "Нужно проверить", 13, MUTED),
                        spaced(-1, -2, 8));
                String key = row.optString("review_key");
                if (!key.isEmpty()) {
                    block.addView(button(checked ? "Отменить проверку" : "Отметить проверенным", () -> {
                        getSharedPreferences("transcript-review", 0).edit().putBoolean(key, !checked).apply();
                        render();
                    }), spaced(-2, dp(48), 6));
                }
            }
            String original = row.optString("original_text");
            if (!original.isEmpty() && !original.equals(row.optString("text"))) {
                block.addView(text("Исходное распознавание: " + original, 13, MUTED), spaced(-1, -2, 8));
            }
            body.addView(block, spaced(-1, -2, 8));
        }
        if (count == 0) {
            body.addView(text(reviewOnly ? (reviewKind.equals("all") ? "Непроверенных отметок нет"
                    : "Совпадений нет") : "Текст пока недоступен", 16, MUTED),
                    spaced(-1, -2, 12));
        }
        if (searchTerms && (reviewPage > 0 || more)) {
            LinearLayout pages = new LinearLayout(this);
            if (reviewPage > 0) pages.addView(button("Назад", () -> showReviewPage(reviewPage - 1)));
            if (more) pages.addView(button("Дальше", () -> showReviewPage(reviewPage + 1)));
            body.addView(pages, spaced(-1, -2, 8));
        }
    }

    private void showReviewPage(int page) {
        reviewPage = page;
        contentScroll = 0;
        scroll.scrollTo(0, 0);
        render();
    }

    private void findInTranscript() {
        if (searchDialog != null) return;
        JSONObject report = document == null ? null : document.optJSONObject("report");
        JSONArray segments = report == null ? null : report.optJSONArray("segments");
        if (segments == null || segments.length() == 0) { showStatus("В этой записи пока нет расшифровки"); return; }
        String revision = stamp;
        searchDialog = TranscriptSearch.open(this, segments, searchQuery, value -> searchQuery = value, index -> {
            if (!revision.equals(TranscriptEdits.stamp(note) + "/" + TranscriptEdits.stamp(edits))) {
                showStatus("Расшифровка обновилась. Повтори поиск.");
                return;
            }
            highlightedSegment = index;
            tab = "text";
            updateTabs();
            render();
            View result = textRows.get(index);
            if (result != null) scroll.post(() -> {
                scroll.scrollTo(0, result.getTop());
                StudioStyle.enter(result, false);
                JSONObject segment = segments.optJSONObject(index);
                if (segment != null) result.announceForAccessibility(segment.optString("text"));
            });
        });
        searchDialog.setOnDismissListener(dialog -> searchDialog = null);
    }

    private void repeatFragment(JSONObject row, List<TranscriptReview.Item> candidates) {
        if (replayDialog != null) return;
        double from = row.optDouble("start"), to = row.optDouble("end"), anchor = Double.NaN;
        for (TranscriptReview.Item word : candidates) {
            if (word.timedWord && word.millis >= 0 && (reviewKind.equals("all") || word.kind.equals(reviewKind))) {
                anchor = word.millis / 1000.0;
                break;
            }
        }
        PhraseReplayAudio.Window expected;
        try { expected = PhraseReplayAudio.window(Store.audio(this, recording).length() / 2, from, to, anchor); }
        catch (java.io.IOException invalid) { showStatus(invalid.getMessage()); return; }
        String revision = stamp;
        String original = row.optString("text");
        int[] range = {(int)(expected.start / 16), (int)((expected.end + 15) / 16)};
        AlertDialog.Builder builder = new AlertDialog.Builder(this).setTitle("Повтор по исходному звуку")
                .setMessage(original + "\n\nРазбираю фрагмент…")
                .setNegativeButton("Закрыть", null)
                .setNeutralButton("Слушать оригинал", null);
        String key = row.optString("review_key");
        if (!key.isEmpty()) builder.setPositiveButton("Проверено", (dialog, button) -> {
            if (!revision.equals(TranscriptEdits.stamp(note) + "/" + TranscriptEdits.stamp(edits))) return;
            getSharedPreferences("transcript-review", 0).edit().putBoolean(key, true).apply();
            render();
        });
        AlertDialog dialog = builder.create();
        replayDialog = dialog;
        dialog.setOnDismissListener(ignored -> {
            if (replayDialog != dialog) return;
            replayDialog = null;
            if (replay != null) { replay.cancel(); replay = null; }
            if (replayAudioEnd >= 0) {
                replayAudioEnd = -1; replaySeeking = false;
                if (player != null && !ready) releasePlayer();
                else pausePlayback();
            }
        });
        dialog.show();
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(ignored -> {
            replayAudioEnd = range[1];
            replaySeeking = true;
            playAt(range[0]);
        });
        try {
            replay = PhraseReplay.start(this, recording, from, to, anchor, result -> {
                if (replayDialog != dialog || !foreground) return;
                replay = null;
                if (!revision.equals(TranscriptEdits.stamp(note) + "/" + TranscriptEdits.stamp(edits))) {
                    dialog.dismiss();
                    return;
                }
                if (result.startMillis >= 0) { range[0] = result.startMillis; range[1] = result.endMillis; }
                dialog.setMessage("В тексте\n" + original + "\n\nПовтор · " + clock(range[0] / 1000.0)
                        + "–" + clock(range[1] / 1000.0) + "\n" + result.message);
            });
        } catch (java.io.IOException unavailable) {
            dialog.setMessage(original + "\n\n" + unavailable.getMessage());
        }
    }

    private boolean reviewed(JSONObject row) {
        String key = row.optString("review_key");
        return getSharedPreferences("transcript-review", 0).getBoolean(key, row.optBoolean("reviewed"));
    }

    private String idlePlayLabel() {
        return finishedListening ? "С начала" : pendingSeek > 0 ? "Продолжить" : "Слушать";
    }

    private int actualPosition() {
        return ready && !seekPending && !finishedListening ? player.getCurrentPosition() : pendingSeek;
    }

    private void savePosition() {
        if (toggle == null || player == null) return;
        pendingSeek = actualPosition();
        library.savePosition(recording, pendingSeek, ready ? player.getDuration() : 0);
    }

    private void updateSpeedLabel() {
        speedButton.setText(ListeningLibrary.SPEED_LABELS[speedIndex]);
        speedButton.setContentDescription("Скорость воспроизведения " + ListeningLibrary.SPEED_LABELS[speedIndex]);
    }

    private void chooseSpeed() {
        PopupMenu menu = new PopupMenu(this, speedButton);
        for (int i = 0; i < ListeningLibrary.SPEEDS.length; i++)
            menu.getMenu().add(1, i + 1, i, ListeningLibrary.SPEED_LABELS[i]).setCheckable(true).setChecked(i == speedIndex);
        menu.getMenu().setGroupCheckable(1, true, true);
        menu.setOnMenuItemClickListener(item -> {
            speedIndex = item.getItemId() - 1;
            library.speed(speedIndex);
            updateSpeedLabel();
            if (ready && player.isPlaying()) startPlayback();
            StudioStyle.changeAction(speedButton);
            return true;
        });
        menu.show();
    }

    private void playAt(int millis) {
        pendingSeek = Math.max(0, millis);
        finishedListening = false;
        seekPending = true;
        if (ready) {
            player.seekTo(Math.min(pendingSeek, player.getDuration()), MediaPlayer.SEEK_CLOSEST);
            startPlayback();
            return;
        }
        try {
            File audio = Store.audio(this, recording);
            if (!audio.isFile() || toggle == null) {
                showStatus("Аудиокопия недоступна");
                return;
            }
            if (player != null) return;
            status.setVisibility(View.GONE);
            player = new MediaPlayer();
            player.setAudioAttributes(ForegroundAudio.SPEECH);
            player.setDataSource(audio.getPath());
            player.setOnSeekCompleteListener(seekingPlayer -> {
                if (player == seekingPlayer) { replaySeeking = false; seekPending = false; }
            });
            player.setOnPreparedListener(prepared -> {
                if (prepared != player || isFinishing()) return;
                ready = true;
                position.setEnabled(true);
                position.setMax(prepared.getDuration());
                pendingSeek = ListeningLibrary.resumable(pendingSeek, prepared.getDuration());
                prepared.seekTo(pendingSeek, MediaPlayer.SEEK_CLOSEST);
                if (foreground) startPlayback();
            });
            player.setOnCompletionListener(complete -> {
                focus.release();
                finishedListening = true;
                pendingSeek = 0;
                library.savePosition(recording, 0, complete.getDuration());
                complete.seekTo(0);
                toggle.setText(idlePlayLabel());
            });
            player.setOnErrorListener((failed, what, extra) -> {
                releasePlayer();
                toggle.setText("Слушать");
                position.setEnabled(false);
                showStatus("Аудиозапись не открылась");
                return true;
            });
            player.prepareAsync();
        } catch (Exception error) {
            releasePlayer();
            showStatus("Не удалось включить аудиозапись");
        }
    }

    private void refresh() {
        try {
            String revision = TranscriptEdits.stamp(note) + "/" + TranscriptEdits.stamp(edits);
            if (!revision.equals(stamp)) {
                document = new JSONObject(Store.read(note));
                try {
                    TranscriptEdits.apply(document, TranscriptEdits.read(edits), local);
                } catch (Exception ignored) {}
                stamp = revision;
                render();
            }
            updatePendingSummary();
            if (ready && player != null) {
                if (replayAudioEnd >= 0 && !replaySeeking && player.isPlaying() && player.getCurrentPosition() >= replayAudioEnd) {
                    replayAudioEnd = -1;
                    pausePlayback();
                }
                if (player.isPlaying() && !seekPending && SystemClock.elapsedRealtime() >= nextCheckpoint) {
                    savePosition();
                    nextCheckpoint = SystemClock.elapsedRealtime() + 5000;
                }
                int current = actualPosition();
                position.setProgress(current);
                elapsed.setText(clock(current / 1000.0)
                        + " / " + clock(player.getDuration() / 1000.0));
            }
        } catch (Exception error) {
            showStatus("Текст временно недоступен");
        }
        timer.postDelayed(this::refresh, 500);
    }

    private void startPlayback() {
        if (!foreground || !focus.acquire()) {
            if (foreground) showStatus("Аудио занято другим приложением");
            return;
        }
        try {
            player.setPlaybackParams(new PlaybackParams().setSpeed(ListeningLibrary.SPEEDS[speedIndex]).setPitch(1f));
        } catch (IllegalArgumentException unsupported) {
            speedIndex = ListeningLibrary.NORMAL;
            library.speed(speedIndex);
            updateSpeedLabel();
            showStatus("На этом устройстве доступна обычная скорость");
        }
        player.start();
        toggle.setText("Пауза");
    }

    private void pausePlayback() {
        savePosition();
        if (ready && player.isPlaying()) {
            player.pause();
            toggle.setText(idlePlayLabel());
        }
        focus.release();
    }

    private void releasePlayer() {
        focus.release();
        ready = false;
        if (player != null) {
            player.release();
            player = null;
        }
    }

    @Override public void onSaveInstanceState(Bundle state) {
        super.onSaveInstanceState(state);
        state.putString("reader_tab", chooseReadingTab ? "read" : tab);
        state.putString("text_query", searchQuery);
        state.putString("reader_review_kind", reviewKind);
        state.putInt("review_page", reviewPage);
        state.putInt("reader_seek", actualPosition());
        state.putBoolean("reader_finished", finishedListening);
        if (scroll != null) state.putInt("reader_scroll", scroll.getScrollY());
    }

    @Override protected void onStart() {
        super.onStart();
        if (note != null) CaptureService.screenStarted();
    }

    @Override public void onResume() {
        super.onResume();
        foreground = true;
        if (note != null) {
            CaptureService.resumeSync(this);
            refresh();
        }
    }

    @Override public void onPause() {
        foreground = false;
        if (replayDialog != null) replayDialog.dismiss();
        if (searchDialog != null) searchDialog.dismiss();
        timer.removeCallbacksAndMessages(null);
        pausePlayback();
        super.onPause();
    }

    @Override protected void onStop() {
        if (note != null) CaptureService.screenStopped();
        super.onStop();
    }

    @Override public void onDestroy() {
        timer.removeCallbacksAndMessages(null);
        releasePlayer();
        super.onDestroy();
    }

    private void showStatus(String value) {
        if (!value.contentEquals(status.getText())) status.setText(value);
        status.setVisibility(View.VISIBLE);
    }

    static String clock(double value) {
        long seconds = Math.max(0, (long) value);
        return seconds >= 3600 ? String.format(Locale.US, "%02d:%02d:%02d", seconds / 3600, seconds / 60 % 60, seconds % 60)
                : String.format(Locale.US, "%02d:%02d", seconds / 60, seconds % 60);
    }

    private int dp(int value) {
        return Math.round(getResources().getDisplayMetrics().density * value);
    }

    private LinearLayout column() {
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        return column;
    }

    private LinearLayout card() {
        LinearLayout card = column();
        card.setPadding(dp(14), dp(12), dp(14), dp(12));
        card.setBackground(StudioStyle.card(this, 18));
        return card;
    }

    private void divider(LinearLayout host) {
        View divider = new View(this);
        divider.setBackgroundColor(DIVIDER);
        host.addView(divider, new LinearLayout.LayoutParams(-1, dp(1)));
    }

    private TextView text(String value, int size, int color) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        text.setLineSpacing(dp(3), 1);
        return text;
    }

    private TextView heading(String value, int size) {
        TextView heading = text(value, size, TEXT);
        heading.setTypeface(Typeface.create("serif", Typeface.NORMAL));
        return heading;
    }

    private Button button(String value, Runnable action) {
        Button button = button(value);
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private Button button(String value) {
        Button button = new Button(this);
        button.setStateListAnimator(null);
        button.setText(value);
        button.setTextSize(14);
        button.setMinHeight(dp(48));
        button.setMinimumHeight(dp(48));
        button.setAllCaps(false);
        button.setTextColor(TEXT);
        button.setPadding(dp(10), 0, dp(10), 0);
        button.setBackground(control(CONTROL));
        return button;
    }

    private GradientDrawable surface(int color, int radius) {
        GradientDrawable surface = new GradientDrawable();
        surface.setColor(color);
        surface.setCornerRadius(dp(radius));
        return surface;
    }

    private RippleDrawable control(int color) {
        return new RippleDrawable(ColorStateList.valueOf(0x2880e2ce), surface(color, 12), null);
    }

    private LinearLayout.LayoutParams spaced(int width, int height, int gap) {
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(width, height);
        layout.topMargin = dp(gap);
        return layout;
    }

    private LinearLayout.LayoutParams withGap(int width, int height, int gap) {
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(width, height);
        layout.setMarginStart(dp(gap));
        return layout;
    }
}
