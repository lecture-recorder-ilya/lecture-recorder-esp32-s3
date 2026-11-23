#include "../src/ble_pcm.h"
#include <algorithm>
#include <array>
#include <cassert>

uint32_t read32(const uint8_t *data) {
  return uint32_t(data[0]) | (uint32_t(data[1]) << 8) |
         (uint32_t(data[2]) << 16) | (uint32_t(data[3]) << 24);
}

int main() {
  assert(framesPerNotification(23) == 0);
  assert(framesPerNotification(184) == 0);
  assert(framesPerNotification(185) == 87);
  assert(framesPerNotification(247) == 118);
  assert(framesPerNotification(517) == 250);
  std::array<int16_t, 256> source;
  for (size_t i = 0; i < source.size(); ++i) source[i] = int16_t((int(i) - 128) * 239);
  for (uint16_t mtu = minAudioMtu; mtu <= 517; ++mtu) {
    BlePcmCursor cursor;
    uint32_t received = 0, index = 0;
    uint8_t packet[audioHeaderBytes + maxAudioBytes];
    for (int block = 0; block < 3; ++block) {
      for (size_t offset = 0; offset < source.size();) {
        size_t frames = std::min(framesPerNotification(mtu), source.size() - offset);
        size_t length = cursor.pack(packet, source.data() + offset, frames);
        assert(length == audioHeaderBytes + frames * sizeof(int16_t));
        assert(length <= mtu - 3u);
        assert(read32(packet) == index++);
        assert(read32(packet + 4) == received);
        for (size_t i = 0; i < frames; ++i) {
          size_t at = audioHeaderBytes + 2 * i;
          assert(int16_t(packet[at] | (uint16_t(packet[at + 1]) << 8)) == source[offset + i]);
        }
        received += frames;
        offset += frames;
      }
    }
    assert(received == 768);
    assert(cursor.firstFrame == received);
  }
}
