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
import android.widget.FrameLayout;

final class CaptureCover extends FrameLayout {
    private final Bitmap wave;
    private final Paint image = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Paint shade = new Paint();
    private final RectF bounds = new RectF();

    CaptureCover(Context context) {
        super(context);
        ColorMatrix graphite = new ColorMatrix();
        graphite.setSaturation(0f);
        image.setColorFilter(new ColorMatrixColorFilter(graphite));
        wave = BitmapFactory.decodeResource(getResources(), R.drawable.capture_wave);
        setBackground(StudioStyle.surface(context, StudioStyle.RECORDER, 22));
        setClipToOutline(true);
        setWillNotDraw(false);
    }

    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        if (width <= 0 || height <= 0) return;
        shade.setShader(new LinearGradient(0, 0, width, 0,
                new int[]{0xff17191c, 0xf017191c, 0x8c17191c},
                new float[]{0f, .42f, 1f}, Shader.TileMode.CLAMP));
        float scale = Math.max(width / (float) wave.getWidth(), height / (float) wave.getHeight());
        float imageWidth = wave.getWidth() * scale, imageHeight = wave.getHeight() * scale;
        float left = (width - imageWidth) * .5f, top = (height - imageHeight) * .5f;
        bounds.set(left, top, left + imageWidth, top + imageHeight);
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.drawBitmap(wave, null, bounds, image);
        canvas.drawRect(0, 0, getWidth(), getHeight(), shade);
    }
}
