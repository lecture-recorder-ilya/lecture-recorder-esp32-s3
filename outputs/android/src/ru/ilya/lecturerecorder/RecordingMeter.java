package ru.ilya.lecturerecorder;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.os.SystemClock;
import android.view.View;
import java.util.Arrays;

final class RecordingMeter extends View {
    private static final int COLUMNS = 54;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final float[] levels = new float[COLUMNS];
    private int cursor;
    private long nextSample;
    private boolean recording;

    RecordingMeter(Context context) {
        super(context);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        paint.setStrokeCap(Paint.Cap.ROUND);
    }

    void setRecording(boolean active) {
        if (recording == active) return;
        recording = active;
        Arrays.fill(levels, 0);
        cursor = 0;
        nextSample = 0;
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        boolean live = recording && CaptureService.recording;
        boolean scrolling = live && StudioStyle.motion(this);
        if (live) {
            long now = SystemClock.uptimeMillis();
            if (now >= nextSample) {
                int peak = CaptureService.link == CaptureService.Link.CONNECTED ? CaptureService.peak : 0;
                float db = peak <= 0 ? -54f : (float) (20 * Math.log10(peak / 32768.0));
                levels[cursor] = Math.max(0f, Math.min(1f, (db + 54f) / 54f));
                cursor = (cursor + 1) % COLUMNS;
                nextSample = now + (scrolling ? 110 : 1000);
            }
            postInvalidateDelayed(Math.max(1, nextSample - now));
        }

        float step = getWidth() / (float) COLUMNS;
        float mid = getHeight() * .5f;
        paint.setStrokeWidth(Math.max(2f, step * .30f));
        float current = levels[(cursor + COLUMNS - 1) % COLUMNS];
        for (int i = 0; i < COLUMNS; i++) {
            float x = step * (i + .5f);
            float level = scrolling ? levels[(cursor + i) % COLUMNS] : 0f;
            float height = Math.max(i % 9 == 0 ? mid * .19f : mid * .06f, mid * .91f * level);
            boolean filled = scrolling ? level > 0 : live && i < Math.round(current * COLUMNS);
            paint.setColor(filled ? StudioStyle.ACCENT : 0xffa0b1b1);
            canvas.drawLine(x, mid - height, x, mid + height, paint);
        }
    }
}
