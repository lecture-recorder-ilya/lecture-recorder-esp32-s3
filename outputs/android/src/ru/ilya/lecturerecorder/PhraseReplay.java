package ru.ilya.lecturerecorder;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import ai.onnxruntime.OrtSession;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.util.function.Consumer;

final class PhraseReplay {
    static final class Result {
        final String message;
        final int startMillis, endMillis;
        Result(String message, int startMillis, int endMillis) {
            this.message = message;
            this.startMillis = startMillis;
            this.endMillis = endMillis;
        }
    }

    private static PhraseReplay active;
    private final PhoneAnalysisService.Job job = new PhoneAnalysisService.Job(ignored -> {});
    private boolean cancelled;
    private OrtSession.RunOptions running;

    static synchronized PhraseReplay start(Context context, String name, double from, double to, double anchor,
                                          Consumer<Result> callback) throws IOException {
        if (active != null || PhoneAnalysisService.busy()) throw new IOException("Дождись завершения текущего разбора");
        if (CaptureService.recording) throw new IOException("Сначала заверши запись");
        if (!android.os.Process.is64Bit()) throw new IOException("Для этой модели нужен 64-битный Android");
        Context app = context.getApplicationContext();
        PhraseReplay replay = new PhraseReplay();
        active = replay;
        new Thread(() -> replay.process(app, name, from, to, anchor, callback), "Повтор фрагмента").start();
        return replay;
    }

    static synchronized void cancelActive() {
        if (active != null) active.cancel();
    }

    synchronized void cancel() {
        cancelled = true;
        job.cancel();
        if (running != null) {
            try { running.setTerminate(true); } catch (Exception ignored) {}
        }
    }

    private void process(Context context, String name, double from, double to, double anchor, Consumer<Result> callback) {
        String message;
        int begin = -1, end = -1;
        try {
            synchronized (PhoneAnalysisService.MODEL_WORK) {
                job.check();
                try (RandomAccessFile audio = Store.openAudio(context, name)) {
                    long total = PcmWave.seekData(audio) / 2;
                    long data = audio.getFilePointer();
                    PhraseReplayAudio.Window section = PhraseReplayAudio.window(total, from, to, anchor);
                    begin = (int)(section.start * 1000 / PcmWave.SAMPLE_RATE);
                    end = (int)((section.end * 1000 + PcmWave.SAMPLE_RATE - 1) / PcmWave.SAMPLE_RATE);
                    File model = PhoneModels.offlineAcoustic(context, job);
                    job.check();
                    try (OrtSession.RunOptions options = new OrtSession.RunOptions()) {
                        synchronized (this) { job.check(); running = options; }
                        try {
                            String text = PhraseReplayAudio.decode(context, audio, data, section, model, options, job);
                            message = text.isEmpty() ? "Не удалось разобрать слова" : text;
                        } finally {
                            synchronized (this) { running = null; }
                        }
                    }
                }
            }
        } catch (Exception | LinkageError error) {
            message = error instanceof IOException && error.getMessage() != null ? error.getMessage() : "Не удалось повторить разбор на телефоне";
        } finally {
            synchronized (PhraseReplay.class) { if (active == this) active = null; }
        }
        Result result = new Result(message, begin, end);
        new Handler(Looper.getMainLooper()).post(() -> {
            synchronized (this) {
                if (cancelled) { callback.accept(new Result("Повтор отменён", -1, -1)); return; }
            }
            callback.accept(result);
        });
    }
}
