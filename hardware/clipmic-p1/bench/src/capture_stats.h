#pragma once
#include <cmath>
#include <cstddef>
#include <cstdint>

struct CaptureStats {
  uint32_t samples = 0;
  uint64_t sumSquares = 0;
  int32_t peak = 0;
  uint32_t railSamples = 0;
  uint32_t overflowEvents = 0;
  uint32_t lostSamplesMin = 0;
  uint32_t dmaErrors = 0;
  bool eventQueueFull = false;

  void addPcm(const int16_t* pcm, size_t count) {
    for (size_t i = 0; i < count; ++i) {
      int32_t value = pcm[i];
      int32_t magnitude = value < 0 ? -value : value;
      if (magnitude > peak) peak = magnitude;
      sumSquares += static_cast<uint64_t>(value * value);
      if (value == INT16_MIN || value == INT16_MAX) ++railSamples;
    }
    samples += count;
  }

  void addOverflow(size_t dmaBytes) {
    ++overflowEvents;
    lostSamplesMin += dmaBytes / sizeof(int16_t);
  }

  double rmsDbfs() const {
    if (!sumSquares || !samples) return -INFINITY;
    return 10 * std::log10(static_cast<double>(sumSquares) / samples / (32768.0 * 32768.0));
  }

  bool streamIntact() const {
    return !overflowEvents && !dmaErrors && !eventQueueFull;
  }
};
