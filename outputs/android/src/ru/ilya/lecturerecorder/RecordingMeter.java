package ru.ilya.lecturerecorder;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.os.SystemClock;
import android.view.View;

final class RecordingMeter extends View {
    private static final int COLUMNS = 44;
    private static final int ROWS = 6;
    private static final long SAMPLE_INTERVAL_MS = 85;

    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int[] history = new int[COLUMNS];
    private int cursor;
    private long nextSample;
    private boolean recording;

    RecordingMeter(Context context) {
        super(context);
        setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        setBackground(StudioStyle.surface(context, StudioStyle.BACKGROUND, 14));
    }

    void setRecording(boolean active) {
        if (recording == active) return;
        recording = active;
        java.util.Arrays.fill(history, 0);
        cursor = 0;
        nextSample = 0;
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (recording && CaptureService.recording) {
            long now = SystemClock.uptimeMillis();
            if (now >= nextSample) {
                int peak = CaptureService.link == CaptureService.Link.CONNECTED ? CaptureService.peak : 0;
                float db = peak == 0 ? -54 : (float) (20 * Math.log10(peak / 32768.0));
                history[cursor] = Math.round(ROWS * Math.max(0, (db + 54) / 54));
                cursor = (cursor + 1) % COLUMNS;
                nextSample = now + SAMPLE_INTERVAL_MS;
            }
            postInvalidateDelayed(nextSample - now);
        }

        float inset = StudioStyle.dp(getContext(), 10);
        float stepX = (getWidth() - 2 * inset) / COLUMNS;
        float stepY = (getHeight() - 2 * inset) / ROWS;
        float width = Math.min(stepX * .68f, stepY * .7f);
        if (width <= 0) return;

        for (int i = 0; i < COLUMNS; i++) {
            int level = history[(cursor + i) % COLUMNS];
            float x = inset + (i + .5f) * stepX;
            for (int row = 0; row < ROWS; row++) {
                float y = getHeight() - inset - (row + .5f) * stepY;
                if (row < level) {
                    paint.setColor(StudioStyle.SPECTRUM[row * (StudioStyle.SPECTRUM.length - 1) / (ROWS - 1)]);
                    canvas.drawRoundRect(x - width / 2, y - width / 2, x + width / 2, y + width / 2,
                            .22f * width, .22f * width, paint);
                } else {
                    paint.setColor(row == 0 ? 0xff48425b : 0xff2a283a);
                    canvas.drawCircle(x, y, width * .23f, paint);
                }
            }
        }
    }
}
