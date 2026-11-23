package ru.ilya.lecturerecorder;

import android.animation.ValueAnimator;
import android.app.Activity;
import android.app.Dialog;
import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.view.animation.LinearInterpolator;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.IOException;
import java.util.function.IntConsumer;

final class EspPairing {
    static final int BLUETOOTH_PERMISSION = 10;
    static final int ENABLE_BLUETOOTH = 11;
    private static final int TEXT = StudioStyle.TEXT;
    private static final int MUTED = StudioStyle.MUTED;
    private static final int ACCENT = StudioStyle.ACCENT;

    private final Activity activity;
    private final IntConsumer onPaired;
    private final Runnable onClosed;
    private final SharedPreferences settings;
    private Dialog dialog;
    private TextView status;
    private Button action;
    private LoadingDots dots;
    private Thread worker;
    private boolean awaitingBluetooth;

    EspPairing(Activity activity, IntConsumer onPaired, Runnable onClosed) {
        this.activity = activity;
        this.onPaired = onPaired;
        this.onClosed = onClosed;
        settings = activity.getSharedPreferences("settings", 0);
    }

    void open() {
        LinearLayout sheet = new LinearLayout(activity);
        sheet.setOrientation(LinearLayout.VERTICAL);
        sheet.setGravity(Gravity.CENTER_HORIZONTAL);
        sheet.setPadding(dp(22), dp(24), dp(22), dp(24));
        sheet.setBackground(StudioStyle.card(activity, 24));
        sheet.setFocusableInTouchMode(true);

        TextView title = text("Подключить ClipMic", 23, TEXT);
        title.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        if (Build.VERSION.SDK_INT >= 28) title.setAccessibilityHeading(true);
        sheet.addView(title, new LinearLayout.LayoutParams(-1, -2));
        dots = new LoadingDots(activity);
        dots.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        sheet.addView(dots, spaced(-1, dp(30), 10));

        status = text("", 15, MUTED);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        status.setVisibility(View.GONE);
        sheet.addView(status, spaced(-1, -2, 12));

        action = new Button(activity);
        action.setAllCaps(false);
        action.setTextSize(15);
        action.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        action.setTextColor(StudioStyle.INK);
        action.setBackground(new RippleDrawable(ColorStateList.valueOf(0x25000000), surface(ACCENT, 12), null));
        action.setVisibility(View.GONE);
        sheet.addView(action, spaced(-1, dp(50), 12));

        dialog = new Dialog(activity);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setContentView(sheet);
        dialog.setCanceledOnTouchOutside(true);
        Window window = dialog.getWindow();
        window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        window.setDimAmount(.52f);
        boolean landscape = activity.getResources().getConfiguration().orientation == Configuration.ORIENTATION_LANDSCAPE;
        window.setGravity(landscape ? Gravity.CENTER : Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        WindowManager.LayoutParams attributes = window.getAttributes();
        attributes.y = landscape ? 0 : dp(16);
        window.setAttributes(attributes);
        dialog.setOnDismissListener(ignored -> {
            dots.stop();
            if (worker != null) worker.interrupt();
            worker = null;
            onClosed.run();
        });
        dialog.show();
        int width = activity.getResources().getConfiguration().screenWidthDp;
        window.setLayout(dp(Math.min(420, width - 32)), WindowManager.LayoutParams.WRAP_CONTENT);
        sheet.requestFocus();
        showProgress();
        sheet.post(() -> advance(true));
    }

    void permissionResult(int[] grants) {
        if (!showing()) return;
        if (grants.length == 0) {
            showPermission();
            return;
        }
        for (int grant : grants) {
            if (grant != 0) {
                showPermission();
                return;
            }
        }
        advance(true);
    }

    void bluetoothEnableResult(int result) {
        awaitingBluetooth = false;
        if (!showing()) return;
        if (result == Activity.RESULT_OK) advance(false);
        else showEnableBluetooth();
    }

    void close() {
        if (dialog != null) dialog.dismiss();
    }

    private void advance(boolean prompt) {
        if (!showing() || worker != null || awaitingBluetooth || CaptureService.recording) return;
        String[] permissions = Build.VERSION.SDK_INT >= 31
                ? new String[]{"android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH_CONNECT"}
                : new String[]{"android.permission.ACCESS_FINE_LOCATION"};
        for (String permission : permissions) {
            if (activity.checkSelfPermission(permission) != 0) {
                showPermission();
                if (prompt) activity.requestPermissions(permissions, BLUETOOTH_PERMISSION);
                return;
            }
        }

        BluetoothManager manager = activity.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null) {
            showAction("Bluetooth недоступен", "Закрыть", this::close);
            return;
        }
        if (!adapter.isEnabled()) {
            showEnableBluetooth();
            if (prompt) requestBluetooth();
            return;
        }

        connect();
    }

    private void showPermission() {
        showAction("Нужен доступ к Bluetooth", "Разрешить", () -> advance(true));
    }

    private void showEnableBluetooth() {
        showAction("Bluetooth выключен", "Включить Bluetooth", this::requestBluetooth);
    }

    private void requestBluetooth() {
        if (!showing() || awaitingBluetooth) return;
        awaitingBluetooth = true;
        try {
            activity.startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE), ENABLE_BLUETOOTH);
        } catch (ActivityNotFoundException | SecurityException error) {
            awaitingBluetooth = false;
            showAction("Включи Bluetooth в настройках телефона", "Повторить", () -> advance(false));
        }
    }

    private void connect() {
        if (!showing() || worker != null || CaptureService.recording) return;
        Context app = activity.getApplicationContext();
        String cachedAddress = settings.getString("ble_address", "");
        showProgress();
        worker = new Thread(() -> {
            try {
                EspDeviceConnection device = EspDeviceConnection.bluetooth(app, cachedAddress);
                activity.runOnUiThread(() -> finish(device));
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
            } catch (Exception error) {
                activity.runOnUiThread(() -> {
                    if (!showing()) return;
                    worker = null;
                    String message = error instanceof IOException && error.getMessage() != null
                            ? error.getMessage() : "Не удалось подключить ESP";
                    BluetoothManager manager = activity.getSystemService(BluetoothManager.class);
                    BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
                    if (adapter != null && !adapter.isEnabled()) showEnableBluetooth();
                    else showAction(message, "Повторить", () -> advance(true));
                });
            }
        }, "Connect ESP");
        worker.start();
    }

    private void finish(EspDeviceConnection device) {
        if (!showing()) return;
        worker = null;
        settings.edit().putString(EspDeviceConnection.PAIRING_MODE, EspDeviceConnection.BONDED)
                .putString("transport", "ble")
                .putString("esp_paired_transport", "ble").putString("ble_address", device.address).apply();
        onPaired.accept(device.battery);
        dialog.dismiss();
    }

    private void showProgress() {
        status.setText("На включённом диктофоне удержи кнопку записи или BOOT одну секунду и подтверди сопряжение на телефоне.");
        status.setVisibility(View.VISIBLE);
        action.setVisibility(View.GONE);
        dots.start();
    }

    private void showAction(String message, String label, Runnable callback) {
        dots.stop();
        status.setText(message);
        status.setVisibility(message.isEmpty() ? View.GONE : View.VISIBLE);
        action.setText(label);
        action.setOnClickListener(view -> callback.run());
        action.setVisibility(View.VISIBLE);
    }

    private boolean showing() {
        return dialog != null && dialog.isShowing();
    }

    private TextView text(String value, int size, int color) {
        TextView view = new TextView(activity);
        view.setGravity(Gravity.CENTER);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        return view;
    }

    private GradientDrawable surface(int color, int radius) {
        GradientDrawable shape = new GradientDrawable();
        shape.setColor(color);
        shape.setCornerRadius(dp(radius));
        return shape;
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private LinearLayout.LayoutParams spaced(int width, int height, int gap) {
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(width, height);
        layout.topMargin = dp(gap);
        return layout;
    }

    private final class LoadingDots extends View {
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final ValueAnimator animation = ValueAnimator.ofFloat(0f, 1f);
        private float phase;

        LoadingDots(Context context) {
            super(context);
            paint.setColor(ACCENT);
            animation.setDuration(1080);
            animation.setRepeatCount(ValueAnimator.INFINITE);
            animation.setInterpolator(new LinearInterpolator());
            animation.addUpdateListener(value -> {
                phase = (float) value.getAnimatedValue();
                invalidate();
            });
        }

        void start() {
            setVisibility(View.VISIBLE);
            if (!animation.isStarted()) animation.start();
        }

        void stop() {
            animation.cancel();
            setVisibility(View.GONE);
        }

        @Override protected void onDraw(Canvas canvas) {
            float centerX = getWidth() * .5f;
            float centerY = getHeight() * .5f;
            for (int dot = 0; dot < 3; dot++) {
                float wave = (float) (0.5 + 0.5 * Math.cos(2 * Math.PI * (phase - dot * .18)));
                paint.setAlpha((int) (90 + 165 * wave));
                canvas.drawCircle(centerX + (dot - 1) * dp(16), centerY - dp(4) * wave,
                        dp(3) + dp(1) * wave, paint);
            }
        }
    }
}
