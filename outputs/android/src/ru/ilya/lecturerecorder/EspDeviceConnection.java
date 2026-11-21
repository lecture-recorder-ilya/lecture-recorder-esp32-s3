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
import android.content.Context;
import android.os.Build;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

final class EspDeviceConnection {
    private static final UUID BATTERY_SERVICE = UUID.fromString("0000180f-0000-1000-8000-00805f9b34fb");
    private static final UUID BATTERY_LEVEL = UUID.fromString("00002a19-0000-1000-8000-00805f9b34fb");

    private static final Pattern REPORTED_BATTERY = Pattern.compile("(?:^| )battery=([0-9]{1,3})(?: |$)");

    final String address;
    final int battery;

    private EspDeviceConnection(String address, int battery) {
        this.address = address;
        this.battery = battery;
    }

    static EspDeviceConnection bluetooth(Context context, String cachedAddress, String code) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Включи Bluetooth");
        BluetoothDevice device = BluetoothAdapter.checkBluetoothAddress(cachedAddress)
                ? adapter.getRemoteDevice(cachedAddress) : EspFirmwareVersion.findBluetooth(adapter, "", true);
        CompletableFuture<EspDeviceConnection> result = new CompletableFuture<>();
        BluetoothGatt gatt = device.connectGatt(context, false, new BluetoothGattCallback() {
            private boolean authorized;

            private void fail(String message) {
                result.completeExceptionally(new IOException(message));
            }

            private void finish(int battery) {
                result.complete(new EspDeviceConnection(device.getAddress(), battery));
            }

            @Override public void onConnectionStateChange(BluetoothGatt connection, int status, int state) {
                if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                    if (!connection.requestMtu(128)) fail("Не удалось настроить Bluetooth");
                } else if (authorized) finish(-1);
                else fail("Не удалось подключиться к ESP по Bluetooth");
            }

            @Override public void onMtuChanged(BluetoothGatt connection, int mtu, int status) {
                if (status != BluetoothGatt.GATT_SUCCESS || mtu < 40 || !connection.discoverServices()) {
                    fail("Не удалось настроить Bluetooth");
                }
            }
            @Override public void onServicesDiscovered(BluetoothGatt connection, int status) {
                BluetoothGattService service = connection.getService(BleStream.SERVICE);
                BluetoothGattCharacteristic control = service == null ? null : service.getCharacteristic(BleStream.CONTROL);
                if (status != BluetoothGatt.GATT_SUCCESS || control == null) {
                    fail("Сервис микрофона ESP недоступен");
                    return;
                }
                boolean sent;
                byte[] command = "PING ".concat(code).getBytes(StandardCharsets.US_ASCII);
                if (Build.VERSION.SDK_INT >= 33) {
                    sent = connection.writeCharacteristic(control, command, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT)
                            == BluetoothStatusCodes.SUCCESS;
                } else {
                    control.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT);
                    control.setValue(command);
                    sent = connection.writeCharacteristic(control);
                }
                if (!sent) fail("ESP не принимает запрос");
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
                if (status != BluetoothGatt.GATT_SUCCESS || !reply.startsWith("READY 16000 ")) {
                    fail("ESP не приняла код. Проверь код и версию прошивки");
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
            return EspFirmwareVersion.await(result, new IOException("ESP-микрофон не ответил"));
        } finally {
            gatt.close();
        }
    }

}
