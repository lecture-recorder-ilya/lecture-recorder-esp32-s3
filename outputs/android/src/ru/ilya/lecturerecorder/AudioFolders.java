package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.Dialog;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.text.InputFilter;
import android.text.InputType;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.HapticFeedbackConstants;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.BiConsumer;
import java.util.function.Supplier;

/** Folder membership and tile positions are stored independently of the recordings. */
final class AudioFolders extends LinearLayout {
    private static final String[] COLORS = {"#AA9AF8", "#70C9D0", "#F5A9BF", "#F0B876", "#A9CE9B", "#B5B7C2"};
    private static final String[] COLOR_NAMES = {"Сиреневый", "Бирюзовый", "Розовый", "Янтарный", "Зелёный", "Серый"};
    private static final String[] ICONS = {"📁", "🎓", "📚", "🎙", "⭐", "💡", "🎵", "📌"};
    private static final String[] ICON_NAMES = {"Папка", "Учёба", "Книги", "Микрофон", "Звезда", "Идеи", "Музыка", "Закладка"};

    private final Activity activity;
    private final Supplier<List<ChoiceDropdown.Option>> recordings;
    private final Runnable onFoldersChanged;
    private final BiConsumer<String, String> onRecording;
    private String current = "";
    private Dialog dialog;
    private ScrollView scroll;
    private int libraryScroll;

    AudioFolders(Activity activity, Supplier<List<ChoiceDropdown.Option>> recordings,
                 Runnable onFoldersChanged, BiConsumer<String, String> onRecording) {
        super(activity);
        this.activity = activity;
        this.recordings = recordings;
        this.onFoldersChanged = onFoldersChanged;
        this.onRecording = onRecording;
        setOrientation(VERTICAL);
        setPadding(0, dp(10), 0, 0);
        setBackgroundColor(StudioStyle.BACKGROUND);
    }

    void open(String id, int scrollY) {
        current = exists(activity, id) ? id : "";
        render(scrollY);
    }

    boolean back() {
        if (current.isEmpty()) return false;
        showLibrary();
        return true;
    }

    String current() { return current; }
    int scrollY() { return scroll == null ? 0 : scroll.getScrollY(); }
    int libraryScroll() { return current.isEmpty() && isShown() ? scrollY() : libraryScroll; }
    void setLibraryScroll(int value) { libraryScroll = value; }

    private void showLibrary() {
        open("", libraryScroll);
    }

    private static JSONArray load(Activity activity) {
        try {
            return new JSONArray(activity.getSharedPreferences("audio_folders", 0).getString("folders", "[]"));
        } catch (JSONException malformed) {
            return new JSONArray();
        }
    }

    private static int indexOf(JSONArray folders, String id) {
        for (int i = 0; i < folders.length(); i++) {
            JSONObject folder = folders.optJSONObject(i);
            if (folder != null && id.equals(folder.optString("id"))) return i;
        }
        return -1;
    }

    private static JSONObject find(Activity activity, String id) {
        JSONArray folders = load(activity);
        return folders.optJSONObject(indexOf(folders, id));
    }

    static boolean exists(Activity activity, String id) {
        return id != null && !id.isEmpty() && find(activity, id) != null;
    }

    static String recordingTitle(Activity activity, String id, String key, String fallback) {
        return alias(find(activity, id), key, fallback);
    }

    static List<ChoiceDropdown.Option> recordingsIn(Activity activity, String id, List<ChoiceDropdown.Option> options) {
        return recordingsIn(find(activity, id), options);
    }

    private static List<ChoiceDropdown.Option> recordingsIn(JSONObject folder, List<ChoiceDropdown.Option> options) {
        Set<String> names = files(folder);
        List<ChoiceDropdown.Option> available = new ArrayList<>();
        for (ChoiceDropdown.Option item : options) {
            if (names.contains(item.value)) {
                available.add(new ChoiceDropdown.Option(item.value, alias(folder, item.value, item.title), item.detail));
            }
        }
        return available;
    }

    private static String alias(JSONObject folder, String key, String fallback) {
        JSONObject names = folder == null ? null : folder.optJSONObject("names");
        return names == null ? fallback : names.optString(key, fallback);
    }

    private static Set<String> files(JSONObject folder) {
        Set<String> result = new LinkedHashSet<>();
        JSONArray names = folder == null ? null : folder.optJSONArray("files");
        if (names != null) for (int i = 0; i < names.length(); i++) {
            String name = names.optString(i);
            if (LectureNotes.valid(name)) result.add(name);
        }
        return result;
    }

    private boolean save(JSONArray data) {
        boolean ok = activity.getSharedPreferences("audio_folders", 0).edit().putString("folders", data.toString()).commit();
        if (ok) onFoldersChanged.run();
        else Toast.makeText(activity, "Не удалось сохранить папки", Toast.LENGTH_LONG).show();
        return ok;
    }

    private void render(int scrollY) {
        removeAllViews();
        JSONObject folder = find(activity, current);
        if (folder == null) {
            current = "";
        }
        LinearLayout heading = new LinearLayout(activity);
        heading.setGravity(Gravity.CENTER_VERTICAL);
        if (folder == null) {
            TextView label = heading("Папки", 23);
            heading.addView(label, new LinearLayout.LayoutParams(0, -2, 1));
            heading.addView(button("＋ Новая папка", () -> editFolder(null), StudioStyle.ACTIVE));
        } else {
            heading.addView(button("‹ Папки", this::showLibrary, StudioStyle.CONTROL));
            heading.addView(new View(activity), new LinearLayout.LayoutParams(0, 1, 1));
            Button actions = button("⋯", this::folderActions, StudioStyle.CONTROL);
            actions.setContentDescription("Действия с папкой");
            heading.addView(actions, new LinearLayout.LayoutParams(dp(48), dp(48)));
        }
        addView(heading, new LinearLayout.LayoutParams(-1, -2));

        scroll = new ScrollView(activity);
        scroll.setClipToPadding(false);
        LinearLayout content = column();
        content.setPadding(0, 0, 0, dp(12));
        scroll.addView(content);
        addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        if (folder == null) renderLibrary(content);
        else renderFolder(content, folder);
        ScrollView shown = scroll;
        if (scrollY > 0) shown.post(() -> shown.scrollTo(0, scrollY));
    }

    private void renderLibrary(LinearLayout content) {
        JSONArray folders = load(activity);
        LinearLayout row = null;
        int count = 0;
        int columns = getResources().getConfiguration().screenWidthDp >= 620 ? 3 : 2;
        for (int i = 0; i < folders.length(); i++) {
            JSONObject folder = folders.optJSONObject(i);
            if (folder == null) continue;
            if (count % columns == 0) {
                row = new LinearLayout(activity);
                row.setBaselineAligned(false);
                append(content, row, 8);
            }
            String id = folder.optString("id");
            int color = color(folder);
            LinearLayout tile = column();
            tile.setPadding(dp(12), dp(10), dp(12), dp(10));
            tile.setBackground(tintedCard(color));
            TextView icon = text(folder.optString("icon", ICONS[0]), 24, color);
            tile.addView(icon);
            TextView name = heading(folder.optString("name"), 16);
            name.setMaxLines(2);
            name.setEllipsize(TextUtils.TruncateAt.END);
            append(tile, name, 5);
            TextView size = text(recordingCount(files(folder).size()), 12, color);
            append(tile, size, 4);
            tile.setFocusable(true);
            tile.setContentDescription(folder.optString("name") + ", " + size.getText());
            tile.setOnClickListener(view -> {
                libraryScroll = scrollY();
                open(id, 0);
            });
            tile.setOnLongClickListener(view -> {
                editFolder(id);
                return true;
            });
            LinearLayout.LayoutParams cell = new LinearLayout.LayoutParams(0, dp(115), 1);
            if (count % columns > 0) cell.setMarginStart(dp(8));
            row.addView(tile, cell);
            count++;
        }
        if (row != null && count % columns != 0) {
            for (int i = count % columns; i < columns; i++) {
                LinearLayout.LayoutParams space = new LinearLayout.LayoutParams(0, 0, 1);
                space.setMarginStart(dp(8));
                row.addView(new View(activity), space);
            }
        }
    }

    private static String recordingCount(int count) {
        int units = count % 10;
        int tens = count % 100;
        String noun = tens >= 11 && tens <= 14 ? "записей"
                : units == 1 ? "запись" : units >= 2 && units <= 4 ? "записи" : "записей";
        return count + " " + noun;
    }

    private void renderFolder(LinearLayout content, JSONObject folder) {
        int accent = color(folder);
        LinearLayout cover = column();
        cover.setPadding(dp(14), dp(12), dp(14), dp(12));
        cover.setBackground(tintedCard(accent));
        cover.addView(text(folder.optString("icon", ICONS[0]), 24, accent));
        append(cover, heading(folder.optString("name"), 25), 4);
        append(content, cover, 10);

        append(content, button("＋ Записи", this::chooseFiles, StudioStyle.CONTROL), 10);
        append(content, text("Удержи карточку для переименования или переноса. Потяни угол для размера. Удержи пустое место для надписи.",
                13, StudioStyle.MUTED), 8);

        Board board = new Board(accent, layout(folder));
        for (ChoiceDropdown.Option option : recordingsIn(folder, recordings.get())) board.addRecording(option);
        JSONObject labels = folder.optJSONObject("labels");
        if (labels != null) {
            labels.keys().forEachRemaining(key -> board.addLabel(key, labels.optString(key)));
        }
        append(content, board, 10);
    }

    private static Map<String, FolderLayout.Tile> layout(JSONObject folder) {
        Map<String, FolderLayout.Tile> placed = new LinkedHashMap<>();
        Set<String> keys = files(folder);
        JSONObject labels = folder.optJSONObject("labels");
        if (labels != null) labels.keys().forEachRemaining(keys::add);
        JSONObject data = folder.optJSONObject("tiles");
        for (String name : keys) {
            JSONObject saved = data == null ? null : data.optJSONObject(name);
            if (saved == null) continue;
            FolderLayout.Tile tile = new FolderLayout.Tile(saved.optInt("column"), Math.min(4000, saved.optInt("row")),
                    saved.optInt("width", 2), saved.optInt("height", 1));
            if (FolderLayout.fits(placed, tile)) placed.put(name, tile);
        }
        for (String name : keys) {
            if (!placed.containsKey(name)) placed.put(name, FolderLayout.firstFree(placed, 0, 2, 1));
        }
        return placed;
    }

    private void saveLayout(String key, FolderLayout.Tile target) {
        JSONArray folders = load(activity);
        JSONObject folder = folders.optJSONObject(indexOf(folders, current));
        if (folder == null) return;
        Map<String, FolderLayout.Tile> previous = layout(folder);
        if (!previous.containsKey(key)) return;
        try {
            putLayout(folder, FolderLayout.change(previous, key, target));
            if (save(folders)) render(scrollY());
        } catch (JSONException error) {
            Toast.makeText(activity, "Не удалось сохранить раскладку", Toast.LENGTH_SHORT).show();
        }
    }

    private static void putLayout(JSONObject folder, Map<String, FolderLayout.Tile> tiles) throws JSONException {
        JSONObject data = new JSONObject();
        for (Map.Entry<String, FolderLayout.Tile> entry : tiles.entrySet()) {
            FolderLayout.Tile tile = entry.getValue();
            data.put(entry.getKey(), new JSONObject().put("column", tile.column).put("row", tile.row)
                    .put("width", tile.width).put("height", tile.height));
        }
        folder.put("tiles", data);
    }

    private void renameRecording(ChoiceDropdown.Option option) {
        LinearLayout form = form("Переименовать запись");
        EditText field = input(option.title, 80, false);
        field.setHint("Название записи");
        append(form, field, 12);
        append(form, button("Сохранить", () -> {
            JSONArray folders = load(activity);
            JSONObject folder = folders.optJSONObject(indexOf(folders, current));
            if (folder == null || !files(folder).contains(option.value)) return;
            try {
                JSONObject names = folder.optJSONObject("names");
                if (names == null) {
                    names = new JSONObject();
                    folder.put("names", names);
                }
                String value = field.getText().toString().trim();
                if (value.isEmpty() || value.equals(Store.recordingTitle(option.value))) names.remove(option.value);
                else names.put(option.value, value);
                if (save(folders)) {
                    dialog.dismiss();
                    render(scrollY());
                }
            } catch (JSONException error) {
                Toast.makeText(activity, "Не удалось сохранить название", Toast.LENGTH_SHORT).show();
            }
        }, StudioStyle.ACTIVE), 10);
        showDialog(form);
    }

    private void editLabel(String key, String initial, FolderLayout.Tile position) {
        LinearLayout form = form(key == null ? "Новая надпись" : "Надпись");
        EditText field = input(initial, 200, true);
        field.setHint("Текст надписи");
        append(form, field, 12);
        append(form, button("Сохранить", () -> {
            String value = field.getText().toString().trim();
            if (value.isEmpty()) {
                field.setError("Введи текст");
                return;
            }
            saveLabel(key, value, position);
        }, StudioStyle.ACTIVE), 10);
        if (key != null) append(form, button("Удалить надпись", () -> saveLabel(key, "", null), StudioStyle.CONTROL), 8);
        showDialog(form);
    }

    private void saveLabel(String key, String value, FolderLayout.Tile position) {
        JSONArray folders = load(activity);
        JSONObject folder = folders.optJSONObject(indexOf(folders, current));
        if (folder == null) return;
        Map<String, FolderLayout.Tile> tiles = layout(folder);
        try {
            JSONObject labels = folder.optJSONObject("labels");
            if (labels == null) {
                labels = new JSONObject();
                folder.put("labels", labels);
            }
            if (key == null) {
                String id = "label:" + UUID.randomUUID();
                labels.put(id, value);
                tiles.put(id, FolderLayout.fits(tiles, position) ? position : FolderLayout.firstFree(tiles, position.row, 2, 1));
            } else if (value.isEmpty()) {
                labels.remove(key);
                tiles.remove(key);
            } else labels.put(key, value);
            putLayout(folder, tiles);
            if (save(folders)) {
                dialog.dismiss();
                render(scrollY());
            }
        } catch (JSONException error) {
            Toast.makeText(activity, "Не удалось сохранить надпись", Toast.LENGTH_SHORT).show();
        }
    }

    private void folderActions() {
        String id = current;
        LinearLayout menu = form("Папка");
        append(menu, button("Оформление", () -> editFolder(id), StudioStyle.CONTROL), 8);
        append(menu, button("Удалить папку", () -> confirmRemoval(id), StudioStyle.CONTROL), 8);
        showDialog(menu);
    }

    private void confirmRemoval(String id) {
        LinearLayout form = form("Удалить папку?");
        append(form, text("Записи и расшифровки останутся в «Все записи».", 15, StudioStyle.MUTED), 8);
        append(form, button("Удалить папку", () -> {
            JSONArray folders = load(activity);
            int index = indexOf(folders, id);
            if (index < 0) return;
            folders.remove(index);
            if (save(folders)) {
                dialog.dismiss();
                showLibrary();
            }
        }, StudioStyle.ACTIVE), 12);
        append(form, button("Отмена", () -> dialog.dismiss(), StudioStyle.CONTROL), 8);
        showDialog(form);
    }

    private void editFolder(String id) {
        JSONObject original = id == null ? null : find(activity, id);
        LinearLayout form = form(original == null ? "Новая папка" : "Оформление");
        EditText name = input(original == null ? "" : original.optString("name"), 60, false);
        name.setHint("Название папки");
        append(form, name, 12);

        append(form, text("Значок", 14, StudioStyle.MUTED), 12);
        int[] iconChoice = {0};
        if (original != null) iconChoice[0] = Math.max(0, java.util.Arrays.asList(ICONS).indexOf(original.optString("icon")));
        append(form, palette(ICONS, ICON_NAMES, iconChoice, false, 4), 6);
        append(form, text("Цвет", 14, StudioStyle.MUTED), 12);
        int[] colorChoice = {0};
        if (original != null) colorChoice[0] = Math.max(0, java.util.Arrays.asList(COLORS).indexOf(original.optString("color")));
        append(form, palette(COLORS, COLOR_NAMES, colorChoice, true, 6), 6);
        append(form, button("Сохранить", () -> {
            String value = name.getText().toString().trim();
            if (value.isEmpty()) {
                name.setError("Укажи название");
                return;
            }
            JSONArray folders = load(activity);
            String key = id == null ? UUID.randomUUID().toString() : id;
            try {
                JSONObject folder = id == null ? new JSONObject().put("id", key).put("files", new JSONArray())
                        : folders.optJSONObject(indexOf(folders, key));
                if (folder == null) return;
                folder.put("name", value).put("icon", ICONS[iconChoice[0]]).put("color", COLORS[colorChoice[0]]);
                if (id == null) folders.put(folder);
                if (save(folders)) {
                    dialog.dismiss();
                    if (id == null) {
                        libraryScroll = scrollY();
                        open(key, 0);
                    } else render(scrollY());
                }
            } catch (JSONException error) {
                Toast.makeText(activity, "Не удалось сохранить папку", Toast.LENGTH_SHORT).show();
            }
        }, StudioStyle.ACTIVE), 12);
        showDialog(form);
    }

    private View palette(String[] values, String[] names, int[] selected, boolean colors, int columns) {
        LinearLayout grid = column();
        Button[] choices = new Button[values.length];
        LinearLayout row = null;
        for (int i = 0; i < values.length; i++) {
            if (i % columns == 0) {
                row = new LinearLayout(activity);
                append(grid, row, i == 0 ? 0 : 6);
            }
            int index = i;
            Button choice = button(colors ? "" : values[i], () -> {
                selected[0] = index;
                for (int j = 0; j < choices.length; j++) styleChoice(choices[j], values[j], colors, j == index);
            }, StudioStyle.CONTROL);
            choice.setContentDescription(names[i]);
            choice.setPadding(0, 0, 0, 0);
            choice.setTextSize(19);
            choices[i] = choice;
            styleChoice(choice, values[i], colors, i == selected[0]);
            LinearLayout.LayoutParams cell = new LinearLayout.LayoutParams(0, dp(48), 1);
            if (i % columns > 0) cell.setMarginStart(dp(4));
            row.addView(choice, cell);
        }
        return grid;
    }

    private void styleChoice(Button choice, String value, boolean colors, boolean selected) {
        int fill = colors ? Color.parseColor(value) : selected ? StudioStyle.ACTIVE : StudioStyle.CONTROL;
        GradientDrawable background = StudioStyle.surface(activity, fill, 10);
        if (selected) background.setStroke(dp(2), StudioStyle.TEXT);
        if (colors) {
            choice.setText(selected ? "✓" : "");
            choice.setTextColor(StudioStyle.INK);
        }
        choice.setBackground(background);
        choice.setSelected(selected);
    }

    private void chooseFiles() {
        List<ChoiceDropdown.Option> options = recordings.get();
        if (options.isEmpty()) {
            Toast.makeText(activity, "Пока нет записей", Toast.LENGTH_SHORT).show();
            return;
        }
        String id = current;
        Set<String> member = files(find(activity, id));
        LinearLayout form = form("Записи в папке");
        // A list adapter keeps the editor responsive for libraries with many recordings.
        android.widget.ListView list = new android.widget.ListView(activity);
        list.setChoiceMode(android.widget.ListView.CHOICE_MODE_MULTIPLE);
        list.setDivider(new ColorDrawable(StudioStyle.LINE));
        list.setDividerHeight(dp(1));
        list.setAdapter(new android.widget.BaseAdapter() {
            @Override public int getCount() { return options.size(); }
            @Override public Object getItem(int index) { return options.get(index); }
            @Override public long getItemId(int index) { return index; }
            @Override public View getView(int index, View old, ViewGroup parent) {
                android.widget.CheckedTextView row = (android.widget.CheckedTextView) (old == null
                        ? android.view.LayoutInflater.from(activity).inflate(android.R.layout.simple_list_item_multiple_choice, parent, false)
                        : old);
                ChoiceDropdown.Option option = options.get(index);
                row.setText(option.title + (option.detail.isEmpty() ? "" : "  ·  " + option.detail));
                row.setTextSize(15);
                row.setTextColor(StudioStyle.TEXT);
                row.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
                row.setPadding(dp(8), 0, dp(8), 0);
                row.setMinHeight(dp(50));
                row.setCheckMarkTintList(ColorStateList.valueOf(StudioStyle.ACCENT));
                row.setChecked(member.contains(option.value));
                return row;
            }
        });
        for (int i = 0; i < options.size(); i++) list.setItemChecked(i, member.contains(options.get(i).value));
        list.setOnItemClickListener((parent, view, index, item) -> {
            String key = options.get(index).value;
            if (list.isItemChecked(index)) member.add(key);
            else member.remove(key);
        });
        int height = Math.min(320, Math.max(115, getResources().getConfiguration().screenHeightDp - 155));
        LinearLayout.LayoutParams entries = new LinearLayout.LayoutParams(-1, dp(height));
        entries.topMargin = dp(8);
        form.addView(list, entries);
        append(form, button("Сохранить", () -> {
            JSONArray folders = load(activity);
            JSONObject folder = folders.optJSONObject(indexOf(folders, id));
            if (folder == null) return;
            try {
                folder.put("files", new JSONArray(member));
                JSONObject data = folder.optJSONObject("tiles");
                if (data != null) {
                    List<String> removed = new ArrayList<>();
                    JSONObject labels = folder.optJSONObject("labels");
                    data.keys().forEachRemaining(key -> {
                        if (!member.contains(key) && (labels == null || !labels.has(key))) removed.add(key);
                    });
                    for (String key : removed) data.remove(key);
                }
                if (save(folders)) {
                    dialog.dismiss();
                    render(scrollY());
                }
            } catch (JSONException error) {
                Toast.makeText(activity, "Не удалось сохранить записи", Toast.LENGTH_SHORT).show();
            }
        }, StudioStyle.ACTIVE), 8);
        showDialog(form);
    }

    private EditText input(String initial, int limit, boolean multiline) {
        EditText field = new EditText(activity);
        field.setTextColor(StudioStyle.TEXT);
        field.setHintTextColor(StudioStyle.MUTED);
        field.setBackground(StudioStyle.surface(activity, StudioStyle.CONTROL, 12));
        field.setPadding(dp(12), dp(8), dp(12), dp(8));
        field.setMinHeight(dp(52));
        field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(limit)});
        if (multiline) {
            field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
            field.setMinLines(2);
            field.setMaxLines(5);
        } else field.setSingleLine(true);
        field.setText(initial);
        field.setSelectAllOnFocus(true);
        return field;
    }

    private LinearLayout form(String title) {
        LinearLayout form = column();
        form.setPadding(dp(16), dp(14), dp(16), dp(16));
        form.addView(heading(title, 21));
        return form;
    }

    private void showDialog(LinearLayout form) {
        if (dialog != null) dialog.dismiss();
        ScrollView host = new ScrollView(activity);
        host.setBackground(StudioStyle.card(activity, 22));
        host.addView(form);
        dialog = new Dialog(activity);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setContentView(host);
        dialog.setCanceledOnTouchOutside(true);
        Window window = dialog.getWindow();
        window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
                | WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
        window.setDimAmount(.55f);
        dialog.show();
        window.setLayout(dp(Math.min(440, getResources().getConfiguration().screenWidthDp - 28)), -2);
    }

    @Override protected void onDetachedFromWindow() {
        if (dialog != null) dialog.dismiss();
        super.onDetachedFromWindow();
    }

    private int dp(int value) { return StudioStyle.dp(activity, value); }

    private LinearLayout column() {
        LinearLayout column = new LinearLayout(activity);
        column.setOrientation(VERTICAL);
        return column;
    }

    private void append(LinearLayout parent, View view, int gap) {
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(gap);
        parent.addView(view, layout);
    }

    private TextView text(String value, int size, int color) {
        TextView text = new TextView(activity);
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        return text;
    }

    private TextView heading(String value, int size) {
        TextView text = text(value, size, StudioStyle.TEXT);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        return text;
    }

    private Button button(String label, Runnable action, int color) {
        Button button = new Button(activity);
        button.setText(label);
        button.setAllCaps(false);
        button.setTextSize(14);
        button.setTextColor(StudioStyle.TEXT);
        button.setMinWidth(0);
        button.setMinimumWidth(0);
        button.setMinHeight(dp(48));
        button.setMinimumHeight(dp(48));
        button.setPadding(dp(10), 0, dp(10), 0);
        button.setBackground(StudioStyle.control(activity, color, 12));
        button.setOnClickListener(view -> action.run());
        return button;
    }

    private int color(JSONObject folder) {
        try { return Color.parseColor(folder.optString("color", COLORS[0])); }
        catch (IllegalArgumentException malformed) { return Color.parseColor(COLORS[0]); }
    }

    private GradientDrawable tintedCard(int accent) {
        int tint = 0xff000000 | (accent & 0x00ffffff);
        int top = Color.rgb((Color.red(tint) + 6 * 22) / 7, (Color.green(tint) + 6 * 24) / 7,
                (Color.blue(tint) + 6 * 33) / 7);
        GradientDrawable drawable = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[]{top, StudioStyle.PANEL});
        drawable.setCornerRadius(dp(16));
        drawable.setStroke(dp(1), StudioStyle.LINE);
        return drawable;
    }

    private final class Board extends ViewGroup {
        private final int accent;
        private final int gap = dp(7), stepY = dp(122);
        private final Map<String, FolderLayout.Tile> tiles;
        private final List<String> keys = new ArrayList<>();
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final int[] screen = new int[2];
        private FolderLayout.Tile preview;
        private FolderLayout.Tile emptySpot = new FolderLayout.Tile(0, 0, 2, 1);
        private float stepX;

        Board(int accent, Map<String, FolderLayout.Tile> tiles) {
            super(activity);
            this.accent = accent;
            this.tiles = tiles;
            setBackground(StudioStyle.surface(activity, StudioStyle.PANEL, 16));
            setContentDescription("Свободное место для надписи");
            setOnLongClickListener(view -> {
                editLabel(null, "", emptySpot);
                return true;
            });
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN && stepX > 0) {
                int column = (int) ((event.getX() - gap) / stepX);
                int row = (int) ((event.getY() - gap) / stepY);
                emptySpot = new FolderLayout.Tile(column, row, 2, 1);
            }
            return super.onTouchEvent(event);
        }

        void addRecording(ChoiceDropdown.Option option) {
            FolderLayout.Tile tile = tiles.get(option.value);
            FrameLayout card = new FrameLayout(activity);
            card.setBackground(tintedCard(accent));
            LinearLayout details = column();
            boolean tall = tile.height > 1;
            details.setGravity(tall ? Gravity.BOTTOM : Gravity.CENTER_VERTICAL);
            details.setPadding(dp(10), dp(6), dp(12), dp(tall ? 16 : 8));
            card.addView(details, new FrameLayout.LayoutParams(-1, -1));
            TextView title = heading(option.title, tall ? 17 : 15);
            title.setMaxLines(2);
            title.setEllipsize(TextUtils.TruncateAt.END);
            boolean timed = option.detail.indexOf(':') >= 0;
            TextView time = text(option.detail, tall && timed ? 31 : 12, accent);
            time.setTypeface(Typeface.MONOSPACE);
            time.setMaxLines(1);
            time.setEllipsize(TextUtils.TruncateAt.END);
            if (tall) {
                details.addView(time);
                append(details, title, 4);
            } else {
                details.addView(title);
                append(details, time, 3);
            }
            attach(option.value, option.title + ", " + option.detail, card,
                    () -> onRecording.accept(current, option.value), () -> renameRecording(option));
        }

        void addLabel(String key, String value) {
            FrameLayout card = new FrameLayout(activity);
            card.setBackground(tintedCard(accent));
            TextView label = text(value, 18, accent);
            label.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
            label.setGravity(Gravity.CENTER_VERTICAL);
            label.setEllipsize(TextUtils.TruncateAt.END);
            label.setMaxLines(tiles.get(key).height * 4);
            label.setPadding(dp(11), dp(10), dp(16), dp(12));
            card.addView(label, new FrameLayout.LayoutParams(-1, -1));
            Runnable edit = () -> editLabel(key, value, null);
            attach(key, value, card, edit, edit);
        }

        private void attach(String key, String description, FrameLayout card, Runnable click, Runnable longPress) {
            keys.add(key);
            card.setFocusable(true);
            card.setContentDescription(description);
            card.setOnClickListener(view -> click.run());
            card.setOnLongClickListener(view -> {
                longPress.run();
                return true;
            });
            View grip = new View(activity) {
                private final Paint strokes = new Paint(Paint.ANTI_ALIAS_FLAG);

                @Override protected void onDraw(Canvas canvas) {
                    strokes.setColor(accent);
                    strokes.setAlpha(160);
                    strokes.setStrokeWidth(dp(1));
                    strokes.setStrokeCap(Paint.Cap.ROUND);
                    float side = getWidth();
                    canvas.drawLine(.25f * side, .75f * side, .75f * side, .25f * side, strokes);
                    canvas.drawLine(.52f * side, .76f * side, .76f * side, .52f * side, strokes);
                }
            };
            grip.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
            FrameLayout.LayoutParams corner = new FrameLayout.LayoutParams(dp(19), dp(19), Gravity.BOTTOM | Gravity.RIGHT);
            corner.rightMargin = dp(3);
            corner.bottomMargin = dp(3);
            card.addView(grip, corner);
            card.setOnTouchListener(new TileGesture(key, card));
            addView(card, new ViewGroup.LayoutParams(-1, -1));
        }

        private final class TileGesture implements OnTouchListener {
            private final String key;
            private final View card;
            private final FolderLayout.Tile original;
            private final int slop = ViewConfiguration.get(activity).getScaledTouchSlop();
            private final Runnable hold;
            private float downX, downY;
            private int boardTop;
            private boolean armed, dragging, resizing, cancelled;
            private int pointer;

            TileGesture(String key, View card) {
                this.key = key;
                this.card = card;
                original = tiles.get(key);
                hold = () -> {
                    if (!card.isAttachedToWindow()) return;
                    armed = true;
                    card.getParent().requestDisallowInterceptTouchEvent(true);
                    card.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
                    preview = original;
                    invalidate();
                };
            }

            @Override public boolean onTouch(View view, MotionEvent event) {
                switch (event.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downX = event.getRawX();
                        downY = event.getRawY();
                        getLocationOnScreen(screen);
                        boardTop = screen[1];
                        pointer = event.getPointerId(0);
                        cancelled = false;
                        resizing = view.getWidth() - event.getX() <= dp(33)
                                && view.getHeight() - event.getY() <= dp(33);
                        if (resizing) view.getParent().requestDisallowInterceptTouchEvent(true);
                        else view.postDelayed(hold, ViewConfiguration.getLongPressTimeout());
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        if (cancelled || event.getPointerId(0) != pointer) return true;
                        float dx = event.getRawX() - downX, dy = event.getRawY() - downY;
                        if (!armed && !resizing) {
                            if (Math.hypot(dx, dy) > slop) {
                                view.removeCallbacks(hold);
                                cancelled = true;
                            }
                            return true;
                        }
                        if (!dragging && Math.hypot(dx, dy) <= slop) return true;
                        dragging = true;
                        getLocationOnScreen(screen);
                        dy += boardTop - screen[1];
                        int deltaX = Math.round(dx / stepX), deltaY = Math.round(dy / stepY);
                        if (resizing) {
                            int width = Math.min(FolderLayout.COLUMNS - original.column, original.width + deltaX);
                            preview = new FolderLayout.Tile(original.column, original.row, width, original.height + deltaY);
                        } else {
                            int row = Math.min(FolderLayout.rows(tiles), original.row + deltaY);
                            preview = new FolderLayout.Tile(original.column + deltaX, row, original.width, original.height);
                            view.setTranslationX((preview.column - original.column) * stepX);
                            view.setTranslationY((preview.row - original.row) * stepY);
                            view.setTranslationZ(dp(5));
                        }
                        scroll.getLocationOnScreen(screen);
                        float relative = event.getRawY() - screen[1];
                        if (relative > scroll.getHeight() - dp(34)) scroll.scrollBy(0, dp(12));
                        else if (relative < dp(34)) scroll.scrollBy(0, -dp(12));
                        invalidate();
                        return true;
                    case MotionEvent.ACTION_UP:
                        FolderLayout.Tile target = dragging ? preview : null;
                        boolean rename = armed && !dragging;
                        boolean click = !dragging && !armed && !resizing && !cancelled;
                        reset();
                        if (target != null && changed(target)) saveLayout(key, target);
                        else if (rename) view.performLongClick();
                        else if (click) view.performClick();
                        return true;
                    case MotionEvent.ACTION_POINTER_DOWN:
                    case MotionEvent.ACTION_CANCEL:
                        reset();
                        cancelled = true;
                        return true;
                    default:
                        return true;
                }
            }

            private boolean changed(FolderLayout.Tile target) {
                return target.column != original.column || target.row != original.row
                        || target.width != original.width || target.height != original.height;
            }

            private void reset() {
                card.removeCallbacks(hold);
                card.setTranslationX(0);
                card.setTranslationY(0);
                card.setTranslationZ(0);
                card.getParent().requestDisallowInterceptTouchEvent(false);
                armed = false;
                dragging = false;
                resizing = false;
                preview = null;
                invalidate();
            }
        }

        @Override protected void onMeasure(int widthSpec, int heightSpec) {
            int width = MeasureSpec.getSize(widthSpec);
            stepX = Math.max(1, (width - gap) / (float) FolderLayout.COLUMNS);
            int rows = Math.max(2, FolderLayout.rows(tiles) + 1);
            setMeasuredDimension(width, rows * stepY + gap);
            for (int index = 0; index < getChildCount(); index++) {
                FolderLayout.Tile tile = tiles.get(keys.get(index));
                getChildAt(index).measure(MeasureSpec.makeMeasureSpec(Math.max(0, Math.round(tile.width * stepX) - gap), MeasureSpec.EXACTLY),
                        MeasureSpec.makeMeasureSpec(tile.height * stepY - gap, MeasureSpec.EXACTLY));
            }
        }

        @Override protected void onLayout(boolean changed, int left, int top, int right, int bottom) {
            for (int index = 0; index < getChildCount(); index++) {
                FolderLayout.Tile tile = tiles.get(keys.get(index));
                View child = getChildAt(index);
                int x = gap + Math.round(tile.column * stepX), y = gap + tile.row * stepY;
                child.layout(x, y, x + child.getMeasuredWidth(), y + child.getMeasuredHeight());
            }
        }

        @Override protected void dispatchDraw(Canvas canvas) {
            if (preview != null || keys.isEmpty()) {
                paint.setColor(StudioStyle.LINE);
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(dp(1));
                android.graphics.Rect clip = canvas.getClipBounds();
                for (int row = Math.max(0, clip.top / stepY); row * stepY + gap < clip.bottom; row++) {
                    for (int col = 0; col < FolderLayout.COLUMNS; col++) drawTile(canvas, col, row, 1, 1);
                }
            }
            super.dispatchDraw(canvas);
            if (preview != null) {
                paint.setColor((accent & 0x00ffffff) | 0x30000000);
                paint.setStyle(Paint.Style.FILL);
                drawTile(canvas, preview.column, preview.row, preview.width, preview.height);
                paint.setColor(accent);
                paint.setStyle(Paint.Style.STROKE);
                paint.setStrokeWidth(dp(2));
                drawTile(canvas, preview.column, preview.row, preview.width, preview.height);
            }
        }

        private void drawTile(Canvas canvas, int col, int row, int width, int height) {
            float x = gap + col * stepX, y = gap + row * stepY;
            canvas.drawRoundRect(x, y, x + width * stepX - gap, y + height * stepY - gap, dp(11), dp(11), paint);
        }
    }
}
