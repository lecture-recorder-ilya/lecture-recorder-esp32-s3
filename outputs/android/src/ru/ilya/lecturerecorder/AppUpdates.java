package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import org.json.JSONObject;
import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.HashSet;
import java.util.Set;

final class AppUpdates {
    private static final String INSTALL_PERMISSION = "Разреши установку из этого приложения, затем повтори.";
    private static volatile String installMessage = "";
    private static volatile boolean checkingInstall;

    private static SharedPreferences settings(Context context) {
        return context.getSharedPreferences("updates", 0);
    }

    static File apk(Context context) {
        String selected = settings(context).getString("selected", "update.apk");
        return new File(new File(context.getFilesDir(), "updates"), selected);
    }

    static boolean active() {
        return CaptureService.recording || PhoneAnalysisService.busy();
    }

    static String message(Context context, boolean available) {
        SharedPreferences prefs = settings(context);
        if (available) {
            if (CaptureService.recording) return "Обновление готово. Установи его после записи.";
            if (PhoneAnalysisService.busy()) return "Обновление готово. Установи его после разбора.";
            if (checkingInstall) return "Проверяю подпись APK…";
            String issue = installMessage;
            if (!issue.isEmpty() && (!INSTALL_PERMISSION.equals(issue) || !context.getPackageManager().canRequestPackageInstalls())) return issue;
            return "github".equals(prefs.getString("source", "mac"))
                    ? "Обновление получено с GitHub и готово к установке."
                    : "Обновление получено с Mac и готово к установке.";
        }
        if (prefs.contains("rejected_digest")) return prefs.getString("rejected_message", "Телефон отклонил обновление.");
        return CaptureService.paired(context) ? "Жду обновление от Mac. Оно появится здесь автоматически."
                : "Обновления доступны через GitHub или сопряжённый Mac.";
    }

    static synchronized JSONObject info(Context context) throws Exception {
        SharedPreferences prefs = settings(context);
        PackageInfo installed = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
        boolean available = ready(context);
        return new JSONObject().put("installed_package", context.getPackageName())
                .put("installed_tag", "v" + installed.versionName).put("installed_code", installed.versionCode)
                .put("sha256", available ? prefs.getString("sha256", "") : "")
                .put("pending_code", available ? prefs.getInt("code", 0) : 0)
                .put("recording", CaptureService.recording).put("analyzing", PhoneAnalysisService.busy())
                .put("rejected_digest", prefs.getString("rejected_digest", "")).put("message", message(context, available));
    }

    static int receive(Context context, File temp, String sha) throws Exception {
        return stage(context, temp, sha, "mac");
    }

    static synchronized int stage(Context context, File temp, String sha, String source) throws Exception {
        if (active()) throw new IOException("Обновление будет передано после записи или разбора");
        if (!sha.matches("[a-f0-9]{64}")) throw new IOException("Неверная контрольная сумма APK");
        SharedPreferences prefs = settings(context);
        int code;
        try {
            code = verify(context, temp);
        } catch (Exception invalid) {
            prefs.edit().putString("rejected_digest", sha).putString("rejected_message", invalid.getMessage()).commit();
            throw invalid;
        }
        File old = apk(context);
        if (ready(context)) {
            int pending = prefs.getInt("code", 0);
            if (code < pending || (code == pending && !sha.equals(prefs.getString("sha256", "")))) {
                throw new IOException("На телефоне уже готово такое же или более новое обновление");
            }
        }
        File folder = old.getParentFile();
        if (!folder.isDirectory() && !folder.mkdirs()) throw new IOException("Не удалось открыть папку обновлений");
        File next = new File(folder, sha + ".apk");
        Files.move(temp.toPath(), next.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        if (!prefs.edit().putString("selected", next.getName()).putString("source", source)
                .putString("sha256", sha).putInt("code", code)
                .remove("rejected_digest").remove("rejected_message").commit()) {
            throw new IOException("Не удалось сохранить сведения об APK");
        }
        if (!old.equals(next)) old.delete();
        installMessage = "";
        return code;
    }

    private static Set<String> signatures(PackageInfo info) throws Exception {
        Signature[] values = Build.VERSION.SDK_INT >= 28
                ? (info.signingInfo == null ? null : info.signingInfo.getApkContentsSigners()) : info.signatures;
        if (values == null || values.length == 0) throw new IOException("Нет подписи APK");
        Set<String> result = new HashSet<>();
        for (Signature value : values) result.add(SyncServer.hash(value.toByteArray()));
        return result;
    }

    static int verify(Context context, File file) throws Exception {
        PackageManager manager = context.getPackageManager();
        int flags = Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES;
        PackageInfo current = manager.getPackageInfo(context.getPackageName(), flags);
        PackageInfo next = manager.getPackageArchiveInfo(file.getPath(), flags);
        if (next == null || !current.packageName.equals(next.packageName) || next.versionCode <= current.versionCode)
            throw new IOException("APK не является новой версией этого приложения");
        if (!signatures(current).equals(signatures(next))) throw new IOException("Подпись обновления отличается от подписи приложения");
        return next.versionCode;
    }

    static synchronized boolean ready(Context context) {
        SharedPreferences prefs = settings(context);
        if (!prefs.contains("sha256")) return false;
        File file = apk(context);
        try {
            if (file.isFile() && prefs.getInt("code", 0) > context.getPackageManager().getPackageInfo(context.getPackageName(), 0).versionCode)
                return true;
            file.delete();
            prefs.edit().remove("sha256").remove("code").remove("selected").remove("source").apply();
        } catch (Exception unavailable) {
            return false;
        }
        return false;
    }

    static synchronized void install(Activity activity) {
        if (checkingInstall || active() || !ready(activity)) return;
        installMessage = "";
        if (!activity.getPackageManager().canRequestPackageInstalls()) {
            try {
                activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + activity.getPackageName())));
                installMessage = INSTALL_PERMISSION;
            } catch (RuntimeException unavailable) {
                installMessage = "Не удалось открыть разрешение на установку.";
            }
            return;
        }
        File file = apk(activity);
        String expected = settings(activity).getString("sha256", "");
        checkingInstall = true;
        new Thread(() -> {
            try {
                if (!Store.hash(file).equals(expected)) throw new IOException("APK изменился. Проверь обновления ещё раз.");
                verify(activity, file);
                activity.runOnUiThread(() -> {
                    if (active() || activity.isFinishing() || activity.isDestroyed() || !file.equals(apk(activity))) return;
                    try {
                        Intent intent = new Intent(Intent.ACTION_VIEW);
                        intent.setDataAndType(Uri.parse("content://" + activity.getPackageName() + ".updates/update.apk"),
                                "application/vnd.android.package-archive");
                        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                        activity.startActivity(intent);
                    } catch (RuntimeException unavailable) {
                        installMessage = "Не удалось открыть установку обновления.";
                    }
                });
            } catch (Exception error) {
                installMessage = error.getMessage() == null ? "Не удалось проверить обновление." : error.getMessage();
            } finally {
                checkingInstall = false;
            }
        }, "APK verification").start();
    }
}
