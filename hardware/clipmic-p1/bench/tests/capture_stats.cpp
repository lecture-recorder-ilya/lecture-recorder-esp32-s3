#include "../src/capture_stats.h"
#include <cassert>

int main() {
  CaptureStats stats;
  assert(std::isinf(stats.rmsDbfs()) && stats.rmsDbfs() < 0);
  const int16_t tone[] = {-16384, 16384, -16384, 16384};
  stats.addPcm(tone, 4);
  assert(std::abs(stats.rmsDbfs() + 6.0206) < 0.0001);
  const int16_t rail[] = {-32768, 32767};
  stats.addPcm(rail, 2);
  assert(stats.peak == 32768 && stats.samples == 6 && stats.railSamples == 2);
  assert(stats.streamIntact());
  stats.addOverflow(512);
  stats.addOverflow(512);
  assert(!stats.streamIntact() && stats.lostSamplesMin == 512 && stats.overflowEvents == 2);
}
