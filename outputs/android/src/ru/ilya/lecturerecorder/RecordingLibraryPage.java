package ru.ilya.lecturerecorder;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.content.res.ColorStateList;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;


import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;
import java.util.TreeMap;
import java.util.function.Consumer;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

final class RecordingLibraryPage extends LinearLayout {
    static final class Entry {
        final String file, title, details, search;
        final boolean pending, awaitingText;

        Entry(String file, String title, String details, boolean pending, boolean awaitingText) {
            this.file = file;
            this.title = title;
            this.details = details;
            this.pending = pending;
            this.awaitingText = awaitingText;
            search = index(file, title, details);
        }

        @Override public boolean equals(Object other) {
            if (!(other instanceof Entry)) return false;
            Entry entry = (Entry) other;
            return pending == entry.pending && awaitingText == entry.awaitingText && file.equals(entry.file) && title.equals(entry.title)
                    && details.equals(entry.details);
        }

        @Override public int hashCode() {
            return Objects.hash(file, title, details, pending, awaitingText);
        }
    }

    private final EditText query;
    private final CheckBox waiting, starred;
    private final ListeningLibrary library;
    private final LinearLayout searchBar, filters;
    private final Button clear, reset;
    private final ExecutorService catalogReader = Executors.newSingleThreadExecutor();
    private boolean reading, refreshAgain, disposed;
    private final ListView list;
    private final ArrayAdapter<Entry> adapter;
    private final Button importButton;
    private final TextView empty;
    private final TextView status;
    private final LinearLayout outcome;
    private final TextView outcomeLabel;
    private final Button outcomeAction;
    private Runnable openOutcome;
    private List<Entry> entries = Collections.emptyList();
    private final android.util.LruCache<String, String> noteTitles = new android.util.LruCache<>(128);

    RecordingLibraryPage(Context context, Runnable importAudio, Consumer<Entry> open) {
        super(context);
        library = new ListeningLibrary(context);
        setOrientation(VERTICAL);
        int inset = dp(StudioStyle.PAGE_INSET);
        setPadding(inset, dp(12), inset, dp(8));
        LinearLayout header = new LinearLayout(context);
        boolean wide = getResources().getConfiguration().screenWidthDp >= 345
                && getResources().getConfiguration().fontScale <= 1.30f;
        header.setOrientation(wide ? HORIZONTAL : VERTICAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = StudioStyle.title(context, "Библиотека");
        header.addView(title, new LayoutParams(wide ? 0 : -1, -2, wide ? 1 : 0));
        importButton = StudioStyle.action(context, "Импорт", importAudio, false);
        importButton.setContentDescription("Импортировать аудио");
        header.addView(importButton, new LayoutParams(wide ? -2 : -1, -2));
        addView(header);

        status = text("", 14, StudioStyle.MUTED);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        status.setVisibility(GONE);
        addView(status, spaced(6));
        outcome = new LinearLayout(context);
        outcome.setOrientation(VERTICAL);
        outcome.setBackground(StudioStyle.card(context, 12));
        outcome.setPadding(dp(10), dp(6), dp(10), dp(6));
        outcomeLabel = text("", 14, StudioStyle.TEXT);
        outcomeLabel.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        outcome.addView(outcomeLabel);
        outcomeAction = StudioStyle.action(context, "Открыть запись", () -> {
            Runnable action = openOutcome;
            if (action == null) return;
            outcome.setVisibility(GONE);
            openOutcome = null;
            action.run();
        }, true);
        outcome.addView(outcomeAction, spaced(4));
        outcome.setVisibility(GONE);
        addView(outcome, spaced(6));
        query = new EditText(context);
        query.setSingleLine();
        query.setInputType(InputType.TYPE_CLASS_TEXT);
        query.setHint("Найти запись");
        query.setContentDescription("Поиск по записям");
        query.setTextColor(StudioStyle.TEXT);
        query.setHintTextColor(StudioStyle.MUTED);
        query.setTextSize(15);
        query.setPadding(dp(12), dp(4), dp(12), dp(4));
        query.setMinHeight(dp(StudioStyle.ACTION_HEIGHT));
        query.setBackground(StudioStyle.control(context, StudioStyle.CONTROL, 12));
        searchBar = new LinearLayout(context);
        searchBar.setGravity(Gravity.CENTER_VERTICAL);
        searchBar.addView(query, new LayoutParams(0, -2, 1));
        clear = StudioStyle.action(context, "×", () -> query.setText(""), false);
        clear.setTextSize(22);
        clear.setContentDescription("Очистить поиск");
        LayoutParams clearSize = new LayoutParams(dp(48), dp(48));
        clearSize.setMarginStart(dp(4));
        searchBar.addView(clear, clearSize);
        addView(searchBar, spaced(8));
        query.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) { filter(); }
            @Override public void afterTextChanged(Editable text) {}
        });

        filters = new LinearLayout(context);
        boolean stacked = getResources().getConfiguration().screenWidthDp < 345
                || getResources().getConfiguration().fontScale > 1.25f;
        filters.setOrientation(stacked ? VERTICAL : HORIZONTAL);
        starred = filterControl(context, "Избранное");
        waiting = filterControl(context, "Ждёт разбора");
        filters.addView(starred, new LayoutParams(stacked ? -1 : -2, -2));
        filters.addView(waiting, new LayoutParams(stacked ? -1 : -2, -2));
        addView(filters, spaced(2));

        empty = text("", 15, StudioStyle.MUTED);
        empty.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        addView(empty, spaced(12));
        reset = StudioStyle.action(context, "Сбросить фильтры", () -> {
            query.setText("");
            waiting.setChecked(false);
            starred.setChecked(false);
        }, false);
        addView(reset, spaced(6));

        list = new ListView(context);
        list.setDivider(new ColorDrawable(StudioStyle.LINE));
        list.setDividerHeight(dp(1));
        adapter = new ArrayAdapter<Entry>(context, 0) {
            @Override public View getView(int position, View previous, ViewGroup parent) {
                Row row = previous == null ? new Row(context) : (Row) previous;
                Entry item = getItem(position);
                row.title.setText(item.title);
                row.details.setText(item.details);
                row.details.setTextColor(item.pending ? StudioStyle.WARNING : StudioStyle.MUTED);
                row.content.setContentDescription(item.title + ". " + item.details);
                row.content.setOnClickListener(view -> open.accept(item));
                boolean pinned = library.favorite(item.file);
                row.star.setChecked(pinned);
                row.star.setText(pinned ? "★" : "☆");
                row.star.setTextColor(pinned ? StudioStyle.ACCENT : StudioStyle.MUTED);
                row.star.setContentDescription((pinned ? "Убрать из избранного. " : "Добавить в избранное. ") + item.title);
                row.star.setOnClickListener(view -> {
                    boolean selected = row.star.isChecked();
                    library.favorite(item.file, selected);
                    row.star.announceForAccessibility(selected ? "Добавлено в избранное" : "Убрано из избранного");
                    StudioStyle.changeAction(row.star);
                    filter();
                });
                return row;
            }
        };
        list.setItemsCanFocus(true);
        list.setAdapter(adapter);
        list.setOnItemClickListener((parent, row, index, id) -> open.accept(adapter.getItem(index)));
        LayoutParams rows = new LayoutParams(-1, 0, 1);
        rows.topMargin = dp(8);
        addView(list, rows);
        filter();
    }

    void showOutcome(String message, Runnable open) {
        openOutcome = open;
        outcomeLabel.setText(message);
        outcomeAction.setVisibility(open == null ? GONE : VISIBLE);
        outcome.setVisibility(VISIBLE);
    }

    void refresh() {
        String message = AudioImport.status;
        if (!message.contentEquals(status.getText())) status.setText(message);
        status.setVisibility(message.isEmpty() ? GONE : VISIBLE);
        status.setTextColor(message.startsWith("Не удалось") ? StudioStyle.RECORDING : StudioStyle.MUTED);
        importButton.setEnabled(!AudioImport.busy);
        if (disposed) return;
        if (reading) {
            refreshAgain = true;
            return;
        }
        reading = true;
        catalogReader.execute(() -> {
            List<Entry> latest = collect(getContext());
            post(() -> {
                if (disposed) return;
                reading = false;
                if (!latest.equals(entries)) {
                    entries = latest;
                    filter();
                }
                if (refreshAgain) {
                    refreshAgain = false;
                    refresh();
                }
            });
        });
    }

    void dispose() {
        disposed = true;
        catalogReader.shutdownNow();
    }

    String queryText() {
        return query.getText().toString();
    }

    boolean waitingOnly() { return waiting.isChecked(); }

    boolean favoritesOnly() { return starred.isChecked(); }

    void restoreQuery(String saved, boolean onlyWaiting, boolean onlyFavorites) {
        query.setText(saved);
        waiting.setChecked(onlyWaiting);
        starred.setChecked(onlyFavorites);
    }

    private CheckBox filterControl(Context context, String title) {
        CheckBox button = new CheckBox(context);
        button.setText(title);
        button.setTextColor(StudioStyle.TEXT);
        button.setButtonTintList(ColorStateList.valueOf(StudioStyle.ACCENT));
        button.setMinHeight(dp(StudioStyle.ACTION_HEIGHT));
        button.setOnCheckedChangeListener((view, checked) -> filter());
        return button;
    }

    private static String index(String file, String title, String details) {
        String date = file.substring("lecture-".length());
        String numeric = "";
        if (date.length() >= 10) {
            numeric = date.substring(0, 10) + " " + date.substring(8, 10) + "." + date.substring(5, 7)
                    + "." + date.substring(0, 4);
        }
        return ListeningLibrary.normalize(title + " " + details + " " + numeric);
    }

    private void filter() {
        String[] words = ListeningLibrary.terms(query.getText().toString());
        List<Entry> visible = new ArrayList<>();
        for (Entry entry : entries) {
            if (starred.isChecked() && !library.favorite(entry.file)) continue;
            if (waiting.isChecked() && !entry.awaitingText) continue;
            if (ListeningLibrary.matches(entry.search, words)) visible.add(entry);
        }
        adapter.setNotifyOnChange(false);
        adapter.clear();
        adapter.addAll(visible);
        adapter.notifyDataSetChanged();
        searchBar.setVisibility(entries.isEmpty() ? GONE : VISIBLE);
        clear.setVisibility(query.length() == 0 ? GONE : VISIBLE);
        filters.setVisibility(entries.isEmpty() ? GONE : VISIBLE);
        empty.setVisibility(visible.isEmpty() ? VISIBLE : GONE);
        String explanation = "Пока нет записей. Здесь появится аудио, которое ты запишешь или импортируешь.";
        if (!entries.isEmpty()) {
            if (words.length > 0) explanation = "По этому запросу записей нет.";
            else if (starred.isChecked() && waiting.isChecked()) explanation = "В избранном нет записей, которые ждут разбора.";
            else if (starred.isChecked()) explanation = "В избранном пока пусто. Нажми на звезду рядом с нужной записью.";
            else explanation = "Все записи уже разобраны.";
        }
        if (!explanation.contentEquals(empty.getText())) empty.setText(explanation);
        reset.setVisibility(!entries.isEmpty() && visible.isEmpty() ? VISIBLE : GONE);
        list.setVisibility(visible.isEmpty() ? GONE : VISIBLE);
    }

    private List<Entry> collect(Context context) {
        TreeMap<String, Entry> records = new TreeMap<>(Collections.reverseOrder());
        for (File file : Store.audioFiles(context)) {
            String name = file.getName();
            long seconds = Math.max(0, file.length() - 44) / (PcmWave.SAMPLE_RATE * 2);
            boolean notes = LectureNotes.file(context, name, true).isFile() || LectureNotes.file(context, name, false).isFile();
            String details = Store.recordingTitle(name) + " · " + LectureReaderActivity.clock(seconds);
            details += notes ? " · Аудио и текст" : " · Ждёт разбора";
            records.put(name, new Entry(name, catalogTitle(context, name, file), details, false, !notes));
        }
        for (boolean local : new boolean[]{true, false}) {
            for (File note : LectureNotes.files(context, local)) {
                String name = note.getName().substring(0, note.getName().length() - 5);
                if (LectureNotes.valid(name) && !records.containsKey(name)) {
                    records.put(name, new Entry(name, catalogTitle(context, name, Store.audio(context, name)),
                            Store.recordingTitle(name) + " · Только текст", false, false));
                }
            }
        }
        File[] pending = Store.root(context).listFiles(file -> LectureNotes.valid(file.getName()) && file.isFile());
        if (pending != null) {
            for (File file : pending) {
                String name = file.getName();
                if (records.containsKey(name)) continue;
                try {
                    Store.pendingMetadata(context, name);
                    String draft = RecordingLessonFlow.draftTitle(context, name);
                    records.put(name, new Entry(name, draft.isEmpty() ? "Запись пары" : draft,
                            Store.recordingTitle(name) + " · Выбрать пару", true, false));
                } catch (Exception ignored) {
                }
            }
        }
        return new ArrayList<>(records.values());
    }

    private String catalogTitle(Context context, String name, File audio) {
        String named = Store.recordingName(context, name, audio);
        if (!named.isEmpty()) return named;
        File note = LectureNotes.file(context, name, true);
        if (!note.isFile()) note = LectureNotes.file(context, name, false);
        if (note.isFile()) {
            String revision = note.getPath() + ":" + note.lastModified() + ":" + note.length();
            String topic = noteTitles.get(revision);
            if (topic == null) {
                topic = "";
                try {
                    org.json.JSONObject report = Store.readObject(note).optJSONObject("report");
                    if (report != null) {
                        topic = report.optString("topic").trim();
                        if (topic.isEmpty()) topic = report.optString("subject").trim();
                    }
                } catch (Exception ignored) {}
                noteTitles.put(revision, topic);
            }
            if (!topic.isEmpty()) return topic;
        }
        return "Запись пары";
    }

    static String title(Context context, String name, File audio) {
        String title = Store.recordingName(context, name, audio);
        return title.isEmpty() ? "Запись пары" : title;
    }

    private LayoutParams spaced(int gap) {
        LayoutParams params = new LayoutParams(-1, -2);
        params.topMargin = dp(gap);
        return params;
    }

    private int dp(int value) { return StudioStyle.dp(getContext(), value); }

    private TextView text(String value, int size, int color) {
        TextView text = new TextView(getContext());
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        return text;
    }

    private final class Row extends LinearLayout {
        final TextView title = text("", 19, StudioStyle.TEXT);
        final TextView details = text("", 13, StudioStyle.MUTED);
        final LinearLayout content;
        final CheckBox star;

        Row(Context context) {
            super(context);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setMinimumHeight(dp(72));
            setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            setPadding(dp(12), dp(8), dp(12), dp(8));
            setBackgroundColor(StudioStyle.PANEL);
            content = new LinearLayout(context);
            content.setOrientation(VERTICAL);
            content.setGravity(Gravity.CENTER_VERTICAL);
            content.setMinimumHeight(dp(48));
            content.setFocusable(true);
            content.setBackground(StudioStyle.control(context, StudioStyle.PANEL, 8));
            title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
            title.setLetterSpacing(-.02f);
            details.setPadding(0, dp(4), 0, 0);
            title.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            details.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            content.addView(title);
            content.addView(details);
            addView(content, new LayoutParams(0, -2, 1));
            star = new CheckBox(context);
            star.setButtonDrawable((android.graphics.drawable.Drawable) null);
            star.setTextSize(23);
            star.setGravity(Gravity.CENTER);
            star.setPadding(0, 0, 0, 0);
            star.setBackground(StudioStyle.control(context, Color.TRANSPARENT, 10));
            LayoutParams starSize = new LayoutParams(dp(48), dp(48));
            starSize.setMarginStart(dp(8));
            addView(star, starSize);
        }
    }
}
