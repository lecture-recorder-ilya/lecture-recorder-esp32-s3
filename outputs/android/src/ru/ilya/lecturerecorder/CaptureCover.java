package ru.ilya.lecturerecorder;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.ColorMatrix;
import android.graphics.ColorMatrixColorFilter;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Shader;
import android.os.SystemClock;
import android.view.View;
import android.widget.FrameLayout;

final class CaptureCover extends FrameLayout {
    private final Bitmap wave;
    private final Paint image = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Paint shade = new Paint();
    private final RectF bounds = new RectF();
    private float level;

    CaptureCover(Context context) {
        super(context);
        ColorMatrix graphite = new ColorMatrix();
        graphite.setSaturation(.06f);
        image.setColorFilter(new ColorMatrixColorFilter(graphite));
        wave = BitmapFactory.decodeResource(getResources(), R.drawable.capture_wave);
        setBackground(StudioStyle.surface(context, StudioStyle.RECORDER, 22));
        setClipToOutline(true);
        setWillNotDraw(false);
    }

    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        if (width > 0) shade.setShader(new LinearGradient(0, 0, width, 0,
                new int[]{0xff10191c, 0xef10191c, 0x5010191c},
                new float[]{0f, .42f, 1f}, Shader.TileMode.CLAMP));
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        boolean animate = isShown() && getWindowVisibility() == View.VISIBLE && StudioStyle.motion(this);
        double phase = animate ? (SystemClock.uptimeMillis() % 16000) * (Math.PI / 8000) : 0;
        boolean live = CaptureService.recording && CaptureService.link == CaptureService.Link.CONNECTED;
        float input = animate && live ? Math.min(1f, CaptureService.peak / 12000f) : 0;
        level += (input - level) * .14f;
        float scale = Math.max(getWidth() / (float) wave.getWidth(), getHeight() / (float) wave.getHeight());
        scale *= 1.10f + (animate ? level * .06f : 0);
        float width = wave.getWidth() * scale, height = wave.getHeight() * scale;
        float x = (getWidth() - width) * (.5f + .25f * (float) Math.sin(phase));
        float y = (getHeight() - height) * (.5f + .17f * (float) Math.cos(phase));
        bounds.set(x, y, x + width, y + height);
        canvas.drawBitmap(wave, null, bounds, image);
        canvas.drawRect(0, 0, getWidth(), getHeight(), shade);
        if (animate) postInvalidateDelayed(40);
    }

    @Override protected void onVisibilityChanged(View changedView, int visibility) {
        super.onVisibilityChanged(changedView, visibility);
        if (visibility == VISIBLE) invalidate();
    }
}
