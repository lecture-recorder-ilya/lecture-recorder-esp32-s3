package ru.ilya.lecturerecorder;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.util.Arrays;
import java.util.Comparator;

final class RecorderModelView extends View {
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Mesh mesh;
    private float yaw = -0.30f;
    private float downX, downY, lastX;
    private boolean dragging;

    RecorderModelView(Context context) {
        super(context);
        mesh = readMesh(context);
        if (android.os.Build.VERSION.SDK_INT < 29) setLayerType(View.LAYER_TYPE_SOFTWARE, null);
        setFocusable(true);
        setClickable(true);
        setContentDescription("Вращаемая 3D-модель корпуса ClipMic");
    }

    float rotation() {
        return yaw;
    }

    void setYaw(float angle) {
        yaw = angle;
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (mesh == null) return;
        float width = getWidth(), height = getHeight();
        float scale = Math.min(width * .83f, height * 1.55f);
        float centerX = width * .5f, centerY = height * .48f;
        canvas.drawColor(0xff151619);
        paint.setColor(0xff101113);
        canvas.drawOval(centerX - scale * .42f, centerY + height * .11f,
                centerX + scale * .42f, centerY + height * .18f, paint);
        paint.setColor(Color.WHITE);
        mesh.draw(canvas, paint, scale, centerX, centerY);
    }

    @Override public boolean onTouchEvent(MotionEvent event) {
        switch (event.getActionMasked()) {
            case MotionEvent.ACTION_DOWN:
                downX = lastX = event.getX();
                downY = event.getY();
                dragging = false;
                return true;
            case MotionEvent.ACTION_MOVE:
                float deltaX = event.getX() - downX;
                float deltaY = event.getY() - downY;
                if (!dragging && Math.abs(deltaX) > Math.abs(deltaY)
                        && Math.abs(deltaX) > ViewConfiguration.get(getContext()).getScaledTouchSlop()) {
                    dragging = true;
                    getParent().requestDisallowInterceptTouchEvent(true);
                }
                if (dragging) turn((event.getX() - lastX) * 4.8f / Math.max(1, getWidth()));
                lastX = event.getX();
                return true;
            case MotionEvent.ACTION_UP:
                if (!dragging) performClick();
                dragging = false;
                getParent().requestDisallowInterceptTouchEvent(false);
                return true;
            case MotionEvent.ACTION_CANCEL:
                dragging = false;
                getParent().requestDisallowInterceptTouchEvent(false);
                return true;
            default:
                return super.onTouchEvent(event);
        }
    }

    @Override public boolean performClick() {
        super.performClick();
        return true;
    }

    @Override public boolean onKeyDown(int key, KeyEvent event) {
        if (key == KeyEvent.KEYCODE_DPAD_LEFT || key == KeyEvent.KEYCODE_DPAD_RIGHT) {
            turn(key == KeyEvent.KEYCODE_DPAD_LEFT ? -.3f : .3f);
            return true;
        }
        return super.onKeyDown(key, event);
    }

    @Override public void onInitializeAccessibilityNodeInfo(AccessibilityNodeInfo info) {
        super.onInitializeAccessibilityNodeInfo(info);
        info.addAction(new AccessibilityNodeInfo.AccessibilityAction(
                AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD, "Повернуть влево"));
        info.addAction(new AccessibilityNodeInfo.AccessibilityAction(
                AccessibilityNodeInfo.ACTION_SCROLL_FORWARD, "Повернуть вправо"));
    }

    @Override public boolean performAccessibilityAction(int action, android.os.Bundle arguments) {
        if (action == AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
                || action == AccessibilityNodeInfo.ACTION_SCROLL_FORWARD) {
            turn(action == AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD ? -.3f : .3f);
            return true;
        }
        return super.performAccessibilityAction(action, arguments);
    }

    private void turn(float amount) {
        setYaw((yaw + amount) % ((float) Math.PI * 2));
    }

    private Mesh readMesh(Context context) {
        try (DataInputStream data = new DataInputStream(new BufferedInputStream(
                context.getResources().openRawResource(R.raw.clipmic_case)))) {
            int vertices = data.readInt(), faces = data.readInt();
            if (vertices < 3 || vertices > 8000 || faces < 1 || faces > 10000) return null;
            Mesh mesh = new Mesh(vertices, faces);
            for (int index = 0; index < mesh.points.length; index++) mesh.points[index] = data.readFloat();
            for (int index = 0; index < faces; index++) {
                int a = data.readUnsignedShort(), b = data.readUnsignedShort(), c = data.readUnsignedShort();
                if (a >= vertices || b >= vertices || c >= vertices) return null;
                mesh.faces[index] = new Face(a, b, c);
            }
            return mesh;
        } catch (IOException ignored) {
            return null;
        }
    }

    private static final class Face {
        final int[] vertices;
        float depth;
        int color;

        Face(int a, int b, int c) {
            vertices = new int[]{a, b, c};
        }
    }

    private final class Mesh {
        private final float[] points, oriented, projected, triangles;
        private final int[] colors;
        private final Face[] faces;
        private final Comparator<Face> backToFront = (a, b) -> Float.compare(b.depth, a.depth);

        Mesh(int vertices, int faceCount) {
            points = new float[vertices * 3];
            oriented = new float[points.length];
            projected = new float[vertices * 2];
            triangles = new float[faceCount * 6];
            colors = new int[faceCount * 3];
            faces = new Face[faceCount];
        }

        void draw(Canvas canvas, Paint material, float scale, float centerX, float centerY) {
            float sinYaw = (float) Math.sin(yaw), cosYaw = (float) Math.cos(yaw);
            float sinPitch = .48f, cosPitch = .877f;
            float sinRoll = -.275f, cosRoll = .961f;
            for (int index = 0, screen = 0; index < points.length; index += 3, screen += 2) {
                float x = points[index], y = points[index + 1], z = points[index + 2];
                float horizontal = x * cosYaw + z * sinYaw;
                float depth = z * cosYaw - x * sinYaw;
                float vertical = y * cosPitch - depth * sinPitch;
                float distance = y * sinPitch + depth * cosPitch;
                oriented[index] = horizontal;
                oriented[index + 1] = vertical;
                oriented[index + 2] = distance;
                float perspective = scale / (1.05f + distance * .56f);
                projected[screen] = centerX + (horizontal * cosRoll - vertical * sinRoll) * perspective;
                projected[screen + 1] = centerY + (horizontal * sinRoll + vertical * cosRoll) * perspective;
            }
            for (Face face : faces) {
                int a = face.vertices[0] * 3, b = face.vertices[1] * 3, c = face.vertices[2] * 3;
                float ux = oriented[b] - oriented[a], uy = oriented[b + 1] - oriented[a + 1];
                float uz = oriented[b + 2] - oriented[a + 2];
                float vx = oriented[c] - oriented[a], vy = oriented[c + 1] - oriented[a + 1];
                float vz = oriented[c + 2] - oriented[a + 2];
                float nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
                float length = (float) Math.sqrt(nx * nx + ny * ny + nz * nz);
                float facing = length == 0 ? 0 : Math.abs((nx * .24f + ny * -.52f + nz * -.82f) / length);
                face.color = Color.rgb((int) (92 + facing * 152), (int) (35 + facing * 65), (int) (37 + facing * 60));
                face.depth = oriented[a + 2] + oriented[b + 2] + oriented[c + 2];
            }
            Arrays.sort(faces, backToFront);
            int cursor = 0, tint = 0;
            for (Face face : faces) {
                for (int point : face.vertices) {
                    triangles[cursor++] = projected[point * 2];
                    triangles[cursor++] = projected[point * 2 + 1];
                    colors[tint++] = face.color;
                }
            }
            canvas.drawVertices(Canvas.VertexMode.TRIANGLES, triangles.length, triangles, 0,
                    null, 0, colors, 0, null, 0, 0, material);
        }
    }
}
