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
import android.view.View;
import android.view.animation.PathInterpolator;
import android.widget.TextView;

final class StudioStyle {
    static final int BACKGROUND = 0xff10131c;
    static final int PANEL = 0xff191e2b;
    static final int CONTROL = 0xff222939;
    static final int LINE = 0xff343d52;
    static final int TEXT = 0xfff4f6fc;
    static final int MUTED = 0xffa9b3c9;
    static final int ACCENT = 0xffc4c6ff;
    static final int ACTIVE = 0xff303653;
    static final int RECORDING = 0xffffb2a5;
    static final int GOOD = 0xff9fdfc6;
    static final int WARNING = 0xfff3c287;
    static final int INK = 0xff1d2040;
    static final int[] SPECTRUM = {0xff747ed2, 0xffa9afff, 0xffc4c6ff, 0xffffb2a5, 0xfff3c287};

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

    static GradientDrawable recorderCard(Context context) {
        GradientDrawable drawable = new GradientDrawable(GradientDrawable.Orientation.TL_BR,
                new int[] {0xff252c43, PANEL, PANEL});
        drawable.setCornerRadius(dp(context, 22));
        drawable.setStroke(dp(context, 1), LINE);
        return drawable;
    }

    static void settle(View view) {
        view.animate().cancel();
        view.setAlpha(1f);
        view.setTranslationY(0);
    }

    static void enter(View view, boolean opening) {
        settle(view);
        if (!ValueAnimator.areAnimatorsEnabled()) return;
        view.setAlpha(.86f);
        view.setTranslationY(dp(view.getContext(), opening ? 8 : 4));
        view.animate().alpha(1f).translationY(0).setDuration(opening ? 210 : 155)
                .setInterpolator(new PathInterpolator(.22f, .75f, .24f, 1f)).start();
    }

    static Drawable control(Context context, int color, int radius) {
        return new RippleDrawable(ColorStateList.valueOf(0x28ffffff), surface(context, color, radius), null);
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
            } else {
                for (int i = 0; i < 3; i++) {
                    float y = 4 + 5 * i;
                    float knob = i == 1 ? 11 : 6;
                    canvas.drawLine(2, y, knob - 2, y, paint);
                    canvas.drawLine(knob + 2, y, 16, y, paint);
                    canvas.drawCircle(knob, y, 1.8f, paint);
                }
            }
            canvas.restore();
        }

        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); }
        @Override public void setColorFilter(ColorFilter filter) { paint.setColorFilter(filter); }
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }
}
