package ru.ilya.lecturerecorder;

import android.content.Context;
import android.animation.ValueAnimator;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.graphics.drawable.StateListDrawable;
import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.TextView;

final class StudioStyle {
    static final int BACKGROUND = 0xff0e1217;
    static final int PANEL = 0xff171e27;
    static final int CONTROL = 0xff202a35;
    static final int LINE = 0xff334252;
    static final int TEXT = 0xffeef3f8;
    static final int MUTED = 0xffa5b4c3;
    static final int ACCENT = 0xffa8d7fa;
    static final int ACTIVE = 0xff263c50;
    static final int RECORDING = 0xffffc0b1;
    private static final int RECORDING_LINE = 0xff915d58;
    static final int GOOD = 0xff9fdfc6;
    static final int WARNING = 0xfff3c287;
    static final int INK = 0xff102135;
    static final int[] SPECTRUM = {0xff6493ba, 0xff7fb3dc, ACCENT, RECORDING, WARNING};
    private static final PathInterpolator MOTION = new PathInterpolator(.2f, .72f, .27f, 1f);

    private StudioStyle() {}

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
                new int[] {0xff202e40, PANEL, PANEL});
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

    static Drawable control(Context context, int color, int radius) {
        return new RippleDrawable(ColorStateList.valueOf(0x28ffffff), surface(context, color, radius), null);
    }

    static void enterPage(View view, int direction) {
        settle(view);
        if (!ValueAnimator.areAnimatorsEnabled()) return;
        view.setAlpha(.78f);
        view.setTranslationX(direction * dp(view.getContext(), 10));
        view.animate().alpha(1f).translationX(0).setDuration(220).setInterpolator(MOTION).start();
    }

    static void moveSelection(View view, float destination, boolean animate) {
        view.animate().cancel();
        if (animate && ValueAnimator.areAnimatorsEnabled()) {
            view.animate().translationX(destination).setDuration(240).setInterpolator(MOTION).start();
        } else {
            view.setTranslationX(destination);
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

    static void recordIcon(TextView button, boolean recording) {
        Drawable icon = new TabIcon(recording ? 4 : 3, INK);
        int size = dp(button.getContext(), 15);
        icon.setBounds(0, 0, size, size);
        button.setCompoundDrawablesRelative(icon, null, null, null);
        button.setCompoundDrawablePadding(dp(button.getContext(), 10));
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
            } else if (index == 3) {
                canvas.drawCircle(9, 9, 6.5f, paint);
            } else {
                canvas.drawRoundRect(3, 3, 15, 15, 2.5f, 2.5f, paint);
            }
            canvas.restore();
        }

        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); }
        @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
}
