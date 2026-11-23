#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

constexpr uint16_t minAudioMtu = 185;
constexpr size_t audioHeaderBytes = 8;
constexpr size_t maxAudioBytes = 500;

inline size_t framesPerNotification(uint16_t mtu) {
  if (mtu < minAudioMtu) return 0;
  const size_t available = mtu - 3 - audioHeaderBytes;
  return (available < maxAudioBytes ? available : maxAudioBytes) / sizeof(int16_t);
}

struct BlePcmCursor {
  uint32_t sequence = 0;
  uint32_t firstFrame = 0;

  size_t pack(uint8_t *packet, const int16_t *samples, size_t frames) {
    uint32_t header[] = {sequence, firstFrame};
    std::memcpy(packet, header, sizeof(header));
    std::memcpy(packet + sizeof(header), samples, frames * sizeof(int16_t));
    ++sequence;
    firstFrame += frames;
    return sizeof(header) + frames * sizeof(int16_t);
  }
};
