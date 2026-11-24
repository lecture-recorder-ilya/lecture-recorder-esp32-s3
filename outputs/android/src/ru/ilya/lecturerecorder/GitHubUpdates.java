package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.lang.ref.WeakReference;
import java.util.concurrent.TimeUnit;

final class GitHubUpdates {
    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static final long INTERVAL = TimeUnit.HOURS.toMillis(6);
    private static final long RETRY = TimeUnit.MINUTES.toMillis(15);
    private static long nextTick;
    private static volatile String status = "";
    private static volatile GitHubUpdateClient.DeviceCode pending;
    private static volatile Thread worker;

    static final class Failure extends IOException {
        Failure(String message) { super(message); }
    }

    static boolean signedIn(Context context) { return new GitHubUpdateCredentials(context).exists(); }
    static boolean busy() { return worker != null; }
    static boolean authorizing() { return pending != null; }
    static String status() { return status; }

    static synchronized void disconnect(Context context) {
        if (busy()) return;
        new GitHubUpdateCredentials(context).clear();
        context.getSharedPreferences("updates", 0).edit().remove("github_after").apply();
        status = "";
        nextTick = 0;
    }

    static void whenOpen(Activity activity) {
        long elapsed = SystemClock.elapsedRealtime();
        if (elapsed < nextTick || busy()) return;
        nextTick = elapsed + TimeUnit.SECONDS.toMillis(30);
        if (AppUpdates.active()) return;
        long now = System.currentTimeMillis();
        long after = activity.getSharedPreferences("updates", 0).getLong("github_after", 0);
        if (after > now && after - now <= INTERVAL) return;
        start(activity, false);
    }

    static synchronized void start(Activity activity, boolean interactive) {
        if (pending != null && interactive) {
            showCode(activity, pending);
            return;
        }
        if (busy() || AppUpdates.active()) return;
        Context context = activity.getApplicationContext();
        ConnectivityManager network = context.getSystemService(ConnectivityManager.class);
        Network current = network == null ? null : network.getActiveNetwork();
        NetworkCapabilities capabilities = current == null ? null : network.getNetworkCapabilities(current);
        if (capabilities == null || !capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)) {
            if (interactive) status = "Телефон без интернета. Запись и разбор доступны офлайн.";
            return;
        }
        WeakReference<Activity> screen = new WeakReference<>(activity);
        status = "Проверяю GitHub…";
        worker = new Thread(() -> {
            SharedPreferences settings = context.getSharedPreferences("updates", 0);
            long delay = RETRY;
            try {
                check(context, screen, interactive);
                delay = INTERVAL;
            } catch (InterruptedException cancelled) {
                status = "Вход в GitHub отменён.";
            } catch (GitHubUpdateClient.AuthorizationRequired privateChannel) {
                delay = INTERVAL;
                status = interactive ? privateChannel.getMessage() : "Для закрытого канала нужен вход в GitHub.";
            } catch (Failure | GitHubUpdateClient.PublicLimit error) {
                status = error.getMessage();
            } catch (Exception failed) {
                status = "Не удалось проверить GitHub. Проверь интернет и повтори.";
            } finally {
                settings.edit().putLong("github_after", System.currentTimeMillis() + delay).apply();
                pending = null;
                worker = null;
            }
        }, "GitHub releases");
        worker.start();
    }

    private static String accessToken(GitHubUpdateClient client, GitHubUpdateCredentials credentials) throws Exception {
        JSONObject saved = credentials.read();
        if (saved == null) return null;
        long now = System.currentTimeMillis();
        if (now + 120000 < saved.getLong("expires_at")) return saved.getString("access_token");
        if (now >= saved.optLong("refresh_expires_at")) return null;
        JSONObject response = client.refresh(saved.getString("refresh_token"));
        credentials.save(response);
        return response.getString("access_token");
    }

    private static void check(Context context, WeakReference<Activity> screen, boolean interactive) throws Exception {
        GitHubUpdateClient client = new GitHubUpdateClient(context);
        GitHubUpdateCredentials credentials = new GitHubUpdateCredentials(context);
        try {
            checkRelease(context, client, null);
        } catch (GitHubUpdateClient.PublicLimit limited) {
            if (!checkSaved(context, client, credentials)) throw limited;
        } catch (GitHubUpdateClient.AuthorizationRequired privateChannel) {
            if (checkSaved(context, client, credentials)) return;
            if (!interactive) throw privateChannel;
            GitHubUpdateClient.DeviceCode code = client.startAuthorization();
            pending = code;
            status = "Подтверди вход в GitHub.";
            UI.post(() -> {
                Activity activity = screen.get();
                if (activity != null && pending == code) showCode(activity, code);
            });
            JSONObject response = client.awaitAuthorization(code);
            credentials.save(response);
            pending = null;
            try {
                checkRelease(context, client, response.getString("access_token"));
            } catch (GitHubUpdateClient.AuthorizationRequired rejected) {
                credentials.clear();
                throw rejected;
            }
        }
    }

    private static boolean checkSaved(Context context, GitHubUpdateClient client, GitHubUpdateCredentials credentials) throws Exception {
        if (!credentials.exists()) return false;
        try {
            String saved = accessToken(client, credentials);
            if (saved != null) {
                checkRelease(context, client, saved);
                return true;
            }
        } catch (GitHubUpdateClient.AuthorizationRequired expired) {
            credentials.clear();
            return false;
        }
        credentials.clear();
        return false;
    }

    private static void checkRelease(Context context, GitHubUpdateClient client, String token) throws Exception {
        String packageName = context.getPackageName();
        String current = context.getPackageManager().getPackageInfo(packageName, 0).versionName;
        String name = packageName.endsWith(".preview") ? "lecture-recorder-android.apk" : "lecture-recorder.apk";
        status = "Проверяю GitHub…";
        GitHubUpdateClient.Asset asset = client.latest(token, current, name);
        if (asset == null) {
            status = "Установлена последняя версия с GitHub.";
            return;
        }
        SharedPreferences settings = context.getSharedPreferences("updates", 0);
        if (AppUpdates.ready(context) && asset.sha256.equals(settings.getString("sha256", ""))
                && asset.sha256.equals(Store.hash(AppUpdates.apk(context)))) {
            status = "Обновление уже на телефоне.";
            return;
        }
        File directory = AppUpdates.apk(context).getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs()) throw new Failure("Не удалось открыть папку обновлений.");
        if (directory.getUsableSpace() < asset.bytes + 32 * 1024 * 1024) throw new Failure("На телефоне мало места для обновления.");
        File part = new File(directory, "github.pending.apk");
        try {
            client.download(token, asset, part, percent -> {
                if (AppUpdates.active()) throw new Failure("Проверка обновления продолжится после записи или разбора.");
                status = "Скачиваю " + asset.version + " · " + percent + "%";
            });
            try {
                AppUpdates.stage(context, part, asset.sha256, "github");
            } catch (IOException rejected) {
                throw new Failure(rejected.getMessage());
            }
            status = "Обновление готово к установке.";
        } finally {
            part.delete();
        }
    }

    private static void showCode(Activity activity, GitHubUpdateClient.DeviceCode code) {
        if (activity.isFinishing() || activity.isDestroyed()) return;
        new AlertDialog.Builder(activity).setTitle("Вход в GitHub")
                .setMessage("Введи код на GitHub, чтобы получать закрытые обновления.\n\n" + code.userCode)
                .setPositiveButton("Открыть GitHub", (dialog, which) -> {
                    if (pending != code) return;
                    try {
                        activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(GitHubUpdateClient.DEVICE_URL)));
                    } catch (ActivityNotFoundException unavailable) {
                        status = "Открой github.com/login/device в браузере и введи код.";
                    }
                }).setNeutralButton("Копировать код", (dialog, which) -> {
                    if (pending == code) activity.getSystemService(ClipboardManager.class)
                            .setPrimaryClip(ClipData.newPlainText("Код входа GitHub", code.userCode));
                }).setNegativeButton("Отменить вход", (dialog, which) -> {
                    Thread task = worker;
                    if (pending == code && task != null) task.interrupt();
                }).show();
    }
}
