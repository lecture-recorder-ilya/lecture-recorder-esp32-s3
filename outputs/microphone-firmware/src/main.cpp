#include <Arduino.h>
#include <driver/i2s.h>
#include <WiFi.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <math.h>
#include <NimBLEDevice.h>
#include <nimble/nimble/host/include/host/ble_store.h>
#include <atomic>
#include "ble_pcm.h"

static const char FIRMWARE_VERSION[] = "1.3.0";
static const char* BLE_SERVICE = "b8a10001-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_CONTROL = "b8a10002-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_AUDIO = "b8a10003-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_VERSION = "b8a10004-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_SECURE_CONTROL = "b8a10005-51e9-4a0b-8e27-047c45f78210";
static constexpr uint8_t BOOT_PIN = 0;
static constexpr uint32_t PAIRING_WINDOW_MS = 60000;
static std::atomic<uint32_t> pairingUntil{0};
static uint8_t trustedBondKey[16];
static bool hasTrustedBond = false;
static NimBLECharacteristic* bleAudio;
static constexpr uint32_t idleStream = 0, directStream = 1;
static std::atomic<uint32_t> activeStream{idleStream};
static std::atomic<uint16_t> bleMtu{23};
static uint16_t streamGeneration = 0;
#ifdef CLIPMIC_P1
static constexpr bool wifiEnabled = false;
static constexpr char microphonePins[] = "42,41";
#else
static constexpr bool wifiEnabled = true;
static constexpr char microphonePins[] = "4,5,6";
static int32_t samples[256];
#endif
static int16_t pcm[256];
static bool ok = false;
static uint32_t lastReport = 0;
static String apName, apPassword, accessToken;
static String stationName, stationPassword, hostName;
static WiFiServer server(8766);

bool ownsBleStream(uint32_t stream, uint16_t handle) {
  return stream > directStream && static_cast<uint16_t>(stream) == handle;
}

bool stopBleStream(NimBLEConnInfo& info) {
  uint32_t stream = activeStream.load();
  return ownsBleStream(stream, info.getConnHandle()) && activeStream.compare_exchange_strong(stream, idleStream);
}

class RecorderBleCallbacks: public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override {
    s->setDataLen(info.getConnHandle(), 251);
    s->updateConnParams(info.getConnHandle(), 12, 12, 0, 200);
  }
  void onDisconnect(NimBLEServer*,NimBLEConnInfo& info,int) override {
    stopBleStream(info);
    NimBLEDevice::startAdvertising();
  }
  void onMTUChange(uint16_t mtu,NimBLEConnInfo& info) override {
    if (ownsBleStream(activeStream.load(), info.getConnHandle())) bleMtu.store(mtu);
  }
};
bool startBleStream(NimBLEConnInfo& info) {
  if (!ok || activeStream.load() != idleStream || !framesPerNotification(info.getMTU())) return false;
  if (++streamGeneration == 0) ++streamGeneration;
  bleMtu.store(info.getMTU());
  uint32_t expected = idleStream;
  const uint32_t stream = (uint32_t(streamGeneration) << 16) | info.getConnHandle();
  return activeStream.compare_exchange_strong(expected, stream);
}

class RecorderControlCallbacks: public NimBLECharacteristicCallbacks {
  void onWrite(NimBLECharacteristic* c,NimBLEConnInfo& info) override {
    String request(c->getValue().c_str());
    if (request == String("START ") + accessToken && startBleStream(info)) c->setValue("READY 16000 PCM16");
    else if (request == String("PING ") + accessToken) c->setValue(ok ? "READY 16000 mic=1" : "READY 16000 mic=0");
    else if (request == String("STOP ") + accessToken && stopBleStream(info)) c->setValue("STOPPED");
    else c->setValue("DENIED");
  }
};

bool pairingOpen() {
  uint32_t deadline = pairingUntil;
  return deadline != 0 && (int32_t)(deadline - millis()) > 0;
}

bool allowBond(NimBLEConnInfo& info, bool enroll = false) {
  if (!info.isEncrypted() || !info.isBonded()) return false;
  ble_store_key_sec lookup = {};
  lookup.peer_addr = *info.getIdAddress().getBase();
  ble_store_value_sec bond = {};
  if (ble_store_read_our_sec(&lookup, &bond) != 0 || !bond.ltk_present || !bond.sc) return false;

  if (hasTrustedBond && memcmp(trustedBondKey, bond.ltk, sizeof(trustedBondKey)) == 0) return true;
  if (!enroll || !pairingOpen() || activeStream.load() != idleStream) return false;
  Preferences prefs;
  if (!prefs.begin("recorder", false)
      || prefs.putBytes("bleBond", bond.ltk, sizeof(trustedBondKey)) != sizeof(trustedBondKey)) return false;
  memcpy(trustedBondKey, bond.ltk, sizeof(trustedBondKey));
  hasTrustedBond = true;
  pairingUntil = 0;
  return true;
}

class SecureRecorderControlCallbacks : public NimBLECharacteristicCallbacks {
  const char* reply = "DENIED";
  uint16_t replyFor = BLE_HS_CONN_HANDLE_NONE;

  void onWrite(NimBLECharacteristic* c, NimBLEConnInfo& info) override {
    String request(c->getValue().c_str());
    if (!allowBond(info, request == "STATUS")) return;

    replyFor = info.getConnHandle();
    if (request == "STATUS") reply = ok ? "READY 16000 mic=1" : "READY 16000 mic=0";
    else if (request == "START" && startBleStream(info)) reply = "READY 16000 PCM16";
    else if (request == "STOP" && stopBleStream(info)) reply = "STOPPED";
    else reply = "DENIED";
  }

  void onRead(NimBLECharacteristic* c, NimBLEConnInfo& info) override {
    if (!allowBond(info)) c->setValue("PAIRING_CLOSED");
    else c->setValue(replyFor == info.getConnHandle() ? reply : "DENIED");
  }
};

void updatePairingButton() {
  static uint32_t pressedAt = 0;
  static bool pressed = false;
  static bool handled = false;
  uint32_t now = millis();
  uint32_t deadline = pairingUntil.load();
  if (deadline && (int32_t)(deadline - now) <= 0) pairingUntil.compare_exchange_strong(deadline, 0);
  bool held = digitalRead(BOOT_PIN) == LOW;
#ifdef CLIPMIC_P1
  held = held || digitalRead(D0) == LOW;
  digitalWrite(D1, (activeStream.load() != idleStream || (pairingOpen() && (now / 250) % 2)) ? HIGH : LOW);
#endif
  if (!held) {
    pressed = false;
    handled = false;
    return;
  }
  if (!pressed) {
    pressed = true;
    pressedAt = now;
  }
  if (!handled && now - pressedAt >= 700) {
    pairingUntil = now + PAIRING_WINDOW_MS;
    handled = true;
    Serial.println("BLE_PAIRING_OPEN");
  }
}

void setupBle(){
  NimBLEDevice::init("зу");NimBLEDevice::setMTU(517);
  NimBLEDevice::setSecurityAuth(true, false, true);
  NimBLEDevice::setSecurityIOCap(BLE_HS_IO_NO_INPUT_OUTPUT);
  NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);
  NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);
  auto s=NimBLEDevice::createServer();s->setCallbacks(new RecorderBleCallbacks());
  auto service=s->createService(BLE_SERVICE);
  auto control=service->createCharacteristic(BLE_CONTROL,NIMBLE_PROPERTY::READ|NIMBLE_PROPERTY::WRITE);
  control->setCallbacks(new RecorderControlCallbacks());control->setValue("READY");
  auto secure = service->createCharacteristic(BLE_SECURE_CONTROL,
      NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::READ_ENC | NIMBLE_PROPERTY::WRITE_ENC);
  secure->setCallbacks(new SecureRecorderControlCallbacks());
  secure->setValue("DENIED");
  bleAudio=service->createCharacteristic(BLE_AUDIO,NIMBLE_PROPERTY::NOTIFY);
  service->createCharacteristic(BLE_VERSION,NIMBLE_PROPERTY::READ)->setValue(FIRMWARE_VERSION);
  service->start();
  auto advertising = NimBLEDevice::getAdvertising();
  advertising->enableScanResponse(true);
  advertising->addServiceUUID(BLE_SERVICE);
  advertising->setName("зу");
  advertising->start();
}
void sendBle(uint32_t stream, size_t count) {
  static uint32_t previousStream = idleStream;
  static BlePcmCursor cursor;
  if (previousStream != stream) {
    cursor = BlePcmCursor{};
    previousStream = stream;
  }
  const size_t maximum = framesPerNotification(bleMtu.load());
  if (!maximum) return;
  uint8_t packet[audioHeaderBytes + maxAudioBytes];
  const uint32_t deadline = millis() + static_cast<uint32_t>(count * 1000 / 16000);
  for (size_t offset = 0; offset < count && activeStream.load() == stream; offset += maximum) {
    size_t frames = min(maximum, count - offset);
    size_t length = cursor.pack(packet, pcm + offset, frames);
    while (activeStream.load() == stream) {
      if (bleAudio->notify(packet, length, static_cast<uint16_t>(stream))) break;
      if ((int32_t)(deadline - millis()) <= 0) break;
      delay(1);
    }
  }
}

String fromHex(const String &input) {
  String result;
  if (input.length() % 2) return result;
  for (unsigned i = 0; i < input.length(); i += 2) {
    char pair[] = {input[i], input[i + 1], 0};
    char *end;
    long value = strtol(pair, &end, 16);
    if (*end || value == 0) return String();
    result += (char)value;
  }
  return result;
}

bool readBlock(size_t &count) {
  size_t bytes = 0;
#ifdef CLIPMIC_P1
  esp_err_t err = i2s_read(I2S_NUM_0, pcm, sizeof(pcm), &bytes, pdMS_TO_TICKS(250));
  count = bytes / sizeof(pcm[0]);
  return err == ESP_OK && count > 0;
#else
  esp_err_t err = i2s_read(I2S_NUM_0, samples, sizeof(samples), &bytes, pdMS_TO_TICKS(1000));
  count = bytes / sizeof(samples[0]);
  if (err != ESP_OK || !count) return false;
  for (size_t i = 0; i < count; ++i) {
    int32_t value = samples[i] >> 13;
    pcm[i] = (int16_t)constrain(value, -32768, 32767);
  }
  return true;
#endif
}

void streamAudio(Stream &output, WiFiClient *client = nullptr) {
  uint32_t expected = idleStream;
  if (!activeStream.compare_exchange_strong(expected, directStream)) {
    output.println("DENIED");
    return;
  }
  output.println("STREAM 16000");
  while (!client || client->connected()) {
    if (output.available() && output.read() == 'x') break;
    size_t count;
    if (!readBlock(count)) break;
    uint16_t length = count * 2;
    const uint8_t header[] = {'P', 'C', 'M', '1', (uint8_t)length, (uint8_t)(length >> 8)};
    if (output.write(header, sizeof(header)) != sizeof(header)) break;
    if (output.write((uint8_t*)pcm, length) != length) break;
  }
  const uint8_t end[] = {'P', 'C', 'M', '1', 0, 0};
  output.write(end, sizeof(end));
  lastReport = millis();
  activeStream.store(idleStream);
}

esp_err_t setupMicrophone() {
  i2s_config_t config = {};
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
#ifdef CLIPMIC_P1
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM);
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  pins.bck_io_num = I2S_PIN_NO_CHANGE;
  pins.ws_io_num = 42;
  pins.data_in_num = 41;
#else
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  pins.bck_io_num = 4;
  pins.ws_io_num = 5;
  pins.data_in_num = 6;
#endif
  config.sample_rate = 16000;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = 16;
  config.dma_buf_len = 256;
  esp_err_t err = i2s_driver_install(I2S_NUM_0, &config, 0, nullptr);
  if (err != ESP_OK) return err;
  err = i2s_set_pin(I2S_NUM_0, &pins);
#ifdef CLIPMIC_P1
  if (err == ESP_OK) err = i2s_set_pdm_rx_down_sample(I2S_NUM_0, I2S_PDM_DSR_16S);
#endif
  size_t frames = 0;
  if (err == ESP_OK && !readBlock(frames)) err = ESP_ERR_TIMEOUT;
  if (err != ESP_OK) i2s_driver_uninstall(I2S_NUM_0);
  return err;
}

void setup() {
  pinMode(BOOT_PIN, INPUT_PULLUP);
#ifdef CLIPMIC_P1
  pinMode(D0, INPUT_PULLUP);
  pinMode(D1, OUTPUT);
#endif
  Serial.begin(921600);
  Serial.setTimeout(1000);
  delay(300);
  esp_err_t err = setupMicrophone();
  ok = err == ESP_OK;
  Preferences prefs;
  prefs.begin("recorder", false);
  apName = prefs.getString("ssid", "");
  apPassword = prefs.getString("password", "");
  accessToken = prefs.getString("token", "");
  stationName = prefs.getString("staSSID", "");
  stationPassword = prefs.getString("staPass", "");
  hasTrustedBond = prefs.getBytesLength("bleBond") == sizeof(trustedBondKey)
      && prefs.getBytes("bleBond", trustedBondKey, sizeof(trustedBondKey)) == sizeof(trustedBondKey);
  if (apName.isEmpty() || apPassword.isEmpty() || accessToken.isEmpty()) {
    char suffix[9], password[17], token[33];
    snprintf(suffix, sizeof(suffix), "%08lx", (unsigned long)(ESP.getEfuseMac() & 0xffffffff));
    snprintf(password, sizeof(password), "%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random());
    snprintf(token, sizeof(token), "%08lx%08lx%08lx%08lx", (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random(), (unsigned long)esp_random());
    apName = String("ESP-Recorder-") + suffix;
    apPassword = password;
    accessToken = token;
    prefs.putString("ssid", apName);
    prefs.putString("password", apPassword);
    prefs.putString("token", accessToken);
  }
  prefs.end();
  bool wifiOK = false;
  if (wifiEnabled) {
    WiFi.persistent(false);
    WiFi.mode(WIFI_AP_STA);
    wifiOK = WiFi.softAP(apName.c_str(), apPassword.c_str(), 1, 0, 1);
    WiFi.setSleep(true);
    WiFi.setAutoReconnect(true);
    if (!stationName.isEmpty()) WiFi.begin(stationName.c_str(), stationPassword.c_str());
    hostName = apName;
    hostName.toLowerCase();
    MDNS.begin(hostName.c_str());
    MDNS.addService("esp-recorder", "tcp", 8766);
    server.begin();
    server.setNoDelay(true);
  }
  setupBle();
  Serial.printf("MIC_READY ok=%d error=%d rate=16000 pins=%s wifi=%d\n", ok, err, microphonePins, wifiOK);
}

void loop() {
  updatePairingButton();
  size_t count;
  uint32_t stream = activeStream.load();
  if (stream > directStream) {
    if (readBlock(count)) sendBle(stream, count);
    return;
  }
  int command = Serial.available() ? Serial.read() : -1;
  if(command=='b')Serial.printf("BLE_ADDRESS %s\n",NimBLEDevice::getAddress().toString().c_str());
  if (wifiEnabled && command == 'p') {
    Serial.printf("PAIR %s\t%s\t%s\t%s\n", apName.c_str(), apPassword.c_str(), accessToken.c_str(), WiFi.softAPIP().toString().c_str());
  }
  if (wifiEnabled && command == 'w') {
    Serial.setTimeout(3000);
    String request = Serial.readStringUntil('\n');
    Serial.setTimeout(1000);
    int tab = request.indexOf('\t');
    String name = fromHex(request.substring(0, tab));
    String password = fromHex(request.substring(tab + 1));
    if (tab < 0 || name.isEmpty() || name.length() > 32 || password.length() > 63) {
      Serial.println("WIFI_ERROR Invalid network settings");
    } else {
      WiFi.disconnect();
      WiFi.begin(name.c_str(), password.c_str());
      uint32_t start = millis();
      while (WiFi.status() != WL_CONNECTED && millis() - start < 25000) delay(100);
      if (WiFi.status() == WL_CONNECTED) {
        stationName = name;
        stationPassword = password;
        Preferences prefs;
        prefs.begin("recorder", false);
        prefs.putString("staSSID", stationName);
        prefs.putString("staPass", stationPassword);
        prefs.end();
        Serial.printf("WIFI_READY %s\t%s.local\n", WiFi.localIP().toString().c_str(), hostName.c_str());
      } else {
        Serial.println("WIFI_ERROR Connection failed: check hotspot, password and 2.4 GHz");
        if (!stationName.isEmpty()) WiFi.begin(stationName.c_str(), stationPassword.c_str());
      }
    }
  }
  if (ok && command == 's') streamAudio(Serial);
  WiFiClient client;
  if (wifiEnabled) client = server.available();
  if (client) {
    client.setTimeout(1500);
    client.setNoDelay(true);
    String request = client.readStringUntil('\n');
    request.trim();
    if (request == "VERSION") {
      client.printf("VERSION %s\n", FIRMWARE_VERSION);
    } else if (request == String("PING ") + accessToken) {
      client.printf("READY rate=16000 uptime=%lu clients=%d mic=%d\n", (unsigned long)(millis()/1000), WiFi.softAPgetStationNum(), ok);
    } else if (ok && request == String("START ") + accessToken) {
      streamAudio(client, &client);
    } else {
      client.println("DENIED");
    }
    client.stop();
  }
  if (!ok) { delay(100); return; }
  if (readBlock(count) && millis() - lastReport >= 1000) {
    double energy = 0;
    int peak = 0;
    for (size_t i = 0; i < count; ++i) {
      energy += (double)pcm[i] * pcm[i];
      peak = max(peak, abs((int)pcm[i]));
    }
    Serial.printf("LEVEL rms=%.1f peak=%d\n", sqrt(energy/count), peak);
    lastReport = millis();
  }
}
