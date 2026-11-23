package ru.ilya.lecturerecorder;

import android.content.Context;
import android.os.SystemClock;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;

final class ClipMicProbe implements AutoCloseable {
    private final CompletableFuture<BleStream> result = new CompletableFuture<>();
    private final long deadline = SystemClock.elapsedRealtime() + 4000;
    private volatile BleStream priming;
    private boolean taken;

    ClipMicProbe(Context context, BooleanSupplier stopped) {
        new Thread(() -> {
            BleStream stream = null;
            try {
                stream = new BleStream(context, () -> stopped.getAsBoolean() || result.isDone(), deadline, true);
                priming = stream;
                if (!stopped.getAsBoolean() && !result.isDone()) {
                    stream.prime(deadline);
                    if (result.complete(stream)) stream = null;
                }
            } catch (Exception unavailable) {
                result.complete(null);
            } finally {
                if (stream != null) stream.close();
                priming = null;
                result.complete(null);
            }
        }, "ClipMic Bluetooth").start();
    }

    BleStream take() {
        if (taken) return null;
        BleStream stream = result.getNow(null);
        if (stream != null) taken = true;
        return stream;
    }

    BleStream await(BooleanSupplier stopped) throws InterruptedException {
        while (!result.isDone() && !stopped.getAsBoolean()) {
            long remaining = deadline - SystemClock.elapsedRealtime();
            if (remaining <= 0) break;
            try {
                result.get(Math.min(remaining, 80), TimeUnit.MILLISECONDS);
            } catch (java.util.concurrent.TimeoutException ignored) {
            } catch (java.util.concurrent.ExecutionException failed) {
                break;
            }
        }
        return take();
    }

    @Override public void close() {
        result.complete(null);
        BleStream stream = result.getNow(null);
        if (stream != null) stream.close();
        stream = priming;
        if (stream != null) stream.close();
    }
}
