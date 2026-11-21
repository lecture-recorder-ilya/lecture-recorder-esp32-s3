package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AbsListView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import java.util.ArrayList;
import java.util.List;
import java.util.function.Consumer;
import java.util.function.IntSupplier;
import java.util.function.Supplier;

final class ChoiceDropdown {
    private static final int TEXT = 0xfff5f3f1;
    private static final int MUTED = 0xffa7a9b2;
    private static final int ACCENT = 0xffff593b;
    private final Context context;
    private final String label;
    private final String empty;
    private final Supplier<List<Option>> options;
    private final Consumer<Option> onChoice;
    final Button button;
    final ListView list;
    private Consumer<Boolean> expansion;
    private IntSupplier heightLimit;
    private Option selected;
    private Object backDispatcher;
    private Object backCallback;

    ChoiceDropdown(Context context, String label, String empty,
                   Supplier<List<Option>> options, Consumer<Option> onChoice) {
        this.context = context;
        this.label = label;
        this.empty = empty;
        this.options = options;
        this.onChoice = onChoice;

        button = new Button(context);
        button.setTextSize(15);
        button.setTextColor(TEXT);
        button.setAllCaps(false);
        button.setGravity(Gravity.CENTER_VERTICAL | Gravity.START);
        button.setMinHeight(dp(52));
        button.setMinimumHeight(dp(52));
        button.setPadding(dp(12), 0, dp(12), 0);
        button.setSingleLine();
        button.setEllipsize(TextUtils.TruncateAt.END);
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x28ffffff), surface(0xff2b2d33), null));
        button.setOnClickListener(view -> { if (!close()) open(); });

        list = new ListView(context);
        GradientDrawable background = surface(0xff24262c);
        background.setStroke(dp(1), 0xff41454f);
        list.setBackground(background);
        list.setDivider(new ColorDrawable(0xff353841));
        list.setDividerHeight(dp(1));
        list.setPadding(0, dp(3), 0, dp(3));
        list.setClipToOutline(true);
        list.setVisibility(View.GONE);
        list.setOnTouchListener((view, event) -> {
            if (event.getActionMasked() == MotionEvent.ACTION_DOWN
                    && (list.canScrollVertically(1) || list.canScrollVertically(-1))) {
                list.getParent().requestDisallowInterceptTouchEvent(true);
            }
            return false;
        });
        updateButton();
    }

    void setExpansionListener(Consumer<Boolean> listener) {
        expansion = listener;
    }

    void setHeightLimit(IntSupplier limit) {
        heightLimit = limit;
    }

    void setSelected(Option option) {
        selected = option;
        updateButton();
        if (list.getAdapter() instanceof Adapter) ((Adapter) list.getAdapter()).notifyDataSetChanged();
    }

    void setEnabled(boolean enabled) {
        if (!enabled) close();
        button.setEnabled(enabled);
        button.setAlpha(enabled ? 1f : 0.45f);
    }

    void refreshOptions() {
        if (!isOpen()) return;
        List<Option> entries = new ArrayList<>(options.get());
        if (entries.isEmpty()) entries.add(new Option(null, empty, ""));
        list.setAdapter(new Adapter(entries));
        list.setOnItemClickListener((parent, row, index, id) -> {
            Option option = entries.get(index);
            if (option.value == null) return;
            setSelected(option);
            close();
            onChoice.accept(option);
        });
        ViewGroup.LayoutParams layout = list.getLayoutParams();
        int limit = dp(240);
        if (heightLimit != null) limit = Math.min(limit, Math.max(dp(58), heightLimit.getAsInt()));
        layout.height = Math.min(limit, dp(52) * entries.size() + dp(6) + dp(1) * (entries.size() - 1));
        list.setLayoutParams(layout);
    }

    boolean close() {
        if (!isOpen()) return false;
        list.animate().cancel();
        list.setVisibility(View.GONE);
        updateButton();
        if (expansion != null) expansion.accept(false);
        if (Build.VERSION.SDK_INT >= 33 && backCallback != null) {
            ((android.window.OnBackInvokedDispatcher) backDispatcher).unregisterOnBackInvokedCallback(
                    (android.window.OnBackInvokedCallback) backCallback);
            backDispatcher = null;
            backCallback = null;
        }
        return true;
    }

    private void open() {
        list.setVisibility(View.VISIBLE);
        refreshOptions();
        updateButton();
        if (expansion != null) expansion.accept(true);
        list.setTranslationY(-dp(8));
        list.setAlpha(0f);
        list.animate().translationY(0f).alpha(1f).setDuration(160).start();
        if (Build.VERSION.SDK_INT >= 33) {
            android.window.OnBackInvokedDispatcher dispatcher = button.findOnBackInvokedDispatcher();
            if (dispatcher != null) {
                android.window.OnBackInvokedCallback callback = () -> close();
                backDispatcher = dispatcher;
                backCallback = callback;
                dispatcher.registerOnBackInvokedCallback(
                        android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback);
            }
        }
    }

    private boolean isOpen() {
        return list.getVisibility() == View.VISIBLE;
    }

    private void updateButton() {
        boolean open = isOpen();
        button.setText((selected == null ? label : selected.title) + (open ? "  ▴" : "  ▾"));
        button.setContentDescription(open ? "Свернуть список" : selected == null ? label : label + ". " + selected.title);
    }

    private GradientDrawable surface(int color) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(12));
        return drawable;
    }

    private int dp(int value) {
        return Math.round(value * context.getResources().getDisplayMetrics().density);
    }

    static final class Option {
        final String value;
        final String title;
        final String detail;

        Option(String value, String title, String detail) {
            this.value = value;
            this.title = title;
            this.detail = detail;
        }
    }

    private final class Adapter extends ArrayAdapter<Option> {
        Adapter(List<Option> options) {
            super(context, 0, options);
        }

        @Override public boolean areAllItemsEnabled() {
            return false;
        }

        @Override public boolean isEnabled(int index) {
            return getItem(index).value != null;
        }

        @Override public View getView(int index, View reusable, ViewGroup parent) {
            Row row = reusable == null ? new Row() : (Row) reusable;
            Option option = getItem(index);
            boolean current = selected != null && selected.value.equals(option.value);
            row.title.setText(option.title);
            row.title.setTextColor(option.value == null ? MUTED : current ? ACCENT : TEXT);
            row.detail.setText(option.detail + (current ? (option.detail.isEmpty() ? "✓" : "  ✓") : ""));
            row.detail.setVisibility(option.detail.isEmpty() && !current ? View.GONE : View.VISIBLE);
            return row;
        }
    }

    private final class Row extends LinearLayout {
        final TextView title = new TextView(context);
        final TextView detail = new TextView(context);

        Row() {
            super(context);
            setGravity(Gravity.CENTER_VERTICAL);
            setPadding(dp(14), 0, dp(12), 0);
            setLayoutParams(new AbsListView.LayoutParams(-1, dp(52)));
            title.setTextSize(15);
            title.setSingleLine();
            title.setEllipsize(TextUtils.TruncateAt.END);
            addView(title, new LinearLayout.LayoutParams(0, -2, 1));
            detail.setTextSize(14);
            detail.setTextColor(MUTED);
            detail.setPadding(dp(8), 0, 0, 0);
            addView(detail);
        }
    }
}
