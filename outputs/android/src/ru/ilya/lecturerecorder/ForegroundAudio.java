package ru.ilya.lecturerecorder;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.AudioAttributes;
import android.media.AudioFocusRequest;
import android.media.AudioManager;
import android.os.Build;

final class ForegroundAudio {
    static final AudioAttributes SPEECH = new AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_MEDIA)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build();

    private final Context context;
    private final AudioManager manager;
    private final AudioFocusRequest request;
    private final BroadcastReceiver route;
    private boolean held;

    ForegroundAudio(Context context, Runnable pause) {
        this.context = context;
        manager = context.getSystemService(AudioManager.class);
        request = new AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(SPEECH)
                .setWillPauseWhenDucked(true)
                .setOnAudioFocusChangeListener(change -> {
                    if (held && change < 0) pause.run();
                }).build();
        route = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                if (held && AudioManager.ACTION_AUDIO_BECOMING_NOISY.equals(intent.getAction())) pause.run();
            }
        };
    }

    boolean acquire() {
        if (held) return true;
        if (manager == null || manager.requestAudioFocus(request) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) return false;
        IntentFilter filter = new IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY);
        if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(route, filter, Context.RECEIVER_NOT_EXPORTED);
        else context.registerReceiver(route, filter);
        held = true;
        return true;
    }

    void release() {
        if (!held) return;
        held = false;
        context.unregisterReceiver(route);
        manager.abandonAudioFocusRequest(request);
    }
}
