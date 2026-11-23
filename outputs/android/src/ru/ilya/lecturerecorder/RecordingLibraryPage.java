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

import org.json.JSONObject;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
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
    private final CheckBox waiting;
    private final ExecutorService catalogReader = Executors.newSingleThreadExecutor();
    private boolean reading, refreshAgain, disposed;
    private final ListView list;
    private final ArrayAdapter<Entry> adapter;
    private final Button importButton;
    private final Button recordButton;
    private final TextView empty;
    private final TextView status;
    private final LinearLayout outcome;
    private final TextView outcomeLabel;
    private final Button outcomeAction;
    private Runnable openOutcome;
    private List<Entry> entries = Collections.emptyList();

    RecordingLibraryPage(Context context, Runnable importAudio, Runnable record, Consumer<Entry> open) {
        super(context);
        setOrientation(VERTICAL);
        int inset = dp(StudioStyle.PAGE_INSET);
        setPadding(inset, dp(12), inset, dp(8));
        LinearLayout header = new LinearLayout(context);
        boolean wide = getResources().getConfiguration().screenWidthDp >= 480;
        header.setOrientation(wide ? HORIZONTAL : VERTICAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = StudioStyle.title(context, "Библиотека");
        header.addView(title, new LayoutParams(wide ? 0 : -1, -2, wide ? 1 : 0));
        importButton = StudioStyle.action(context, "Импорт аудио", importAudio, true);
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
            StudioStyle.actionTone(importButton, StudioStyle.ACCENT, StudioStyle.INK);
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
        addView(query, spaced(8));
        query.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) { filter(); }
            @Override public void afterTextChanged(Editable text) {}
        });

        waiting = new CheckBox(context);
        waiting.setText("Ждёт разбора");
        waiting.setTextColor(StudioStyle.TEXT);
        waiting.setButtonTintList(ColorStateList.valueOf(StudioStyle.ACCENT));
        waiting.setMinHeight(dp(StudioStyle.ACTION_HEIGHT));
        waiting.setOnCheckedChangeListener((button, checked) -> filter());
        addView(waiting, spaced(2));

        empty = text("", 15, StudioStyle.MUTED);
        addView(empty, spaced(12));
        recordButton = StudioStyle.action(context, "К записи пары", record, false);
        addView(recordButton, spaced(8));

        list = new ListView(context);
        list.setDivider(new ColorDrawable(Color.TRANSPARENT));
        list.setDividerHeight(dp(6));
        adapter = new ArrayAdapter<Entry>(context, 0) {
            @Override public View getView(int position, View previous, ViewGroup parent) {
                Row row = previous == null ? new Row(context) : (Row) previous;
                Entry item = getItem(position);
                row.title.setText(item.title);
                row.details.setText(item.details);
                row.details.setTextColor(item.pending ? StudioStyle.WARNING : StudioStyle.MUTED);
                row.setContentDescription(item.title + ". " + item.details);
                return row;
            }
        };
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
        StudioStyle.actionTone(importButton, open == null ? StudioStyle.ACCENT : StudioStyle.CONTROL,
                open == null ? StudioStyle.INK : StudioStyle.TEXT);
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

    void restoreQuery(String saved, boolean onlyWaiting) {
        query.setText(saved);
        waiting.setChecked(onlyWaiting);
    }

    private static String normalize(String value) {
        return value.toLowerCase(Locale.ROOT).replace('ё', 'е');
    }

    private static String index(String file, String title, String details) {
        String date = file.substring("lecture-".length());
        String numeric = "";
        if (date.length() >= 10) {
            numeric = date.substring(0, 10) + " " + date.substring(8, 10) + "." + date.substring(5, 7)
                    + "." + date.substring(0, 4);
        }
        return normalize(title + " " + details + " " + numeric);
    }

    private void filter() {
        String[] words = normalize(query.getText().toString().trim()).split("\\s+");
        List<Entry> visible = new ArrayList<>();
        for (Entry entry : entries) {
            if (waiting.isChecked() && !entry.awaitingText) continue;
            boolean matches = true;
            for (String word : words) {
                if (!entry.search.contains(word)) {
                    matches = false;
                    break;
                }
            }
            if (matches) visible.add(entry);
        }
        adapter.setNotifyOnChange(false);
        adapter.clear();
        adapter.addAll(visible);
        adapter.notifyDataSetChanged();
        query.setVisibility(entries.isEmpty() ? GONE : VISIBLE);
        waiting.setVisibility(entries.isEmpty() ? GONE : VISIBLE);
        empty.setVisibility(visible.isEmpty() ? VISIBLE : GONE);
        empty.setText(entries.isEmpty() ? "Записей пока нет. Запиши пару или импортируй аудиофайл." : "Записи не найдены.");
        recordButton.setVisibility(entries.isEmpty() ? VISIBLE : GONE);
        list.setVisibility(visible.isEmpty() ? GONE : VISIBLE);
    }

    private static List<Entry> collect(Context context) {
        TreeMap<String, Entry> records = new TreeMap<>(Collections.reverseOrder());
        for (File file : Store.audioFiles(context)) {
            String name = file.getName();
            long seconds = Math.max(0, file.length() - 44) / (PcmWave.SAMPLE_RATE * 2);
            boolean notes = LectureNotes.file(context, name, true).isFile() || LectureNotes.file(context, name, false).isFile();
            String details = Store.recordingTitle(name) + " · " + LectureReaderActivity.clock(seconds);
            if (!notes) details += " · Ждёт разбора";
            records.put(name, new Entry(name, title(context, name, file), details, false, !notes));
        }
        for (boolean local : new boolean[]{true, false}) {
            for (File note : LectureNotes.files(context, local)) {
                String name = note.getName().substring(0, note.getName().length() - 5);
                if (LectureNotes.valid(name) && !records.containsKey(name)) {
                    records.put(name, new Entry(name, title(context, name, Store.audio(context, name)),
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
                    // A transfer or a completed choice may have removed it during refresh.
                }
            }
        }
        return new ArrayList<>(records.values());
    }

    static String title(Context context, String name, File audio) {
        try {
            String subject = Store.lesson(context, name).optString("subject").trim();
            if (!subject.isEmpty()) return subject;
        } catch (Exception ignored) {}
        try {
            JSONObject metadata = Store.readObject(new File(audio.getPath() + ".json"));
            String imported = metadata.optString("title").trim();
            if (metadata.optBoolean("imported") && !imported.isEmpty()) return imported;
        } catch (Exception ignored) {}
        return "Запись пары";
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
        final TextView title = text("", 16, StudioStyle.TEXT);
        final TextView details = text("", 13, StudioStyle.MUTED);

        Row(Context context) {
            super(context);
            setOrientation(HORIZONTAL);
            setGravity(Gravity.CENTER_VERTICAL);
            setMinimumHeight(dp(64));
            if (android.os.Build.VERSION.SDK_INT >= 28) setScreenReaderFocusable(true);
            setPadding(dp(12), dp(8), dp(12), dp(8));
            setBackground(StudioStyle.control(context, StudioStyle.PANEL, 12));
            LinearLayout content = new LinearLayout(context);
            content.setOrientation(VERTICAL);
            title.setTypeface(Typeface.DEFAULT_BOLD);
            title.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            details.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            content.addView(title);
            content.addView(details);
            addView(content, new LayoutParams(0, -2, 1));
            TextView arrow = text("›", 22, StudioStyle.ACCENT);
            arrow.setPadding(dp(8), 0, 0, 0);
            arrow.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            addView(arrow);
        }
    }
}
