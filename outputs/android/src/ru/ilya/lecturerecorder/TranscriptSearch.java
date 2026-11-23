package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.text.Editable;
import android.text.TextWatcher;
import android.text.TextUtils;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.ArrayAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;
import java.util.function.IntConsumer;

final class TranscriptSearch {
    static AlertDialog open(Activity activity, JSONArray segments, String previous, Consumer<String> remember, IntConsumer select) {
        LinearLayout column = new LinearLayout(activity);
        column.setOrientation(LinearLayout.VERTICAL);
        int inset = StudioStyle.dp(activity, 16);
        column.setPadding(inset, 0, inset, 0);
        EditText query = new EditText(activity);
        query.setSingleLine();
        query.setHint("Слово или фраза");
        query.setContentDescription("Поиск по расшифровке");
        query.setImeOptions(EditorInfo.IME_ACTION_SEARCH | EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        column.addView(query);
        TextView status = new TextView(activity);
        status.setTextColor(StudioStyle.MUTED);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        column.addView(status);
        ListView list = new ListView(activity);
        int height = Math.min(300, activity.getResources().getConfiguration().screenHeightDp / 3);
        column.addView(list, new LinearLayout.LayoutParams(-1, StudioStyle.dp(activity, height)));
        ArrayAdapter<String> adapter = new ArrayAdapter<String>(activity, android.R.layout.simple_list_item_1) {
            @Override public View getView(int position, View view, ViewGroup parent) {
                TextView row = (TextView)super.getView(position, view, parent);
                row.setTextColor(StudioStyle.TEXT);
                row.setSingleLine(false);
                row.setMaxLines(3);
                row.setEllipsize(TextUtils.TruncateAt.END);
                row.setMinimumHeight(StudioStyle.dp(activity, 48));
                return row;
            }
        };
        list.setAdapter(adapter);
        List<String> indexed = new ArrayList<>(), labels = new ArrayList<>();
        for (int i = 0; i < segments.length(); i++) {
            JSONObject segment = segments.optJSONObject(i);
            String text = segment == null ? "" : segment.optString("text");
            indexed.add(ListeningLibrary.normalize(text));
            double from = segment == null ? -1 : segment.optDouble("start", -1);
            labels.add(Double.isFinite(from) && from >= 0 ? LectureReaderActivity.clock(from) + " · " + text : text);
        }
        List<Integer> matches = new ArrayList<>();
        Runnable update = () -> {
            String value = query.getText().toString();
            remember.accept(value);
            String[] terms = ListeningLibrary.terms(value);
            matches.clear();
            adapter.setNotifyOnChange(false);
            adapter.clear();
            if (terms.length > 0) for (int i = 0; i < indexed.size(); i++) {
                if (ListeningLibrary.matches(indexed.get(i), terms)) {
                    matches.add(i);
                    adapter.add(labels.get(i));
                }
            }
            adapter.notifyDataSetChanged();
            status.setText(terms.length == 0 ? "Введи слова из записи"
                    : matches.isEmpty() ? "Совпадений нет" : "Найдено фрагментов · " + matches.size());
        };
        AlertDialog dialog = new AlertDialog.Builder(activity).setTitle("Найти в тексте").setView(column)
                .setNeutralButton("Очистить", null).setNegativeButton("Закрыть", null).create();
        list.setOnItemClickListener((parent, view, position, id) -> {
            int index = matches.get(position);
            dialog.dismiss();
            select.accept(index);
        });
        query.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) { update.run(); }
            @Override public void afterTextChanged(Editable text) {}
        });
        query.setText(previous);
        query.setSelection(query.length());
        query.setOnEditorActionListener((box, action, key) -> {
            if (action != EditorInfo.IME_ACTION_SEARCH || matches.isEmpty()) return false;
            int first = matches.get(0);
            dialog.dismiss();
            select.accept(first);
            return true;
        });
        query.requestFocus();
        dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE
                | WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE);
        dialog.show();
        dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(view -> {
            query.setText("");
            query.requestFocus();
        });
        return dialog;
    }

    private TranscriptSearch() {}
}
