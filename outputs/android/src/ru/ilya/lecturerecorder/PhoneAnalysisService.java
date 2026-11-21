package ru.ilya.lecturerecorder;

import android.app.*;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import com.google.ai.edge.litertlm.Conversation;

import java.io.IOException;
import java.io.InterruptedIOException;
import java.util.function.Consumer;

public final class PhoneAnalysisService extends Service {
    private static final String CHANNEL = "phone-analysis";
    private static final int NOTIFICATION = 36;
    private static volatile Job active;
    static volatile String status = "";
    private static volatile String recording;
    private Job current;

    static boolean busy() {
        return active != null;
    }

    static boolean busyFor(String name) {
        return name.equals(recording) && busy();
    }

    static String statusFor(String name) {
        return name.equals(recording) ? status : "";
    }

    static void request(Activity screen, String name, String title) {
        request(screen, name, title, false);
    }

    static void request(Activity screen, String name, String title, boolean retranscribe) {
        if (busy() || !LectureNotes.valid(name)) return;
        Runnable start = () -> screen.startForegroundService(new Intent(screen, PhoneAnalysisService.class)
                .setAction("analyze").putExtra("name", name).putExtra("title", title)
                .putExtra("retranscribe", retranscribe));
        if (PhoneModels.ready(screen)) start.run();
        else new AlertDialog.Builder(screen).setTitle("Модели для разбора")
                .setMessage("Первый запуск скачает до 570 МБ. После этого разбор работает офлайн.")
                .setPositiveButton("Скачать и разобрать", (dialog, which) -> start.run())
                .setNegativeButton("Отмена", null).show();
    }

    static Intent cancel(Context context) {
        return new Intent(context, PhoneAnalysisService.class).setAction("cancel");
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent == null) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        if ("cancel".equals(intent.getAction())) {
            Job job = active;
            if (job != null) job.cancel();
            else stopSelf(startId);
            return START_NOT_STICKY;
        }
        if (active != null) return START_NOT_STICKY;
        String name = intent.getStringExtra("name");
        if (!LectureNotes.valid(name)) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        Job job = new Job(value -> {
            status = value;
            getSystemService(NotificationManager.class).notify(NOTIFICATION, notification(value));
        });
        recording = name;
        current = job;
        active = job;
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Разбор лекций", NotificationManager.IMPORTANCE_LOW));
        status = "Подготавливаю разбор";
        startForeground(NOTIFICATION, notification(status));
        String title = intent.getStringExtra("title");
        boolean retranscribe = intent.getBooleanExtra("retranscribe", false);
        new Thread(() -> process(job, name, title, retranscribe), "Lecture analysis").start();
        return START_NOT_STICKY;
    }

    private void process(Job job, String name, String title, boolean retranscribe) {
        PowerManager.WakeLock wakeLock = getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "lectures:phone-analysis");
        wakeLock.acquire(2 * 60 * 60 * 1000L);
        try {
            PhoneLectureAnalysis.run(getApplicationContext(), job, name, title, retranscribe);
            status = retranscribe ? "Расшифровка готова" : "Разбор готов";
        } catch (Exception | LinkageError error) {
            if (job.cancelled) {
                status = "Разбор отменён";
            } else if (error instanceof IOException && error.getMessage() != null
                    && error.getMessage().matches("^[А-ЯЁ].*")) {
                status = error.getMessage();
            } else {
                status = "Не удалось завершить разбор. Можно повторить";
                Log.e("LectureAnalysis", "Local analysis failed", error);
            }
        } finally {
            if (wakeLock.isHeld()) wakeLock.release();
            new Handler(Looper.getMainLooper()).post(() -> {
                if (active != job) return;
                stopForeground(STOP_FOREGROUND_REMOVE);
                active = null;
                stopSelf();
            });
        }
    }

    private Notification notification(String progress) {
        PendingIntent open = PendingIntent.getActivity(this, 36, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        PendingIntent cancel = PendingIntent.getService(this, 36, cancel(this), PendingIntent.FLAG_IMMUTABLE);
        return new Notification.Builder(this, CHANNEL)
                .setSmallIcon(R.drawable.icon).setContentTitle("Разбор лекции").setContentText(progress)
                .setContentIntent(open).setOnlyAlertOnce(true).setOngoing(true)
                .addAction(new Notification.Action.Builder(null, "Отменить", cancel).build()).build();
    }

    @Override public void onDestroy() {
        if (current != null && current == active) current.cancel();
        super.onDestroy();
    }

    static final class Job {
        private final Consumer<String> report;
        private volatile boolean cancelled;
        volatile Conversation conversation;

        Job(Consumer<String> report) {
            this.report = report;
        }

        void check() throws InterruptedIOException {
            if (cancelled) throw new InterruptedIOException();
        }

        void update(String value) {
            if (!cancelled) report.accept(value);
        }

        void cancel() {
            cancelled = true;
            report.accept("Останавливаю разбор");
            Conversation current = conversation;
            if (current != null) {
                new Thread(() -> {
                    try {
                        current.cancelProcess();
                    } catch (RuntimeException ignored) {
                        // The generation may have already ended.
                    }
                }, "Cancel lecture analysis").start();
            }
        }
    }
}
