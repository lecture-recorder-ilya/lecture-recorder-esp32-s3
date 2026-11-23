package ru.ilya.lecturerecorder;

import android.content.Context;
import android.animation.ValueAnimator;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Insets;
import android.os.Build;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.view.animation.PathInterpolator;
import android.widget.Button;
import android.widget.TextView;
import android.graphics.Typeface;

final class StudioStyle {
    static final int BACKGROUND = 0xff101517;
    static final int PANEL = 0xff1a2022;
    static final int CONTROL = 0xff273034;
    static final int LINE = 0xff4e6061;
    static final int TEXT = 0xffeff6f4;
    static final int MUTED = 0xffb1c3c1;
    static final int ACCENT = 0xff80e2ce;
    static final int ACTIVE = 0xff214440;
    static final int RECORDING = 0xffffc0b1;
    private static final int RECORDING_LINE = 0xff915d58;
    static final int GOOD = 0xff9fdfc6;
    static final int WARNING = 0xfff3c287;
    static final int INK = 0xff102725;
    static final int ACTION_HEIGHT = 48;
    static final int PAGE_INSET = 16;
    static final int CARD_RADIUS = 18;
    static final int[] SPECTRUM = {0xff5d9d96, 0xff6cbcaf, ACCENT, RECORDING, WARNING};
    private static final PathInterpolator MOTION = new PathInterpolator(.2f, .72f, .27f, 1f);

    private StudioStyle() {}

    static void fitWindow(Window window, View root, int horizontal, int top, int bottom) {
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false);
            window.setStatusBarColor(Color.TRANSPARENT);
            window.setNavigationBarColor(Color.TRANSPARENT);
            window.setNavigationBarContrastEnforced(false);
            android.view.WindowInsetsController controller = window.getDecorView().getWindowInsetsController();
            if (controller != null) controller.setSystemBarsAppearance(0,
                    android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                            | android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
        } else {
            window.setStatusBarColor(BACKGROUND);
            window.setNavigationBarColor(BACKGROUND);
        }
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets bars = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout());
                Insets keyboard = insets.getInsets(WindowInsets.Type.ime());
                view.setPadding(bars.left + horizontal, bars.top + top,
                        bars.right + horizontal, Math.max(bars.bottom, keyboard.bottom) + bottom);
                return WindowInsets.CONSUMED;
            }
            view.setPadding(insets.getSystemWindowInsetLeft() + horizontal,
                    insets.getSystemWindowInsetTop() + top, insets.getSystemWindowInsetRight() + horizontal,
                    insets.getSystemWindowInsetBottom() + bottom);
            return insets.consumeSystemWindowInsets();
        });
    }

    static void fitLabel(TextView view, int min, int max) {
        view.setSingleLine();
        view.setHorizontallyScrolling(false);
        view.setAutoSizeTextTypeUniformWithConfiguration(min, max, 1,
                android.util.TypedValue.COMPLEX_UNIT_SP);
    }

    static int dp(Context context, int value) {
        return Math.round(context.getResources().getDisplayMetrics().density * value);
    }

    static GradientDrawable surface(Context context, int color, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(context, radius));
        return drawable;
    }

    static GradientDrawable card(Context context, int radius) {
        GradientDrawable drawable = surface(context, PANEL, radius);
        drawable.setStroke(dp(context, 1), LINE);
        return drawable;
    }

    static GradientDrawable recorderCard(Context context, boolean recording) {
        GradientDrawable drawable = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[] {0xff233735, PANEL, PANEL});
        drawable.setCornerRadius(dp(context, 20));
        drawable.setStroke(dp(context, 1), recording ? RECORDING_LINE : LINE);
        return drawable;
    }

    static void settle(View view) {
        view.animate().cancel();
        view.setAlpha(1f);
        view.setTranslationX(0);
        view.setTranslationY(0);
        view.setScaleX(1f);
        view.setScaleY(1f);
    }

    static void enter(View view, boolean opening) {
        settle(view);
        if (!ValueAnimator.areAnimatorsEnabled()) return;
        view.setAlpha(.86f);
        view.setTranslationY(dp(view.getContext(), opening ? 6 : 4));
        view.animate().alpha(1f).translationY(0).setDuration(opening ? 180 : 150)
                .setInterpolator(MOTION).start();
    }

    static void changeAction(View view) {
        settle(view);
        if (!ValueAnimator.areAnimatorsEnabled()) return;
        view.setAlpha(.76f);
        view.setScaleX(.985f);
        view.setScaleY(.985f);
        view.animate().alpha(1f).scaleX(1f).scaleY(1f).setDuration(140)
                .setInterpolator(MOTION).start();
    }

    static TextView title(Context context, String label) {
        TextView title = new TextView(context);
        title.setText(label);
        title.setTextColor(TEXT);
        title.setTextSize(26);
        title.setTypeface(Typeface.DEFAULT_BOLD);
        title.setLetterSpacing(-.02f);
        if (android.os.Build.VERSION.SDK_INT >= 28) title.setAccessibilityHeading(true);
        return title;
    }

    static Button action(Context context, String label, Runnable command, boolean primary) {
        Button button = new Button(context);
        button.setText(label);
        button.setTextSize(15);
        button.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        button.setAllCaps(false);
        button.setMinimumHeight(dp(context, ACTION_HEIGHT));
        button.setMinHeight(dp(context, ACTION_HEIGHT));
        button.setPadding(dp(context, 12), dp(context, 6), dp(context, 12), dp(context, 6));
        button.setOnClickListener(view -> command.run());
        actionTone(button, primary ? ACCENT : CONTROL, primary ? INK : TEXT);
        return button;
    }

    static void actionTone(Button button, int fill, int text) {
        button.setTextColor(actionColors(text));
        button.setBackground(control(button.getContext(), fill, 12));
    }

    static ColorStateList actionColors(int color) {
        return new ColorStateList(new int[][] {{-android.R.attr.state_enabled}, {}},
                new int[] {0xff839895, color});
    }

    static Drawable control(Context context, int color, int radius) {
        StateListDrawable states = new StateListDrawable();
        GradientDrawable focus = surface(context, color, radius);
        focus.setStroke(dp(context, 2), ACCENT);
        states.addState(new int[] {-android.R.attr.state_enabled}, surface(context, color == 0 ? 0 : PANEL, radius));
        states.addState(new int[] {android.R.attr.state_focused}, focus);
        states.addState(new int[0], surface(context, color, radius));
        return new RippleDrawable(ColorStateList.valueOf(0x28ffffff), states, null);
    }

    static void enterPage(View view, int direction, boolean vertical) {
        settle(view);
        if (!ValueAnimator.areAnimatorsEnabled()) return;
        float offset = Integer.signum(direction) * dp(view.getContext(), 16);
        view.setAlpha(.86f);
        if (vertical) view.setTranslationY(offset);
        else view.setTranslationX(offset);
        view.animate().alpha(1f).translationX(0f).translationY(0f).setDuration(190)
                .setInterpolator(MOTION).start();
    }

    static void moveSelection(View view, float x, float y, boolean animate) {
        view.animate().cancel();
        if (animate && ValueAnimator.areAnimatorsEnabled()) {
            view.animate().translationX(x).translationY(y).setDuration(140).setInterpolator(MOTION).start();
        } else {
            view.setTranslationX(x);
            view.setTranslationY(y);
        }
    }

    static Drawable lessonOption(Context context) {
        GradientDrawable selected = surface(context, ACTIVE, 12);
        selected.setStroke(dp(context, 1), ACCENT);
        GradientDrawable normal = surface(context, CONTROL, 12);
        normal.setStroke(dp(context, 1), LINE);
        StateListDrawable states = new StateListDrawable();
        states.addState(new int[]{android.R.attr.state_checked}, selected);
        states.addState(new int[0], normal);
        return new RippleDrawable(ColorStateList.valueOf(0x24ffffff), states, null);
    }

    static void recordIcon(TextView button, boolean recording, boolean animate) {
        Drawable current = button.getCompoundDrawablesRelative()[0];
        RecordGlyph glyph;
        if (current instanceof RecordGlyph) {
            glyph = (RecordGlyph) current;
        } else {
            int size = dp(button.getContext(), 13);
            glyph = new RecordGlyph(size);
            button.setCompoundDrawablesRelative(glyph, null, null, null);
            button.setCompoundDrawablePadding(dp(button.getContext(), 10));
        }
        glyph.setRecording(recording, animate && button.isShown());
    }

    private static final class RecordGlyph extends GradientDrawable {
        private final ValueAnimator corners = new ValueAnimator();

        RecordGlyph(int size) {
            setColor(INK);
            setBounds(0, 0, size, size);
            corners.setDuration(190);
            corners.setInterpolator(MOTION);
            corners.addUpdateListener(frame -> setCornerRadius((float) frame.getAnimatedValue()));
        }

        void setRecording(boolean recording, boolean animate) {
            float radius = getBounds().width() * (recording ? .18f : .5f);
            corners.cancel();
            if (animate && ValueAnimator.areAnimatorsEnabled() && radius != getCornerRadius()) {
                corners.setFloatValues(getCornerRadius(), radius);
                corners.start();
            } else {
                setCornerRadius(radius);
            }
        }
    }

    static void tabIcon(TextView tab, int index, int color) {
        Drawable icon = new TabIcon(index, color);
        int size = dp(tab.getContext(), 18);
        icon.setBounds(0, 0, size, size);
        tab.setCompoundDrawablesRelative(null, icon, null, null);
        tab.setCompoundDrawablePadding(dp(tab.getContext(), 4));
    }

    private static final class TabIcon extends Drawable {
        private final int index;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);

        TabIcon(int index, int color) {
            this.index = index;
            paint.setColor(color);
            paint.setStrokeWidth(1.5f);
            paint.setStrokeCap(Paint.Cap.ROUND);
        }

        @Override public void draw(Canvas canvas) {
            Rect box = getBounds();
            canvas.save();
            canvas.translate(box.left, box.top);
            canvas.scale(box.width() / 18f, box.height() / 18f);
            if (index == 0) {
                canvas.drawRect(7, 1.5f, 11, 3, paint);
                canvas.drawRect(6, 3, 12, 9, paint);
                canvas.drawRect(7, 9, 11, 10.5f, paint);
                canvas.drawLine(3.5f, 7.5f, 3.5f, 10.5f, paint);
                canvas.drawLine(14.5f, 7.5f, 14.5f, 10.5f, paint);
                canvas.drawLine(3.5f, 10.5f, 6, 13, paint);
                canvas.drawLine(14.5f, 10.5f, 12, 13, paint);
                canvas.drawLine(6, 13, 12, 13, paint);
                canvas.drawLine(9, 13, 9, 16.5f, paint);
            } else if (index == 1) {
                float[] heights = {2, 4, 6.5f, 3.5f, 2};
                for (int i = 0; i < heights.length; i++) {
                    float x = 3 + 3 * i;
                    canvas.drawLine(x, 9 - heights[i], x, 9 + heights[i], paint);
                }
            } else if (index == 2) {
                for (int i = 0; i < 3; i++) {
                    float y = 4 + 5 * i;
                    float knob = i == 1 ? 11 : 6;
                    canvas.drawLine(2, y, knob - 2, y, paint);
                    canvas.drawLine(knob + 2, y, 16, y, paint);
                    canvas.drawCircle(knob, y, 1.8f, paint);
                }
            } else if (index == 5) {
                paint.setStyle(Paint.Style.STROKE);
                canvas.drawRoundRect(2.5f, 3, 15.5f, 15, 2, 2, paint);
                canvas.drawLine(6, 7, 12, 7, paint);
                canvas.drawLine(6, 11, 12, 11, paint);
                paint.setStyle(Paint.Style.FILL);
            }
            canvas.restore();
        }

        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); }
        @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
}
