package ru.ilya.lecturerecorder;

import android.bluetooth.BluetoothAdapter;
import android.bluetooth.BluetoothDevice;
import android.bluetooth.BluetoothGatt;
import android.bluetooth.BluetoothGattCallback;
import android.bluetooth.BluetoothGattCharacteristic;
import android.bluetooth.BluetoothGattService;
import android.bluetooth.BluetoothManager;
import android.bluetooth.BluetoothProfile;
import android.bluetooth.le.BluetoothLeScanner;
import android.bluetooth.le.ScanCallback;
import android.bluetooth.le.ScanFilter;
import android.bluetooth.le.ScanResult;
import android.bluetooth.le.ScanSettings;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.ParcelUuid;

import java.io.IOException;
import java.net.ProtocolException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Pattern;

final class EspFirmwareVersion {
    private static final int PORT = 8766;
    private static final UUID CHARACTERISTIC = UUID.fromString("b8a10004-51e9-4a0b-8e27-047c45f78210");
    private static final Pattern VERSION = Pattern.compile("[0-9]{1,4}\\.[0-9]{1,4}\\.[0-9]{1,4}(?:-[A-Za-z0-9.-]{1,20})?");
    private static final String UNAVAILABLE = "Микрофон не сообщает версию прошивки";

    static final class NotFound extends IOException {
        NotFound(String message) { super(message); }
    }

    static void checkPresence(Context context) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Bluetooth выключен");
        String address = context.getSharedPreferences("settings", 0).getString("ble_address", "");
        findBluetooth(adapter, address, false);
    }

    static String bluetooth(Context context) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Bluetooth выключен");
        String address = context.getSharedPreferences("settings", 0).getString("ble_address", "");
        BluetoothDevice device = BluetoothAdapter.checkBluetoothAddress(address)
                ? adapter.getRemoteDevice(address) : findBluetooth(adapter, "", true);
        CompletableFuture<String> result = new CompletableFuture<>();
        BluetoothGatt gatt = device.connectGatt(context, false, new BluetoothGattCallback() {
            @Override public void onConnectionStateChange(BluetoothGatt connection, int status, int state) {
                if (status == BluetoothGatt.GATT_SUCCESS && state == BluetoothProfile.STATE_CONNECTED) {
                    if (!connection.discoverServices()) result.completeExceptionally(new IOException("ESP не отвечает"));
                } else if (status != BluetoothGatt.GATT_SUCCESS || state == BluetoothProfile.STATE_DISCONNECTED) {
                    result.completeExceptionally(new IOException("ESP-микрофон не подключён по Bluetooth"));
                }
            }

            @Override public void onServicesDiscovered(BluetoothGatt connection, int status) {
                BluetoothGattService service = connection.getService(BleStream.SERVICE);
                if (status != BluetoothGatt.GATT_SUCCESS || service == null) {
                    result.completeExceptionally(new IOException("Сервис ESP-микрофона недоступен"));
                    return;
                }
                BluetoothGattCharacteristic version = service.getCharacteristic(CHARACTERISTIC);
                if (version == null) result.complete(UNAVAILABLE);
                else if (!connection.readCharacteristic(version)) {
                    result.completeExceptionally(new IOException("Не удалось прочитать версию прошивки"));
                }
            }

            @Override public void onCharacteristicRead(BluetoothGatt connection, BluetoothGattCharacteristic value,
                                                       int status) {
                onCharacteristicRead(connection, value, value.getValue(), status);
            }

            @Override public void onCharacteristicRead(BluetoothGatt connection, BluetoothGattCharacteristic value,
                                                       byte[] bytes, int status) {
                try {
                    if (status != BluetoothGatt.GATT_SUCCESS || bytes == null) {
                        throw new IOException("Не удалось прочитать версию прошивки");
                    }
                    result.complete(format(new String(bytes, StandardCharsets.US_ASCII)));
                } catch (IOException error) {
                    result.completeExceptionally(error);
                }
            }
        }, BluetoothDevice.TRANSPORT_LE);
        if (gatt == null) throw new IOException("Не удалось подключиться к ESP по Bluetooth");
        try {
            return await(result, new IOException("ESP-микрофон не ответил по Bluetooth"));
        } finally {
            gatt.close();
        }
    }

    static BluetoothDevice findBluetooth(BluetoothAdapter adapter, String address, boolean interactive) throws Exception {
        BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) throw new IOException("Поиск Bluetooth недоступен");
        CompletableFuture<BluetoothDevice> device = new CompletableFuture<>();
        ScanCallback callback = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult result) { device.complete(result.getDevice()); }

            @Override public void onScanFailed(int error) {
                device.completeExceptionally(new IOException("Не удалось найти ESP по Bluetooth"));
            }
        };
        ScanFilter.Builder filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(BleStream.SERVICE));
        if (BluetoothAdapter.checkBluetoothAddress(address)) filter.setDeviceAddress(address);
        ScanSettings scanSettings = new ScanSettings.Builder().setScanMode(interactive
                ? ScanSettings.SCAN_MODE_LOW_LATENCY : ScanSettings.SCAN_MODE_LOW_POWER).build();
        scanner.startScan(Collections.singletonList(filter.build()), scanSettings, callback);
        try {
            return await(device, new NotFound("ESP-микрофон не найден по Bluetooth"));
        } finally {
            scanner.stopScan(callback);
        }
    }

    static <T> T await(CompletableFuture<T> result, IOException timeout)
            throws IOException, InterruptedException {
        try {
            return result.get(8, TimeUnit.SECONDS);
        } catch (TimeoutException error) {
            throw timeout;
        } catch (ExecutionException error) {
            if (error.getCause() instanceof IOException) throw (IOException) error.getCause();
            throw new IOException("Не удалось проверить версию прошивки", error);
        }
    }

    private static String format(String version) throws IOException {
        if (!VERSION.matcher(version).matches()) throw new ProtocolException("Некорректная версия прошивки");
        return "Версия прошивки · " + version;
    }

    private EspFirmwareVersion() {}
}
