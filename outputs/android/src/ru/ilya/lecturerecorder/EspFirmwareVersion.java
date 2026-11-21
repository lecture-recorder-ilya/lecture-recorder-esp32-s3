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
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.os.ParcelUuid;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
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

    static String wifi(Context context) throws Exception {
        SharedPreferences settings = context.getSharedPreferences("settings", 0);
        LinkedHashSet<String> hosts = new LinkedHashSet<>(Arrays.asList(settings.getString("ip", "").trim(),
                settings.getString("hostname", "").trim(), "192.168.4.1"));
        for (String host : hosts) {
            if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
            if (!host.isEmpty()) {
                try {
                    return queryWifiHost(host);
                } catch (IOException ignored) {
                    // Try the next address or the advertised service.
                }
            }
        }
        String discovered = discover(context);
        if (discovered != null && !hosts.contains(discovered)) {
            try {
                return queryWifiHost(discovered);
            } catch (IOException ignored) {
                // The service may have disconnected since discovery.
            }
        }
        throw new IOException("ESP-микрофон не найден по Wi-Fi");
    }

    static String queryWifiHost(String host) throws IOException {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(host, PORT), 1500);
            socket.setSoTimeout(1800);
            socket.getOutputStream().write("VERSION\n".getBytes(StandardCharsets.US_ASCII));
            InputStream input = socket.getInputStream();
            ByteArrayOutputStream response = new ByteArrayOutputStream();
            for (int value; (value = input.read()) != -1 && value != '\n'; ) {
                if (response.size() == 64) throw new IOException("Неизвестный ответ ESP");
                response.write(value);
            }
            String line = new String(response.toByteArray(), StandardCharsets.US_ASCII).trim();
            if ("DENIED".equals(line)) return UNAVAILABLE;
            if (!line.startsWith("VERSION ")) throw new IOException("Неизвестный ответ ESP");
            return format(line.substring("VERSION ".length()));
        }
    }

    private static String discover(Context context) throws InterruptedException {
        NsdManager manager = context.getSystemService(NsdManager.class);
        WifiManager wifi = context.getApplicationContext().getSystemService(WifiManager.class);
        if (manager == null || wifi == null) return null;
        CompletableFuture<String> result = new CompletableFuture<>();
        NsdManager.DiscoveryListener listener = new NsdManager.DiscoveryListener() {
            @Override public void onDiscoveryStarted(String type) {}
            @Override public void onDiscoveryStopped(String type) {}
            @Override public void onStartDiscoveryFailed(String type, int error) { result.complete(null); }
            @Override public void onStopDiscoveryFailed(String type, int error) {}
            @Override public void onServiceLost(NsdServiceInfo service) {}
            @Override public void onServiceFound(NsdServiceInfo service) {
                if (result.isDone()) return;
                manager.resolveService(service, new NsdManager.ResolveListener() {
                    @Override public void onResolveFailed(NsdServiceInfo info, int error) {}
                    @Override public void onServiceResolved(NsdServiceInfo info) {
                        if (info.getHost() != null && info.getPort() == PORT) {
                            result.complete(info.getHost().getHostAddress());
                        }
                    }
                });
            }
        };
        WifiManager.MulticastLock lock = wifi.createMulticastLock("ESP version discovery");
        boolean started = false;
        try {
            lock.acquire();
            manager.discoverServices("_esp-recorder._tcp.", NsdManager.PROTOCOL_DNS_SD, listener);
            started = true;
            return result.get(3, TimeUnit.SECONDS);
        } catch (TimeoutException | ExecutionException | RuntimeException error) {
            return null;
        } finally {
            result.complete(null);
            if (started) {
                try {
                    manager.stopServiceDiscovery(listener);
                } catch (IllegalArgumentException ignored) {}
            }
            if (lock.isHeld()) lock.release();
        }
    }

    static String bluetooth(Context context) throws Exception {
        BluetoothManager manager = context.getSystemService(BluetoothManager.class);
        BluetoothAdapter adapter = manager == null ? null : manager.getAdapter();
        if (adapter == null || !adapter.isEnabled()) throw new IOException("Bluetooth выключен");
        String address = context.getSharedPreferences("settings", 0).getString("ble_address", "");
        BluetoothDevice device = BluetoothAdapter.checkBluetoothAddress(address)
                ? adapter.getRemoteDevice(address) : findBluetooth(adapter);
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
            return await(result, "ESP-микрофон не ответил по Bluetooth");
        } finally {
            gatt.close();
        }
    }

    private static BluetoothDevice findBluetooth(BluetoothAdapter adapter) throws Exception {
        BluetoothLeScanner scanner = adapter.getBluetoothLeScanner();
        if (scanner == null) throw new IOException("Поиск Bluetooth недоступен");
        CompletableFuture<BluetoothDevice> device = new CompletableFuture<>();
        ScanCallback callback = new ScanCallback() {
            @Override public void onScanResult(int type, ScanResult result) { device.complete(result.getDevice()); }

            @Override public void onScanFailed(int error) {
                device.completeExceptionally(new IOException("Не удалось найти ESP по Bluetooth"));
            }
        };
        ScanFilter filter = new ScanFilter.Builder().setServiceUuid(new ParcelUuid(BleStream.SERVICE)).build();
        scanner.startScan(Collections.singletonList(filter), new ScanSettings.Builder().build(), callback);
        try {
            return await(device, "ESP-микрофон не найден по Bluetooth");
        } finally {
            scanner.stopScan(callback);
        }
    }

    private static <T> T await(CompletableFuture<T> result, String timeout)
            throws IOException, InterruptedException {
        try {
            return result.get(8, TimeUnit.SECONDS);
        } catch (TimeoutException error) {
            throw new IOException(timeout);
        } catch (ExecutionException error) {
            if (error.getCause() instanceof IOException) throw (IOException) error.getCause();
            throw new IOException("Не удалось проверить версию прошивки", error);
        }
    }

    private static String format(String version) throws IOException {
        if (!VERSION.matcher(version).matches()) throw new IOException("Некорректная версия прошивки");
        return "Версия прошивки · " + version;
    }

    private EspFirmwareVersion() {}
}
