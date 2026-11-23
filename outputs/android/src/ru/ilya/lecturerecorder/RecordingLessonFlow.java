package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Typeface;
import android.text.Editable;
import android.text.InputFilter;
import android.text.TextWatcher;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.widget.*;
import org.json.JSONObject;

import java.time.Instant;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.function.Consumer;

final class RecordingLessonFlow {
    private static final String DEFERRED = "deferred_lessons";
    private final Activity activity;
    private final SharedPreferences profile;
    private final SharedPreferences choiceDrafts;
    private final Consumer<String> onSaved;
    private final Runnable onDeferred;
    private final Runnable onDiscarded;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final ExecutorService saves = Executors.newSingleThreadExecutor();
    private AlertDialog dialog, discardDialog;
    private String checkedGroup = "";
    private boolean disposed;
    private boolean pendingChecked;
    private String pending = "";
    private String lastRecording = "";

    RecordingLessonFlow(Activity activity, Consumer<String> onSaved, Runnable onDeferred, Runnable onDiscarded) {
        this.activity = activity;
        this.onSaved = onSaved;
        this.onDeferred = onDeferred;
        this.onDiscarded = onDiscarded;
        profile = MireaSchedule.profile(activity);
        choiceDrafts = activity.getSharedPreferences("lesson_choice_drafts", Context.MODE_PRIVATE);
    }

    String profileLabel() {
        String group = profile.getString("group", "");
        int course = profile.getInt("course", 0);
        return group.isEmpty() ? "Группа и курс не заданы" : group + " · " + course + " курс";
    }

    void onResume() { pendingChecked = false; }

    boolean hasPending() { return !pending.isEmpty(); }

    void openPending() {
        if (disposed || dialog != null || CaptureService.recording) return;
        pending = Store.pendingLesson(activity);
        if (hasPending()) choose(pending);
    }

    void openPending(String name) {
        if (disposed || dialog != null || CaptureService.recording) return;
        choose(name);
    }

    void refresh(boolean recording, boolean allowAutomaticChoice) {
        if (recording) {
            pendingChecked = false;
            return;
        }
        if (!lastRecording.equals(CaptureService.current)) {
            lastRecording = CaptureService.current;
            pendingChecked = false;
        }
        if (dialog != null) return;
        if (!pendingChecked) {
            pendingChecked = true;
            pending = Store.pendingLesson(activity);
            if (!hasPending()) {
                if (profile.contains(DEFERRED)) profile.edit().remove(DEFERRED).apply();
                warmSchedule();
            } else if (allowAutomaticChoice && !deferred().contains(pending)) choose(pending);
        }
    }

    private Set<String> deferred() {
        return profile.getStringSet(DEFERRED, Collections.emptySet());
    }

    private void defer(String name) {
        Set<String> entries = new HashSet<>(deferred());
        if (entries.add(name)) profile.edit().putStringSet(DEFERRED, entries).apply();
        onDeferred.run();
    }

    private void resolve(String name) {
        choiceDrafts.edit().remove(name + ".choice").remove(name + ".title").apply();
        Set<String> entries = new HashSet<>(deferred());
        if (entries.remove(name)) profile.edit().putStringSet(DEFERRED, entries).apply();
        pending = "";
        pendingChecked = false;
    }

    void profile(boolean editing) {
        if (dialog != null || disposed) return;
        LinearLayout content = pane();
        content.addView(text("Группу и курс можно изменить в настройках. Для выбора пары используем расписание МИРЭА.", 15, StudioStyle.MUTED));
        EditText group = edit("Например, ИКБО-01-26");
        group.setText(profile.getString("group", ""));
        content.addView(group);
        TextView courseLabel = text("Курс", 14, StudioStyle.MUTED);
        courseLabel.setPadding(0, dp(12), 0, 0);
        content.addView(courseLabel);
        Spinner course = new Spinner(activity, Spinner.MODE_DROPDOWN);
        ArrayAdapter<String> courses = new ArrayAdapter<>(activity, android.R.layout.simple_spinner_item,
                new String[]{"Выбери курс", "1 курс", "2 курс", "3 курс", "4 курс", "5 курс", "6 курс"});
        courses.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        course.setAdapter(courses);
        course.setSelection(profile.getInt("course", 0));
        course.setContentDescription("Курс");
        course.setMinimumHeight(dp(48));
        content.addView(course);
        AlertDialog profileDialog = new AlertDialog.Builder(activity)
                .setTitle("Группа и курс")
                .setView(scroll(content))
                .setPositiveButton("Сохранить", null)
                .setNegativeButton(editing ? "Закрыть" : "Пропустить", (d, w) -> {
                    if (!editing) profile.edit().putBoolean("seen", true).apply();
                    pendingChecked = false;
                }).create();
        show(profileDialog, content, editing);
        profileDialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(view -> {
            String value = MireaSchedule.group(group.getText().toString());
            if (!MireaSchedule.validGroup(value)) {
                group.setError("Введи код учебной группы");
                group.requestFocus();
                return;
            }
            if (course.getSelectedItemPosition() == 0) {
                Toast.makeText(activity, "Выбери курс", Toast.LENGTH_SHORT).show();
                course.performClick();
                return;
            }
            profile.edit().putBoolean("seen", true).putString("group", value)
                    .putInt("course", course.getSelectedItemPosition()).apply();
            pendingChecked = false;
            profileDialog.dismiss();
            warmSchedule();
        });
    }

    private void warmSchedule() {
        String group = profile.getString("group", "");
        if (group.isEmpty() || checkedGroup.equals(group)) return;
        checkedGroup = group;
        worker.execute(() -> {
            try { MireaSchedule.load(activity.getApplicationContext(), group); }
            catch (Exception ignored) {}
        });
    }

    static String draftTitle(Context context, String name) {
        return context.getSharedPreferences("lesson_choice_drafts", Context.MODE_PRIVATE)
                .getString(name + ".title", "").trim().replaceAll("\\s*\\R\\s*", " ");
    }

    private static String lessonKey(MireaSchedule.Lesson lesson) {
        return "schedule:" + lesson.start + "|" + lesson.end + "|" + lesson.subject + "|" + lesson.type + "|" + lesson.room;
    }

    private void choose(String name) {
        JSONObject recording;
        try { recording = Store.pendingMetadata(activity, name); }
        catch (Exception error) {
            Toast.makeText(activity, error.getMessage(), Toast.LENGTH_SHORT).show();
            return;
        }
        ZonedDateTime start = Instant.ofEpochMilli(recording.optLong("started_ms", System.currentTimeMillis()))
                .atZone(MireaSchedule.MOSCOW);
        long seconds = Math.max(0, (Store.audio(activity, name).length() - 44) / 32000);
        String group = profile.getString("group", "");
        LinearLayout content = pane();
        TextView status = text("Аудио сохранено на телефоне · " + Store.recordingTitle(name), 14, StudioStyle.MUTED);
        content.addView(status);
        TextView hint = text(group.isEmpty() ? "Укажи предмет вручную или сохрани запись без пары." : "Загружаю расписание группы " + group + "…",
                14, StudioStyle.MUTED);
        hint.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        content.addView(hint);
        Button retry = new Button(activity);
        retry.setText("Повторить загрузку расписания");
        retry.setAllCaps(false);
        retry.setMinimumHeight(dp(48));
        retry.setTextColor(StudioStyle.ACCENT);
        retry.setBackground(StudioStyle.control(activity, StudioStyle.CONTROL, 12));
        retry.setVisibility(View.GONE);
        content.addView(retry);
        RadioGroup options = new RadioGroup(activity);
        options.setPadding(0, dp(6), 0, dp(6));
        content.addView(options);
        List<MireaSchedule.Lesson> lessons = new ArrayList<>();
        EditText manual = edit("Название предмета");
        String[] draftChoice = {choiceDrafts.getString(name + ".choice", "")};
        manual.setSingleLine(false);
        manual.setRawInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        manual.setHorizontallyScrolling(false);
        manual.setMaxLines(3);
        manual.setImeOptions(EditorInfo.IME_ACTION_DONE);
        manual.setText(choiceDrafts.getString(name + ".title", ""));
        manual.setVisibility("manual".equals(draftChoice[0]) ? View.VISIBLE : View.GONE);
        manual.addTextChangedListener(new TextWatcher() {
            @Override public void beforeTextChanged(CharSequence text, int start, int count, int after) {}
            @Override public void onTextChanged(CharSequence text, int start, int before, int count) {
                choiceDrafts.edit().putString(name + ".title", text.toString()).apply();
            }
            @Override public void afterTextChanged(Editable text) {}
        });
        content.addView(manual);
        TextView saveStatus = text("", 14, StudioStyle.MUTED);
        saveStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        saveStatus.setVisibility(View.GONE);
        content.addView(saveStatus);
        Button delete = new Button(activity, null, android.R.attr.borderlessButtonStyle);
        delete.setText("Отменить запись…");
        delete.setAllCaps(false);
        delete.setTextColor(StudioStyle.RECORDING);
        delete.setMinimumHeight(dp(48));
        content.addView(delete);
        RadioButton outside = option("Без пары", false);
        RadioButton own = option("Указать предмет вручную", false);
        options.addView(outside);
        options.addView(own);
        outside.setTag(-1);
        own.setTag(-2);
        if ("manual".equals(draftChoice[0])) options.check(own.getId());
        else if (!draftChoice[0].startsWith("schedule:")) options.check(outside.getId());
        Consumer<String> rememberChoice = value -> {
            draftChoice[0] = value;
            choiceDrafts.edit().putString(name + ".choice", value).apply();
        };
        outside.setOnClickListener(view -> rememberChoice.accept("outside"));
        own.setOnClickListener(view -> rememberChoice.accept("manual"));

        AlertDialog choice = new AlertDialog.Builder(activity)
                .setTitle("К какой паре отнести запись?")
                .setView(scroll(content))
                .setPositiveButton("Сохранить", null)
                .setNegativeButton("Позже", (dismissed, button) -> defer(name))
                .create();
        choice.setOnCancelListener(cancelled -> defer(name));
        show(choice, content, true);
        Button later = choice.getButton(AlertDialog.BUTTON_NEGATIVE);
        Button save = choice.getButton(AlertDialog.BUTTON_POSITIVE);
        save.setEnabled(options.getCheckedRadioButtonId() != View.NO_ID);
        options.setOnCheckedChangeListener((layout, id) -> {
            manual.setVisibility(id == own.getId() ? View.VISIBLE : View.GONE);
            if (id == own.getId()) StudioStyle.enter(manual, false);
            save.setEnabled(id != View.NO_ID);
        });
        boolean[] saving = {false};
        boolean[] scheduleFailed = {false};
        later.setAllCaps(false);
        later.setTextColor(StudioStyle.MUTED);
        later.setContentDescription("Выбрать пару позже");
        save.setOnClickListener(view -> {
            if (saving[0]) return;
            RadioButton selected = options.findViewById(options.getCheckedRadioButtonId());
            if (selected == null) return;
            int index = (Integer) selected.getTag();
            String title = manual.getText().toString().trim().replaceAll("\\s*\\R\\s*", " ");
            if (index == -2 && title.isEmpty()) {
                manual.setError("Введи название предмета");
                manual.requestFocus();
                return;
            }
            try {
                JSONObject lesson = null;
                if (index >= 0) lesson = lessons.get(index).metadata(group);
                else if (index == -2) lesson = new JSONObject().put("subject", title)
                        .put("date", start.toLocalDate().toString())
                        .put("start", start.toLocalTime().withSecond(0).withNano(0).toString())
                        .put("end", "").put("type", "").put("group", group).put("source", "manual");
                JSONObject selectedLesson = lesson;
                saving[0] = true;
                choice.setCancelable(false);
                save.setEnabled(false);
                later.setEnabled(false);
                delete.setEnabled(false);
                for (int i = 0; i < options.getChildCount(); i++) options.getChildAt(i).setEnabled(false);
                manual.setEnabled(false);
                retry.setEnabled(false);
                saveStatus.setTextColor(StudioStyle.MUTED);
                saveStatus.setText("Сохраняю выбранную пару…");
                saveStatus.setVisibility(View.VISIBLE);
                saves.execute(() -> {
                    try {
                        Store.finishLesson(activity, name, selectedLesson);
                        activity.runOnUiThread(() -> {
                            if (disposed) return;
                            resolve(name);
                            choice.dismiss();
                            onSaved.accept(name);
                            boolean analyze = android.os.Process.is64Bit() && !PhoneAnalysisService.busy()
                                    && PhoneModels.ready(activity);
                            if (analyze) PhoneAnalysisService.request(activity, name, Store.recordingTitle(activity, name));
                        });
                    } catch (Exception error) {
                        activity.runOnUiThread(() -> {
                            if (disposed || dialog != choice) return;
                            saving[0] = false;
                            choice.setCancelable(true);
                            save.setEnabled(true);
                            later.setEnabled(true);
                            delete.setEnabled(true);
                            for (int i = 0; i < options.getChildCount(); i++) options.getChildAt(i).setEnabled(true);
                            manual.setEnabled(true);
                            retry.setEnabled(scheduleFailed[0]);
                            saveStatus.setTextColor(StudioStyle.RECORDING);
                            saveStatus.setText("Не удалось сохранить выбор. Повтори попытку. " + error.getMessage());
                        });
                    }
                });
            } catch (Exception error) {
                Toast.makeText(activity, error.getMessage(), Toast.LENGTH_LONG).show();
            }
        });
        delete.setOnClickListener(view -> {
            delete.setEnabled(false);
            AlertDialog confirmationDialog = new AlertDialog.Builder(activity).setTitle("Отменить запись?")
                .setMessage("Аудио будет удалено с телефона.")
                .setNegativeButton("Оставить аудио", null)
                .setPositiveButton("Удалить", null)
                .show();
            discardDialog = confirmationDialog;
            decorate(confirmationDialog, true);
            confirmationDialog.setOnDismissListener(ignored -> {
                discardDialog = null;
                delete.setEnabled(true);
            });
            Button discard = confirmationDialog.getButton(AlertDialog.BUTTON_POSITIVE);
            discard.setOnClickListener(confirm -> {
                discard.setEnabled(false);
                try {
                    Store.discardLesson(activity, name);
                    resolve(name);
                    confirmationDialog.dismiss();
                    choice.dismiss();
                    onDiscarded.run();
                } catch (Exception error) {
                    discard.setEnabled(true);
                    Toast.makeText(activity, error.getMessage(), Toast.LENGTH_LONG).show();
                }
            });
        });
        if (group.isEmpty()) return;

        Runnable loadSchedule = () -> {
            scheduleFailed[0] = false;
            retry.setVisibility(View.GONE);
            hint.setText("Загружаю расписание. Можно выбрать предмет вручную или сохранить без пары.");
            worker.execute(() -> {
                try {
                    String calendar = MireaSchedule.load(activity.getApplicationContext(), group);
                    List<MireaSchedule.Lesson> result = MireaSchedule.lessons(calendar, start.toLocalDate());
                    activity.runOnUiThread(() -> {
                        if (disposed || dialog != choice || !choice.isShowing()) return;
                        lessons.addAll(result);
                        int recommended = MireaSchedule.suggestion(lessons, start, seconds);
                        boolean suggest = !saving[0] && draftChoice[0].isEmpty() && options.getCheckedRadioButtonId() == outside.getId();
                        hint.setText(lessons.isEmpty() ? "В расписании на этот день занятий нет."
                                : recommended >= 0 ? "Предложение по времени начала записи · Москва"
                                : "Выбери занятие из расписания на день записи · Москва");
                        for (int i = 0; i < lessons.size(); i++) {
                            MireaSchedule.Lesson lesson = lessons.get(i);
                            RadioButton button = option(lesson.subject + "\n" + lesson.detail() + (i == recommended ? " · предложено" : ""),
                                    i == recommended);
                            String key = lessonKey(lesson);
                            button.setTag(i);
                            button.setEnabled(!saving[0]);
                            button.setOnClickListener(view -> rememberChoice.accept(key));
                            options.addView(button, i);
                            if (!saving[0] && (key.equals(draftChoice[0]) || i == recommended && suggest)) {
                                options.check(button.getId());
                            }
                        }
                        if (draftChoice[0].startsWith("schedule:") && options.getCheckedRadioButtonId() == View.NO_ID) {
                            hint.setText("Сохранённой пары нет в расписании. Выбери пару заново.");
                        }
                        if (!lessons.isEmpty()) StudioStyle.enter(options, false);
                    });
                } catch (Exception error) {
                    activity.runOnUiThread(() -> {
                        if (disposed || dialog != choice) return;
                        scheduleFailed[0] = true;
                        hint.setText("Расписание недоступно. Можно указать предмет или сохранить без пары.");
                        retry.setEnabled(!saving[0]);
                        retry.setVisibility(View.VISIBLE);
                    });
                }
            });
        };
        retry.setOnClickListener(view -> loadSchedule.run());
        loadSchedule.run();
    }

    private RadioButton option(String title, boolean recommended) {
        RadioButton option = new RadioButton(activity);
        option.setId(View.generateViewId());
        option.setText(title);
        option.setMinHeight(dp(48));
        option.setPadding(dp(12), dp(10), dp(12), dp(10));
        RadioGroup.LayoutParams size = new RadioGroup.LayoutParams(-1, -2);
        size.bottomMargin = dp(6);
        option.setLayoutParams(size);
        option.setBackground(StudioStyle.lessonOption(activity));
        option.setTextColor(StudioStyle.TEXT);
        option.setButtonTintList(ColorStateList.valueOf(recommended ? StudioStyle.GOOD : StudioStyle.ACCENT));
        if (recommended) option.setTypeface(Typeface.DEFAULT_BOLD);
        return option;
    }

    private void show(AlertDialog value, View content, boolean cancelable) {
        dialog = value;
        value.setCancelable(cancelable);
        value.setCanceledOnTouchOutside(false);
        value.setOnDismissListener(ignored -> { if (dialog == value) dialog = null; });
        value.show();
        decorate(value, false);
        value.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN
                | WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
        StudioStyle.enter(content, true);
    }

    private void decorate(AlertDialog value, boolean destructive) {
        value.getWindow().setBackgroundDrawable(StudioStyle.card(activity, 20));
        Button confirm = value.getButton(AlertDialog.BUTTON_POSITIVE);
        confirm.setAllCaps(false);
        confirm.setTextColor(StudioStyle.INK);
        confirm.setBackground(StudioStyle.control(activity, destructive ? StudioStyle.RECORDING : StudioStyle.ACCENT, 12));
        Button cancel = value.getButton(AlertDialog.BUTTON_NEGATIVE);
        cancel.setAllCaps(false);
        cancel.setMinimumHeight(dp(48));
        confirm.setMinimumHeight(dp(48));
        cancel.setTextColor(destructive || !"Удалить запись".contentEquals(cancel.getText())
                ? StudioStyle.MUTED : StudioStyle.RECORDING);
    }

    private ScrollView scroll(LinearLayout content) {
        ScrollView view = new ScrollView(activity);
        view.addView(content);
        return view;
    }

    private LinearLayout pane() {
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setFocusableInTouchMode(true);
        content.setPadding(dp(20), dp(12), dp(20), dp(6));
        return content;
    }

    private TextView text(String value, int size, int color) {
        TextView text = new TextView(activity);
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        text.setGravity(Gravity.START);
        return text;
    }

    private EditText edit(String hint) {
        EditText field = new EditText(activity);
        field.setSingleLine(true);
        field.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        field.setFilters(new InputFilter[]{new InputFilter.LengthFilter(160)});
        field.setHint(hint);
        field.setContentDescription(hint);
        return field;
    }

    private int dp(int value) { return StudioStyle.dp(activity, value); }

    void dispose() {
        disposed = true;
        if (discardDialog != null) discardDialog.dismiss();
        if (dialog != null) dialog.dismiss();
        worker.shutdownNow();
        saves.shutdown();
    }
}
