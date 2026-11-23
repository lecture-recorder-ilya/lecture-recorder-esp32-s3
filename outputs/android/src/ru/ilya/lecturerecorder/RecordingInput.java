package ru.ilya.lecturerecorder;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.content.Context;
import android.media.AudioDeviceInfo;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;

final class RecordingInput implements AutoCloseable {
    private final Context context;
    private final AudioManager manager;
    private AudioDeviceInfo wired;
    private boolean modeRequested;
    private boolean communicationSelected;
    private boolean scoStarted;
    private boolean scoRoutingChanged;

    RecordingInput(Context context) {
        this.context = context;
        manager = context.getSystemService(AudioManager.class);
        if (manager == null) return;
        try {
            boolean headsetInput = false;
            for (AudioDeviceInfo input : manager.getDevices(AudioManager.GET_DEVICES_INPUTS)) {
                if (!input.isSource()) continue;
                if (wiredInput(input.getType())) {
                    wired = input;
                    return;
                }
                headsetInput |= bluetoothInput(input.getType());
            }
            if (manager.getMode() != AudioManager.MODE_NORMAL) return;
            if (Build.VERSION.SDK_INT >= 31) {
                AudioDeviceInfo selected = manager.getCommunicationDevice();
                if (selected == null || !bluetoothInput(selected.getType())) {
                    selected = null;
                    for (AudioDeviceInfo device : manager.getAvailableCommunicationDevices()) {
                        if (bluetoothInput(device.getType())) {
                            selected = device;
                            break;
                        }
                    }
                }
                if (selected == null) return;
                setCommunicationMode();
                communicationSelected = manager.setCommunicationDevice(selected);
                if (!communicationSelected) close();
            } else if (manager.isBluetoothScoAvailableOffCall() && (headsetInput || legacyHeadsetConnected())) {
                setCommunicationMode();
                manager.startBluetoothSco();
                scoStarted = true;
                if (!manager.isBluetoothScoOn()) {
                    manager.setBluetoothScoOn(true);
                    scoRoutingChanged = true;
                }
            }
        } catch (RuntimeException error) {
            close();
        }
    }

    private boolean legacyHeadsetConnected() {
        BluetoothManager bluetooth = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = bluetooth == null ? null : bluetooth.getAdapter();
        return adapter != null && adapter.isEnabled()
                && adapter.getProfileConnectionState(BluetoothProfile.HEADSET) == BluetoothProfile.STATE_CONNECTED;
    }

    private void setCommunicationMode() {
        manager.setMode(AudioManager.MODE_IN_COMMUNICATION);
        modeRequested = true;
    }

    private static boolean wiredInput(int type) {
        return type == AudioDeviceInfo.TYPE_WIRED_HEADSET || type == AudioDeviceInfo.TYPE_USB_HEADSET
                || type == AudioDeviceInfo.TYPE_USB_DEVICE || type == AudioDeviceInfo.TYPE_USB_ACCESSORY;
    }

    private static boolean bluetoothInput(int type) {
        return type == AudioDeviceInfo.TYPE_BLUETOOTH_SCO || type == AudioDeviceInfo.TYPE_BLE_HEADSET;
    }

    int audioSource() {
        return communicationSelected || scoStarted ? MediaRecorder.AudioSource.VOICE_COMMUNICATION : MediaRecorder.AudioSource.MIC;
    }

    void prefer(AudioRecord recorder) {
        if (wired != null) {
            try { recorder.setPreferredDevice(wired); } catch (RuntimeException ignored) {}
        }
    }

    static String actualLabel(AudioRecord recorder) {
        AudioDeviceInfo input = recorder.getRoutedDevice();
        if (input == null || !input.isSource()) return "Микрофон · источник уточняется";
        int type = input.getType();
        if (type == AudioDeviceInfo.TYPE_BUILTIN_MIC) return "Микрофон телефона";
        if (bluetoothInput(type)) return "Bluetooth-гарнитура";
        if (type == AudioDeviceInfo.TYPE_WIRED_HEADSET) return "Проводная гарнитура";
        if (wiredInput(type)) return "Микрофон USB";
        return "Системный аудиовход";
    }

    @Override public void close() {
        if (manager == null) return;
        if (Build.VERSION.SDK_INT >= 31 && communicationSelected) {
            try { manager.clearCommunicationDevice(); } catch (RuntimeException ignored) {}
        }
        if (scoRoutingChanged) {
            try { manager.setBluetoothScoOn(false); } catch (RuntimeException ignored) {}
        }
        if (scoStarted) {
            try { manager.stopBluetoothSco(); } catch (RuntimeException ignored) {}
        }
        if (modeRequested) {
            try { manager.setMode(AudioManager.MODE_NORMAL); } catch (RuntimeException ignored) {}
        }
        communicationSelected = scoStarted = scoRoutingChanged = modeRequested = false;
    }
}
