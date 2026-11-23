#include <Arduino.h>
#include <driver/i2s.h>
#include <WiFi.h>
#include <Preferences.h>
#include <ESPmDNS.h>
#include <math.h>
#include <NimBLEDevice.h>
#include <nimble/nimble/host/include/host/ble_store.h>

static const char FIRMWARE_VERSION[] = "1.2.0";
static const char* BLE_SERVICE = "b8a10001-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_CONTROL = "b8a10002-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_AUDIO = "b8a10003-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_VERSION = "b8a10004-51e9-4a0b-8e27-047c45f78210";
static const char* BLE_SECURE_CONTROL = "b8a10005-51e9-4a0b-8e27-047c45f78210";
static constexpr uint8_t BOOT_PIN = 0;
static constexpr uint32_t PAIRING_WINDOW_MS = 60000;
static volatile uint32_t pairingUntil = 0;
static uint8_t trustedBondKey[16];
static bool hasTrustedBond = false;
static NimBLECharacteristic* bleAudio;
static volatile bool bleActive=false, otherStream=false;
static volatile uint16_t bleMtu=23, bleStreamOwner=BLE_HS_CONN_HANDLE_NONE;
static uint32_t bleSequence=0, bleFrames=0;

static int32_t samples[256];
static int16_t pcm[256];
static bool ok = false;
static uint32_t lastReport = 0;
static String apName, apPassword, accessToken;
static String stationName, stationPassword, hostName;
static WiFiServer server(8766);

class RecorderBleCallbacks: public NimBLEServerCallbacks {
  void onConnect(NimBLEServer* s, NimBLEConnInfo& info) override { s->updateConnParams(info.getConnHandle(),12,12,0,200); }
  void onDisconnect(NimBLEServer*,NimBLEConnInfo& info,int) override {
    if(bleStreamOwner==info.getConnHandle()){bleActive=false;bleStreamOwner=BLE_HS_CONN_HANDLE_NONE;}
    NimBLEDevice::startAdvertising();
  }
  void onMTUChange(uint16_t mtu,NimBLEConnInfo& info) override { if(bleStreamOwner==info.getConnHandle())bleMtu=mtu; }
};
bool startBleStream(NimBLEConnInfo& info) {
  if (!ok || otherStream || bleActive || info.getMTU() < 247) return false;
  bleSequence = 0;
  bleFrames = 0;
  bleStreamOwner = info.getConnHandle();
  bleMtu = info.getMTU();
  bleActive = true;
  return true;
}

bool stopBleStream(NimBLEConnInfo& info) {
  if (bleStreamOwner != info.getConnHandle()) return false;
  bleActive = false;
  bleStreamOwner = BLE_HS_CONN_HANDLE_NONE;
  return true;
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
  if (!enroll || !pairingOpen() || bleActive || otherStream) return false;
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
  if (pairingUntil != 0 && !pairingOpen()) pairingUntil = 0;
  if (digitalRead(BOOT_PIN) == HIGH) {
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
  NimBLEDevice::init("ESP Lectures");NimBLEDevice::setMTU(517);
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
  auto advertising=NimBLEDevice::getAdvertising();advertising->setName("ESP Lectures");advertising->addServiceUUID(BLE_SERVICE);advertising->enableScanResponse(true);advertising->start();
}
void sendBle(size_t count){
  const uint16_t owner = bleStreamOwner;
  if (owner == BLE_HS_CONN_HANDLE_NONE) return;
  const size_t maximum=min((size_t)bleMtu-11,(size_t)500)/2;
  uint8_t packet[508];
  for(size_t offset=0;offset<count&&bleActive;offset+=maximum){
    size_t frames=min(maximum,count-offset);memcpy(packet,&bleSequence,4);memcpy(packet+4,&bleFrames,4);memcpy(packet+8,pcm+offset,frames*2);
    bool sent=false;uint32_t deadline=millis()+30;
    while (bleActive && bleStreamOwner == owner && !sent && (int32_t)(deadline - millis()) > 0) {
      sent = bleAudio->notify(packet, 8 + frames * 2, owner);
      if (!sent) delay(1);
    }
    ++bleSequence;bleFrames+=frames;
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
  esp_err_t err = i2s_read(I2S_NUM_0, samples, sizeof(samples), &bytes, pdMS_TO_TICKS(1000));
  count = bytes / 4;
  if (err != ESP_OK || !count) return false;
  for (size_t i = 0; i < count; ++i) {
    int32_t value = samples[i] >> 13;
    pcm[i] = (int16_t)constrain(value, -32768, 32767);
  }
  return true;
}

void streamAudio(Stream &output, WiFiClient *client = nullptr) {
  otherStream=true;
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
  otherStream=false;
}

void setup() {
  pinMode(BOOT_PIN, INPUT_PULLUP);
  Serial.begin(921600);
  Serial.setTimeout(1000);
  delay(300);
  i2s_config_t config = {};
  config.mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX);
  config.sample_rate = 16000;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  config.dma_buf_count = 16;
  config.dma_buf_len = 256;
  i2s_pin_config_t pins = {};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = 4;
  pins.ws_io_num = 5;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  pins.data_in_num = 6;
  esp_err_t err = i2s_driver_install(I2S_NUM_0, &config, 0, nullptr);
  if (err == ESP_OK) err = i2s_set_pin(I2S_NUM_0, &pins);
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
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  bool wifiOK = WiFi.softAP(apName.c_str(), apPassword.c_str(), 1, 0, 1);
  WiFi.setSleep(true);
  WiFi.setAutoReconnect(true);
  if (!stationName.isEmpty()) WiFi.begin(stationName.c_str(), stationPassword.c_str());
  hostName = apName;
  hostName.toLowerCase();
  MDNS.begin(hostName.c_str());
  MDNS.addService("esp-recorder", "tcp", 8766);
  setupBle();
  server.begin();
  server.setNoDelay(true);
  Serial.printf("MIC_READY ok=%d error=%d rate=16000 pins=4,5,6 wifi=%d\n", ok, err, wifiOK);
}

void loop() {
  updatePairingButton();
  int command = Serial.available() ? Serial.read() : -1;
  if(command=='b')Serial.printf("BLE_ADDRESS %s\n",NimBLEDevice::getAddress().toString().c_str());
  if (command == 'p') {
    Serial.printf("PAIR %s\t%s\t%s\t%s\n", apName.c_str(), apPassword.c_str(), accessToken.c_str(), WiFi.softAPIP().toString().c_str());
  }
  if (command == 'w') {
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
  if (ok && !bleActive && command == 's') streamAudio(Serial);
  WiFiClient client = server.available();
  if (client) {
    client.setTimeout(1500);
    client.setNoDelay(true);
    String request = client.readStringUntil('\n');
    request.trim();
    if (request == "VERSION") {
      client.printf("VERSION %s\n", FIRMWARE_VERSION);
    } else if (request == String("PING ") + accessToken) {
      client.printf("READY rate=16000 uptime=%lu clients=%d mic=%d\n", (unsigned long)(millis()/1000), WiFi.softAPgetStationNum(), ok);
    } else if (ok && !bleActive && request == String("START ") + accessToken) {
      streamAudio(client, &client);
    } else {
      client.println("DENIED");
    }
    client.stop();
  }
  if (!ok) { delay(100); return; }
  size_t count;
  if(bleActive){if(readBlock(count))sendBle(count);return;}
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
