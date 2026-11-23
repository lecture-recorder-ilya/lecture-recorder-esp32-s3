#include "capture_stats.h"
#include <algorithm>
#include <Arduino.h>
#include <SD.h>
#include <SPI.h>
#include <driver/i2s.h>
#include <esp_heap_caps.h>

constexpr uint32_t rate = 16000;
#ifndef BENCH_SECONDS
#define BENCH_SECONDS 45
#endif
constexpr uint32_t durationMs = BENCH_SECONDS * 1000;
constexpr size_t pcmBytes = rate * BENCH_SECONDS * sizeof(int16_t);
constexpr i2s_port_t port = I2S_NUM_0;
uint8_t *pcm = nullptr;
bool ready = false;

bool capture() {
  i2s_config_t config{};
  config.mode = static_cast<i2s_mode_t>(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM);
  config.sample_rate = rate;
  config.bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT;
  config.channel_format = I2S_CHANNEL_FMT_ONLY_LEFT;
  config.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  config.dma_buf_count = 12;
  config.dma_buf_len = 256;
  QueueHandle_t events = nullptr;
  if (i2s_driver_install(port, &config, 32, &events) != ESP_OK) return false;
  i2s_pin_config_t pins{};
  pins.mck_io_num = I2S_PIN_NO_CHANGE;
  pins.bck_io_num = I2S_PIN_NO_CHANGE;
  pins.ws_io_num = 42;
  pins.data_in_num = 41;
  pins.data_out_num = I2S_PIN_NO_CHANGE;
  bool ok = i2s_set_pin(port, &pins) == ESP_OK &&
            i2s_set_pdm_rx_down_sample(port, I2S_PDM_DSR_16S) == ESP_OK;
  CaptureStats stats;
  size_t used = 0;
  uint8_t warmup[512];
  for (int i = 0; ok && i < 8; ++i) {
    size_t got = 0;
    ok = i2s_read(port, warmup, sizeof(warmup), &got, pdMS_TO_TICKS(500)) == ESP_OK && got == sizeof(warmup);
  }
  xQueueReset(events);
  const uint32_t start = millis();
  while (ok && used < pcmBytes) {
    size_t got = 0;
    const size_t chunk = std::min<size_t>(2048, pcmBytes - used);
    const esp_err_t result = i2s_read(port, pcm + used, chunk, &got, pdMS_TO_TICKS(500));
    ok = result == ESP_OK && got == chunk;
    used += got;
    if (uxQueueSpacesAvailable(events) == 0) stats.eventQueueFull = true;
    i2s_event_t event;
    while (xQueueReceive(events, &event, 0) == pdTRUE) {
      if (event.type == I2S_EVENT_RX_Q_OVF) stats.addOverflow(event.size);
      if (event.type == I2S_EVENT_DMA_ERROR) ++stats.dmaErrors;
    }
  }
  uint32_t elapsed = millis() - start;
  i2s_driver_uninstall(port);
  stats.addPcm(reinterpret_cast<const int16_t *>(pcm), used / sizeof(int16_t));
  Serial.printf("PCM samples=%u target=%u missing_from_target=%u elapsed_ms=%u "
                "rms_dbfs=%.2f peak_pcm=%d rail_samples=%u rx_overflows=%u "
                "lost_samples_min=%u dma_errors=%u event_queue_full=%u\n",
                unsigned(stats.samples), unsigned(pcmBytes / 2), unsigned((pcmBytes - used) / 2),
                unsigned(elapsed), stats.rmsDbfs(), int(stats.peak), unsigned(stats.railSamples),
                unsigned(stats.overflowEvents), unsigned(stats.lostSamplesMin),
                unsigned(stats.dmaErrors), unsigned(stats.eventQueueFull));
  return ok && stats.streamIntact() && used == pcmBytes &&
         elapsed >= durationMs - 500 && elapsed <= durationMs + 500;
}

void put32(uint8_t *dest, uint32_t value) {
  for (int i = 0; i < 4; ++i) dest[i] = value >> (8 * i);
}

bool saveTake() {
  char finalName[16], tempName[16];
  for (int n = 1; n <= 999; ++n) {
    snprintf(finalName, sizeof(finalName), "/P1_%03d.WAV", n);
    snprintf(tempName, sizeof(tempName), "/P1_%03d.TMP", n);
    if (SD.exists(finalName) || SD.exists(tempName)) continue;
    File file = SD.open(tempName, FILE_WRITE);
    if (!file) return false;
    uint8_t header[44] = {'R','I','F','F',0,0,0,0,'W','A','V','E','f','m','t',' ',
                          16,0,0,0,1,0,1,0,0,0,0,0,0,0,0,0,2,0,16,0,'d','a','t','a',0,0,0,0};
    put32(header + 4, pcmBytes + 36);
    put32(header + 24, rate);
    put32(header + 28, rate * 2);
    put32(header + 40, pcmBytes);
    bool ok = file.write(header, sizeof(header)) == sizeof(header);
    for (size_t offset = 0; ok && offset < pcmBytes;) {
      size_t chunk = std::min<size_t>(16384, pcmBytes - offset);
      ok = file.write(pcm + offset, chunk) == chunk;
      offset += chunk;
    }
    file.flush();
    ok = ok && file.size() == pcmBytes + sizeof(header);
    file.close();
    if (!ok || !SD.rename(tempName, finalName)) return false;
    Serial.println(finalName);
    return true;
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  pinMode(D0, INPUT_PULLUP);
  pinMode(D1, OUTPUT);
  digitalWrite(D1, LOW);
  SPI.begin(SCK, MISO, MOSI, D2);
  pcm = static_cast<uint8_t *>(heap_caps_malloc(pcmBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  ready = pcm && SD.begin(D2, SPI);
  Serial.println(ready ? "READY: r / REC" : "ERROR: PSRAM or SD");
}

void loop() {
  if (!ready) {
    digitalWrite(D1, (millis() / 200) % 2);
    delay(20);
    return;
  }
  bool triggered = Serial.available() && Serial.read() == 'r';
  if (!triggered && digitalRead(D0) == HIGH) {
    delay(10);
    return;
  }
  digitalWrite(D1, HIGH);
  const bool ok = capture() && saveTake();
  digitalWrite(D1, LOW);
  if (!ok) {
    Serial.println("ERROR: capture or SD save");
    for (int i = 0; i < 5; ++i) {
      digitalWrite(D1, HIGH); delay(120); digitalWrite(D1, LOW); delay(120);
    }
  }
  while (digitalRead(D0) == LOW) delay(10);
  delay(40);
}
