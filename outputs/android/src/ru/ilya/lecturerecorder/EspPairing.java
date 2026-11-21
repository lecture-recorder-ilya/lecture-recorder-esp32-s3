package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.os.Build;
import android.text.InputFilter;
import android.text.InputType;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.IOException;
import java.util.Locale;
import java.util.function.IntConsumer;

final class EspPairing {
    static final int BLUETOOTH_PERMISSION = 10;

    private final Activity activity;
    private final IntConsumer onPaired;
    private final Runnable onClosed;
    private final SharedPreferences settings;
    private AlertDialog dialog;
    private EditText code;
    private TextView status;
    private Button connect;
    private Thread worker;

    EspPairing(Activity activity, IntConsumer onPaired, Runnable onClosed) {
        this.activity = activity;
        this.onPaired = onPaired;
        this.onClosed = onClosed;
        settings = activity.getSharedPreferences("settings", 0);
    }

    void open() {
        LinearLayout content = new LinearLayout(activity);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(10), dp(20), dp(8));
        code = new EditText(activity);
        code.setSingleLine();
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        code.setImportantForAutofill(View.IMPORTANT_FOR_AUTOFILL_NO);
        code.setFilters(new InputFilter[]{new InputFilter.LengthFilter(32)});
        code.setHint(settings.getString("token", "").isEmpty() ? "Код устройства" : "Код устройства сохранён");
        content.addView(code, spaced());
        status = new TextView(activity);
        status.setTextColor(Color.LTGRAY);
        status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        status.setVisibility(View.GONE);
        content.addView(status, spaced());

        ScrollView scroll = new ScrollView(activity);
        scroll.addView(content);
        dialog = new AlertDialog.Builder(activity).setTitle("Подключить ESP по Bluetooth").setView(scroll)
                .setPositiveButton("Подключить", null).setNegativeButton("Отмена", null).create();
        dialog.setOnDismissListener(ignored -> {
            if (worker != null) worker.interrupt();
            worker = null;
            onClosed.run();
        });
        dialog.getWindow().setSoftInputMode(android.view.WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
        dialog.show();
        connect = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
        connect.setOnClickListener(view -> connect());
    }

    void permissionResult(int[] grants) {
        if (!dialog.isShowing()) return;
        if (grants.length == 0) return;
        for (int grant : grants) {
            if (grant != 0) {
                showStatus("Нет доступа к Bluetooth");
                return;
            }
        }
        connect();
    }

    void close() {
        if (dialog != null) dialog.dismiss();
    }

    private void connect() {
        if (worker != null || CaptureService.recording) return;
        String entered = code.getText().toString().trim().toLowerCase(Locale.ROOT);
        String token = entered.isEmpty() ? settings.getString("token", "") : entered;
        if (!token.matches("[0-9a-f]{32}")) {
            code.setError("Введи код ESP из 32 символов");
            return;
        }
        String[] permissions = Build.VERSION.SDK_INT >= 31
                ? new String[]{"android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH_CONNECT"}
                : new String[]{"android.permission.ACCESS_FINE_LOCATION"};
        for (String permission : permissions) {
            if (activity.checkSelfPermission(permission) != 0) {
                activity.requestPermissions(permissions, BLUETOOTH_PERMISSION);
                return;
            }
        }
        Context app = activity.getApplicationContext();
        String cachedAddress = settings.getString("ble_address", "");
        setWorking(true);
        showStatus("Подключаюсь…");
        worker = new Thread(() -> {
            try {
                EspDeviceConnection device = EspDeviceConnection.bluetooth(app, cachedAddress, token);
                activity.runOnUiThread(() -> finish(token, device));
            } catch (InterruptedException stopped) {
                Thread.currentThread().interrupt();
            } catch (Exception error) {
                String message = error instanceof IOException && error.getMessage() != null
                        && error.getMessage().matches("^(?:[А-ЯЁ]|ESP).*") ? error.getMessage() : "Не удалось подключить ESP";
                activity.runOnUiThread(() -> {
                    if (!dialog.isShowing()) return;
                    worker = null;
                    setWorking(false);
                    showStatus(message);
                });
            }
        }, "Connect ESP");
        worker.start();
    }

    private void finish(String token, EspDeviceConnection device) {
        if (!dialog.isShowing()) return;
        worker = null;
        settings.edit().putString("token", token).putString("transport", "ble")
                .putString("esp_paired_transport", "ble").putString("ble_address", device.address).apply();
        onPaired.accept(device.battery);
        dialog.dismiss();
    }

    private void setWorking(boolean working) {
        connect.setEnabled(!working);
        code.setEnabled(!working);
    }

    private void showStatus(String value) {
        status.setText(value);
        status.setVisibility(View.VISIBLE);
    }

    private int dp(int value) {
        return Math.round(value * activity.getResources().getDisplayMetrics().density);
    }

    private LinearLayout.LayoutParams spaced() {
        LinearLayout.LayoutParams layout = new LinearLayout.LayoutParams(-1, -2);
        layout.topMargin = dp(8);
        return layout;
    }
}
