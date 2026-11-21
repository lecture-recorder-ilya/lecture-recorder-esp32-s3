package ru.ilya.lecturerecorder;

import android.content.Context;
import android.content.res.ColorStateList;
import android.graphics.Canvas;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.widget.TextView;

final class StudioStyle {
    static final int BACKGROUND = 0xff0c0d12;
    static final int PANEL = 0xff161821;
    static final int CONTROL = 0xff232633;
    static final int LINE = 0xff303343;
    static final int TEXT = 0xfff5f3f8;
    static final int MUTED = 0xffadafc2;
    static final int ACCENT = 0xffc5b5ff;
    static final int ACTIVE = 0xff2c2441;
    static final int LIME = 0xffd9fb83;
    static final int INK = 0xff171b12;
    static final int[] SPECTRUM = {0xff7867ee, 0xffb188ff, 0xffed72bc, 0xffffaa79, 0xffffdb96};

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
