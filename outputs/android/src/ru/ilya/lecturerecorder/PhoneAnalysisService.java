package ru.ilya.lecturerecorder;

import android.app.*;
import android.content.Context;
import android.content.Intent;
import android.net.ConnectivityManager;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import android.util.Log;
import com.google.ai.edge.litertlm.Conversation;
import org.json.JSONObject;

import java.io.IOException;
import java.io.InterruptedIOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.function.Consumer;

public final class PhoneAnalysisService extends Service {
    static final Object MODEL_WORK = new Object();
    private static final String CHANNEL = "phone-analysis";
    private static final int NOTIFICATION = 36;
    private static volatile Job active;
    static volatile String status = "";
    private static volatile String recording;
    private static volatile String failure = "";
    private static final String MISSING_SUMMARY = "Расшифровка сохранена. Для конспекта нужна модель (343 МБ).";
    private Job current;

    static boolean busy() {
        return active != null;
    }

    static boolean busyFor(String name) {
        return name.equals(recording) && busy();
    }

    static List<Phrase> previewFor(String name) {
        Job job = active;
        return job != null && name.equals(recording) ? job.preview : Collections.emptyList();
    }

    static String statusFor(String name) {
        return name.equals(recording) ? status : "";
    }

    static boolean networkAvailable(Context context) {
        ConnectivityManager networks = context.getSystemService(ConnectivityManager.class);
        return networks != null && networks.getActiveNetwork() != null;
    }

    static String summaryAction(Context context) {
        return PhoneModels.summaryReady(context) ? "Завершить конспект" : "Загрузить модель конспекта";
    }

    static String pendingSummaryMessage(Context context, String name) {
        if (busyFor(name)) return statusFor(name);
        if (name.equals(recording) && !failure.isEmpty()) return "Расшифровка сохранена. " + failure;
        return PhoneModels.summaryReady(context) ? "Расшифровка сохранена. Можно завершить конспект." : MISSING_SUMMARY;
    }

    static void request(Activity screen, String name, String title) {
        request(screen, name, title, false);
    }

    static void request(Activity screen, String name, String title, boolean retranscribe) {
        request(screen, name, title, retranscribe, false);
    }

    static void requestSummary(Activity screen, String name, String title) {
        request(screen, name, title, false, true);
    }

    private static void request(Activity screen, String name, String title, boolean retranscribe, boolean summaryOnly) {
        if (busy() || !LectureNotes.valid(name)) return;
        boolean online = networkAvailable(screen);
        boolean speechReady = PhoneModels.speechReady(screen) || (!online && PhoneModels.savedSpeechFallback(screen));
        boolean summaryReady = PhoneModels.summaryReady(screen);
        Runnable start = () -> screen.startForegroundService(new Intent(screen, PhoneAnalysisService.class)
                .setAction("analyze").putExtra("name", name).putExtra("title", title)
                .putExtra("retranscribe", retranscribe).putExtra("summaryOnly", summaryOnly).putExtra("allow_summary_download", online));
        boolean canStart = summaryOnly ? summaryReady : speechReady && (summaryReady || !online);
        if (canStart) {
            start.run();
            return;
        }
        if (!online) {
            String message = summaryOnly ? "Расшифровка сохранена. Подключись к интернету, чтобы один раз загрузить модель конспекта (343 МБ)."
                    : "Запись сохранена. Для первой расшифровки подключись к интернету и загрузи модель речи (225 МБ).";
            new AlertDialog.Builder(screen).setTitle("Нужен интернет для загрузки").setMessage(message).setPositiveButton("Понятно", null).show();
            return;
        }
        String download = summaryOnly || speechReady ? "Для конспекта нужна модель (343 МБ)."
                : summaryReady ? "Для расшифровки нужна модель речи (225 МБ)." : "Для речи и конспекта нужно скачать до 570 МБ.";
        new AlertDialog.Builder(screen).setTitle("Модели для разбора").setMessage(download + " После загрузки обработка работает без сети.")
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
        failure = "";
        job.allowSummaryDownload = intent.getBooleanExtra("allow_summary_download", true);
        current = job;
        active = job;
        PhraseReplay.cancelActive();
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Разбор лекций", NotificationManager.IMPORTANCE_LOW));
        status = "Подготавливаю разбор";
        startForeground(NOTIFICATION, notification(status));
        String title = intent.getStringExtra("title");
        boolean retranscribe = intent.getBooleanExtra("retranscribe", false);
        boolean summaryOnly = intent.getBooleanExtra("summaryOnly", false);
        new Thread(() -> process(job, name, title, retranscribe, summaryOnly), "Lecture analysis").start();
        return START_NOT_STICKY;
    }

    private void process(Job job, String name, String title, boolean retranscribe, boolean summaryOnly) {
        PowerManager.WakeLock wakeLock = getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "lectures:phone-analysis");
        wakeLock.acquire(2 * 60 * 60 * 1000L);
        try {
            boolean complete;
            synchronized (MODEL_WORK) {
                job.check();
                complete = PhoneLectureAnalysis.run(getApplicationContext(), job, name, title, retranscribe, summaryOnly);
            }
            status = complete ? (retranscribe ? "Расшифровка и конспект готовы" : "Конспект готов") : MISSING_SUMMARY;
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
            if (!job.cancelled) failure = status;
        } finally {
            job.clearPreview();
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

    static final class Phrase {
        final double start;
        final String text;

        Phrase(JSONObject phrase) {
            start = phrase.optDouble("start");
            text = phrase.optString("text");
        }
    }

    static final class Job {
        private final Consumer<String> report;
        private volatile List<Phrase> preview = Collections.emptyList();
        private volatile boolean cancelled;
        private boolean finalSaveStarted;
        boolean allowSummaryDownload = true;
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

        synchronized void publishPhrase(JSONObject phrase) {
            if (cancelled) return;
            List<Phrase> recent = new ArrayList<>(2);
            if (!preview.isEmpty()) recent.add(preview.get(preview.size() - 1));
            recent.add(new Phrase(phrase));
            preview = Collections.unmodifiableList(recent);
        }

        synchronized void clearPreview() {
            preview = Collections.emptyList();
        }

        synchronized void beginFinalSave() throws InterruptedIOException {
            check();
            finalSaveStarted = true;
        }

        void cancel() {
            synchronized (this) {
                if (finalSaveStarted) return;
                cancelled = true;
                clearPreview();
            }
            report.accept("Останавливаю разбор");
            Conversation current = conversation;
            if (current != null) {
                new Thread(() -> {
                    try {
                        current.cancelProcess();
                    } catch (RuntimeException ignored) {
                    }
                }, "Cancel lecture analysis").start();
            }
        }
    }
}
