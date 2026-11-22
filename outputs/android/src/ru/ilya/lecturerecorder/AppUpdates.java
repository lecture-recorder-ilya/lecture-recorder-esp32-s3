package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.*;
import android.content.pm.*;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import org.json.JSONObject;
import java.io.*;
import java.lang.ref.WeakReference;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

final class AppUpdates {
    private static final String INSTALL_PERMISSION = "Разреши установку из этого приложения, затем повтори.";
    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static volatile String message = "";
    private static volatile GitHubUpdateClient.DeviceCode pending;
    private static volatile Thread worker;

    static final class Failure extends IOException {
        Failure(String text) { super(text); }
    }

    static File apk(Context context) {
        return new File(new File(context.getFilesDir(), "updates"), "update.apk");
    }

    static boolean busy() { return worker != null; }
    static boolean authorizing() { return pending != null; }

    static boolean signedIn(Context context) {
        return new GitHubUpdateCredentials(context).exists();
    }

    static void signOut(Context context) {
        if (busy()) return;
        new GitHubUpdateCredentials(context).clear();
        message = "";
    }

    static String message(Context context, boolean available) {
        if (available && !busy()) {
            if (CaptureService.recording) return "Обновление готово. Установи его после записи.";
            if (PhoneAnalysisService.busy()) return "Обновление готово. Установи его после обработки аудио.";
            if (INSTALL_PERMISSION.equals(message) && context.getPackageManager().canRequestPackageInstalls())
                return "Обновление готово к установке.";
        }
        if (!message.isEmpty()) return message;
        if (available) return "Обновление готово к установке.";
        return signedIn(context) ? "Проверь, есть ли новая версия."
                : "Для обновлений войди в GitHub аккаунтом с доступом к проекту.";
    }

    static void check(Activity activity) {
        GitHubUpdateClient.DeviceCode code = pending;
        if (code != null) {
            showCode(activity, code);
            return;
        }
        if (busy()) return;
        Context context = activity.getApplicationContext();
        WeakReference<Activity> screen = new WeakReference<>(activity);
        begin("Проверяю обновления…", () -> downloadLatest(context, screen));
    }

    private static void downloadLatest(Context context, WeakReference<Activity> screen) throws Exception {
        GitHubUpdateClient client = new GitHubUpdateClient(context);
        GitHubUpdateCredentials credentials = new GitHubUpdateCredentials(context);
        String token;
        try {
            token = accessToken(client, credentials);
        } catch (GitHubUpdateClient.AuthorizationRequired expired) {
            credentials.clear();
            token = null;
        }
        if (token == null) {
            GitHubUpdateClient.DeviceCode request = client.startAuthorization();
            pending = request;
            message = "Подтверди вход на GitHub.";
            UI.post(() -> {
                Activity activity = screen.get();
                if (activity != null && pending == request) showCode(activity, request);
            });
            JSONObject response = client.awaitAuthorization(request);
            credentials.save(response);
            pending = null;
            token = response.getString("access_token");
        }

        PackageInfo current = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
        String name = context.getPackageName().endsWith(".preview")
                ? "lecture-recorder-android.apk" : "lecture-recorder.apk";
        message = "Проверяю обновления…";
        GitHubUpdateClient.Asset asset;
        try {
            asset = client.latest(token, current.versionName, name);
        } catch (GitHubUpdateClient.AuthorizationRequired expired) {
            credentials.clear();
            throw expired;
        }
        if (asset == null) {
            message = "Для этой сборки новых версий нет.";
            return;
        }

        File target = apk(context);
        File directory = target.getParentFile();
        if (!directory.isDirectory() && !directory.mkdirs())
            throw new Failure("Не удалось открыть папку обновлений.");
        if (ready(context) && asset.sha256.equals(settings(context).getString("sha256", "")) &&
                asset.sha256.equals(Store.hash(target))) {
            message = "Версия " + asset.version + " готова к установке.";
            return;
        }
        if (directory.getUsableSpace() < asset.bytes + 32 * 1024 * 1024)
            throw new Failure("На телефоне мало места для обновления.");

        // Use the same temporary path on retries so an interrupted download cannot accumulate copies.
        File part = new File(directory, "update.pending.apk");
        try {
            client.download(token, asset, part, percent -> message = "Скачиваю версию " + asset.version + " · " + percent + "%");
            int code = verify(context, part);
            Files.move(part.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            if (!settings(context).edit().putString("sha256", asset.sha256).putInt("code", code).commit())
                throw new Failure("Не удалось сохранить сведения об обновлении.");
            message = "Версия " + asset.version + " готова к установке.";
        } finally {
            part.delete();
        }
    }

    private static String accessToken(GitHubUpdateClient client, GitHubUpdateCredentials credentials) throws Exception {
        JSONObject existing = credentials.read();
        if (existing == null) return null;
        long now = System.currentTimeMillis();
        if (now + 120000 < existing.getLong("expires_at")) return existing.getString("access_token");
        if (now >= existing.optLong("refresh_expires_at")) return null;
        JSONObject response = client.refresh(existing.getString("refresh_token"));
        credentials.save(response);
        return response.getString("access_token");
    }

    private static void showCode(Activity activity, GitHubUpdateClient.DeviceCode code) {
        if (code == null || activity.isFinishing() || activity.isDestroyed()) return;
        new AlertDialog.Builder(activity).setTitle("Вход в GitHub")
                .setMessage("Введи этот код на GitHub и подтверди доступ к обновлениям.\n\n" + code.userCode)
                .setPositiveButton("Открыть GitHub", (dialog, which) -> {
                    if (pending != code) return;
                    try {
                        activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(GitHubUpdateClient.DEVICE_URL)));
                    } catch (ActivityNotFoundException error) {
                        message = "Открой github.com/login/device в браузере и введи показанный код.";
                    }
                }).setNeutralButton("Копировать код", (dialog, which) -> {
                    if (pending == code) activity.getSystemService(ClipboardManager.class)
                            .setPrimaryClip(ClipData.newPlainText("Код входа GitHub", code.userCode));
                }).setNegativeButton("Отменить вход", (dialog, which) -> {
                    Thread active = worker;
                    if (pending == code && active != null) active.interrupt();
                }).show();
    }

    private interface Operation { void run() throws Exception; }

    private static synchronized void begin(String initial, Operation operation) {
        if (worker != null) return;
        message = initial;
        worker = new Thread(() -> {
            try {
                operation.run();
            } catch (InterruptedException cancelled) {
                message = "Вход в GitHub отменён.";
            } catch (Failure | GitHubUpdateClient.AuthorizationRequired error) {
                message = error.getMessage();
            } catch (Exception error) {
                message = "Не удалось завершить обновление. Проверь интернет и повтори.";
            } finally {
                pending = null;
                worker = null;
            }
        }, "Android updates");
        worker.start();
    }

    private static SharedPreferences settings(Context context) {
        return context.getSharedPreferences("updates", Context.MODE_PRIVATE);
    }

    private static Set<Signature> signatures(PackageInfo info) throws Failure {
        Signature[] signers = Build.VERSION.SDK_INT >= 28
                ? (info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners()) : info.signatures;
        if (signers == null || signers.length == 0) throw new Failure("У APK нет подписи.");
        return new HashSet<>(Arrays.asList(signers));
    }

    static int verify(Context context, File file) throws Exception {
        PackageManager manager = context.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo current = manager.getPackageInfo(context.getPackageName(), flags);
        PackageInfo next = manager.getPackageArchiveInfo(file.getPath(), flags);
        if (next == null || !current.packageName.equals(next.packageName) || next.versionCode <= current.versionCode)
            throw new Failure("APK не подходит для обновления установленной версии.");
        if (!signatures(current).equals(signatures(next)))
            throw new Failure("Подпись обновления отличается от подписи приложения.");
        return next.versionCode;
    }

    static boolean ready(Context context) {
        if (!apk(context).isFile() || !settings(context).contains("sha256")) return false;
        try {
            int installed = context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionCode;
            if (settings(context).getInt("code", 0) > installed) return true;
            if (!busy() && apk(context).delete()) settings(context).edit().remove("code").remove("sha256").apply();
            return false;
        } catch (PackageManager.NameNotFoundException error) {
            return false;
        }
    }

    static void install(Activity activity) {
        if (busy() || CaptureService.recording || PhoneAnalysisService.busy()) return;
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            if (open(activity, new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + activity.getPackageName())))) message = INSTALL_PERMISSION;
            return;
        }
        Context context = activity.getApplicationContext();
        WeakReference<Activity> screen = new WeakReference<>(activity);
        begin("Проверяю APK…", () -> {
            File file = apk(context);
            if (!ready(context) || !Store.hash(file).equals(settings(context).getString("sha256", "")))
                throw new Failure("APK изменился. Проверь обновления ещё раз.");
            verify(context, file);
            UI.post(() -> {
                Activity owner = screen.get();
                if (owner == null || owner.isFinishing() || owner.isDestroyed()
                        || CaptureService.recording || PhoneAnalysisService.busy()) return;
                Uri uri = Uri.parse("content://" + owner.getPackageName() + ".updates/update.apk");
                open(owner, new Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION));
            });
            message = "Обновление готово к установке.";
        });
    }

    private static boolean open(Activity activity, Intent intent) {
        try {
            activity.startActivity(intent);
            return true;
        } catch (ActivityNotFoundException | SecurityException unavailable) {
            message = "Не удалось открыть установку обновления.";
            return false;
        }
    }
}
