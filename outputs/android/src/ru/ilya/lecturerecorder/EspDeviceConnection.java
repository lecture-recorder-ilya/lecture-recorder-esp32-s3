package ru.ilya.lecturerecorder;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.BluetoothStatusCodes;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Build;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class EspDeviceConnection {
    static final String PAIRING_MODE = "esp_pairing_mode";
    static final String BONDED = "bonded";
    private static final UUID BATTERY_SERVICE = UUID.fromString("0000180f-0000-1000-8000-00805f9b34fb");
    private static final UUID BATTERY_LEVEL = UUID.fromString("00002a19-0000-1000-8000-00805f9b34fb");

    private static final Pattern REPORTED_BATTERY = Pattern.compile("(?:^| )battery=([0-9]{1,3})(?: |$)");

    final String address;
    final int battery;

    private EspDeviceConnection(String address, int battery) {
        this.address = address;
        this.battery = battery;
    }

    static EspDeviceConnection bluetooth(Context context, String cachedAddress) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Включи Bluetooth");
        BluetoothDevice device = BluetoothAdapter.checkBluetoothAddress(cachedAddress)
                ? adapter.getRemoteDevice(cachedAddress) : EspFirmwareVersion.findBluetooth(adapter, "", true);
        CompletableFuture<BluetoothGattCharacteristic> discovered = new CompletableFuture<>();
        CompletableFuture<EspDeviceConnection> result = new CompletableFuture<>();
        BluetoothGatt gatt = device.connectGatt(context, false, new BluetoothGattCallback() {
            private boolean authorized;

            private void fail(String message) {
                IOException error = new IOException(message);
                discovered.completeExceptionally(error);
                result.completeExceptionally(error);
            }

            private void finish(int battery) {
                result.complete(new EspDeviceConnection(device.getAddress(), battery));
            }

            @Override public void onConnectionStateChange(BluetoothGatt connection, int status, int state) {
                if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                    if (!connection.discoverServices()) fail("ESP не отвечает");
                } else if (authorized) finish(-1);
                else fail("Не удалось подключиться к ESP по Bluetooth");
            }

            @Override public void onServicesDiscovered(BluetoothGatt connection, int status) {
                BluetoothGattService service = connection.getService(BleStream.SERVICE);
                if (status != BluetoothGatt.GATT_SUCCESS || service == null) {
                    fail("Сервис микрофона ESP недоступен");
                    return;
                }
                BluetoothGattCharacteristic control = service.getCharacteristic(BleStream.SECURE_CONTROL);
                if (control == null) {
                    fail("Обнови прошивку ESP до версии 1.2.0 для сопряжения");
                    return;
                }
                discovered.complete(control);
            }

            @Override public void onCharacteristicWrite(BluetoothGatt connection, BluetoothGattCharacteristic control, int status) {
                if (status != BluetoothGatt.GATT_SUCCESS || !connection.readCharacteristic(control)) {
                    fail("ESP не ответила на запрос");
                }
            }

            @Override public void onCharacteristicRead(BluetoothGatt connection, BluetoothGattCharacteristic characteristic, int status) {
                onCharacteristicRead(connection, characteristic, characteristic.getValue(), status);
            }

            @Override public void onCharacteristicRead(BluetoothGatt connection, BluetoothGattCharacteristic characteristic,
                                                       byte[] bytes, int status) {
                if (BATTERY_LEVEL.equals(characteristic.getUuid())) {
                    int percent = status == BluetoothGatt.GATT_SUCCESS && bytes != null && bytes.length == 1 ? bytes[0] & 255 : -1;
                    finish(percent <= 100 ? percent : -1);
                    return;
                }
                String reply = bytes == null ? "" : new String(bytes, StandardCharsets.US_ASCII).trim();
                if (status != BluetoothGatt.GATT_SUCCESS) {
                    fail("Не удалось подтвердить сопряжение с ESP");
                    return;
                }
                if (!reply.startsWith("READY 16000 ")) {
                    fail(reply.equals("PAIRING_CLOSED") ? "Удержи BOOT на включённом ESP и повтори"
                            : "ESP не подтвердила сопряжение");
                    return;
                }
                authorized = true;
                Matcher reported = REPORTED_BATTERY.matcher(reply);
                if (reported.find()) {
                    int percent = Integer.parseInt(reported.group(1));
                    if (percent <= 100) {
                        finish(percent);
                        return;
                    }
                }
                BluetoothGattService service = connection.getService(BATTERY_SERVICE);
                BluetoothGattCharacteristic battery = service == null ? null : service.getCharacteristic(BATTERY_LEVEL);
                if (battery == null || !connection.readCharacteristic(battery)) finish(-1);
            }
        }, BluetoothDevice.TRANSPORT_LE);
        if (gatt == null) throw new IOException("Не удалось подключиться к ESP по Bluetooth");
        try {
            BluetoothGattCharacteristic control = EspFirmwareVersion.await(discovered,
                    new IOException("Сервис микрофона ESP не ответил"));
            bond(context, device, result);
            byte[] command = "STATUS".getBytes(StandardCharsets.US_ASCII);
            boolean sent;
            if (Build.VERSION.SDK_INT >= 33) {
                sent = gatt.writeCharacteristic(control, command, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
                        == BluetoothStatusCodes.SUCCESS;
            } else {
                control.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                control.setValue(command);
                sent = gatt.writeCharacteristic(control);
            }
            if (!sent) throw new IOException("ESP не принимает запрос");
            return EspFirmwareVersion.await(result, new IOException("ESP-микрофон не ответил"));
        } finally {
            gatt.close();
        }
    }

    private static void bond(Context context, BluetoothDevice device, CompletableFuture<?> connection) throws Exception {
        if (device.getBondState() == BluetoothDevice.BOND_BONDED) return;

        CompletableFuture<Boolean> bonded = new CompletableFuture<>();
        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context ignored, Intent intent) {
                if (!BluetoothDevice.ACTION_BOND_STATE_CHANGED.equals(intent.getAction())
                        || !device.equals(intent.getParcelableExtra(BluetoothDevice.EXTRA_DEVICE))) return;
                int state = device.getBondState();
                if (state == BluetoothDevice.BOND_BONDED) bonded.complete(true);
                else if (state == BluetoothDevice.BOND_NONE && intent.getIntExtra(BluetoothDevice.EXTRA_PREVIOUS_BOND_STATE,
                        BluetoothDevice.ERROR) == BluetoothDevice.BOND_BONDING) bonded.complete(false);
            }
        };
        IntentFilter filter = new IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED);
        if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED);
        else context.registerReceiver(receiver, filter);

        try {
            int state = device.getBondState();
            if (state == BluetoothDevice.BOND_BONDED) return;
            if (state == BluetoothDevice.BOND_NONE && !device.createBond()
                    && device.getBondState() == BluetoothDevice.BOND_NONE) {
                throw new IOException("Не удалось начать сопряжение по Bluetooth");
            }
            try {
                CompletableFuture.anyOf(bonded, connection).get(30, TimeUnit.SECONDS);
            } catch (TimeoutException error) {
                if (device.getBondState() != BluetoothDevice.BOND_BONDED) {
                    throw new IOException("Не удалось дождаться сопряжения с ESP");
                }
            } catch (java.util.concurrent.ExecutionException error) {
                throw new IOException("Связь с ESP прервалась во время сопряжения", error);
            }
            if (device.getBondState() != BluetoothDevice.BOND_BONDED) {
                throw new IOException("Сопряжение не завершено. Подтверди запрос Bluetooth");
            }
        } finally {
            context.unregisterReceiver(receiver);
        }
    }
}
