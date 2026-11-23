"""Сопоставление пары синхронных записей reference.wav по двум акустическим меткам."""
import argparse
import hashlib
import json
import math
import wave
from pathlib import Path

import numpy as np


def read_pcm(path, channel):
    with wave.open(str(path)) as src:
        if src.getsampwidth() != 2 or src.getcomptype() != "NONE":
            raise ValueError(f"{path}: нужен WAV PCM16")
        if not 1 <= channel <= src.getnchannels():
            raise ValueError(f"{path}: нет канала {channel}")
        rate = src.getframerate()
        if not 8000 <= rate <= 96000:
            raise ValueError(f"{path}: частота вне диапазона 8–96 кГц")
        if src.getnframes() > 120 * rate:
            raise ValueError(f"{path}: оставьте один дубль продолжительностью до 120 с")
        raw = src.readframes(src.getnframes())
        if len(raw) != src.getnframes() * 2 * src.getnchannels():
            raise ValueError(f"{path}: неполный WAV")
        frames = np.frombuffer(raw, "<i2").reshape(-1, src.getnchannels())
        return frames[:, channel - 1].astype(float) / 32768.0, rate


def locate(signal, marker, rate):
    size = len(marker)
    if len(signal) < size:
        raise ValueError("Слишком короткая запись")
    nfft = 1 << (len(signal) + size - 2).bit_length()
    product = np.fft.rfft(signal, nfft) * np.fft.rfft(marker[::-1], nfft)
    cov = np.fft.irfft(product, nfft)[size - 1:len(signal)]
    energy = np.r_[0, np.cumsum(signal * signal)]
    denom = np.sqrt(np.maximum(energy[size:] - energy[:-size], 0) * (marker @ marker))
    scores = np.abs(cov) / np.maximum(denom, 1e-9)
    idx = int(np.argmax(scores))
    best = float(scores[idx])
    scores[max(0, idx - rate // 2):idx + rate // 2 + 1] = 0
    if best < 0.22 or best < 1.5 * float(scores.max()):
        raise ValueError("Слабая или неоднозначная метка. Просмотрите запись и повторите дубль")
    return idx, round(best, 3)


def band_rms(samples, rate):
    spectrum = np.fft.rfft(samples)
    frequencies = np.fft.rfftfreq(len(samples), 1 / rate)
    selected = (frequencies >= 300) & (frequencies <= 4000) & (frequencies < rate / 2)
    return math.sqrt(2 * np.sum(abs(spectrum[selected]) ** 2)) / len(samples)


def db(value):
    return round(20 * math.log10(value), 2) if value > 0 else None


def measure(path, channel, master, master_rate):
    data, rate = read_pcm(path, channel)
    markers = []
    for start in (1, 25):
        original = master[start*master_rate:start*master_rate+round(.32*master_rate)]
        marker = np.interp(np.arange(round(.32*rate)) * master_rate / rate,
                           np.arange(len(original)), original)
        markers.append(locate(data, marker, rate))
    a, b = (m[0] for m in markers)
    scale = (b - a) / (24 * rate)
    if abs(scale-1) > .005:
        raise ValueError("Интервал между метками отличается от 24 с более чем на 0,5%")
    def window(start, stop):
        i, j = (a + round((t - 1) * scale * rate) for t in (start, stop))
        return data[i:j]
    speech = window(7, 22.25)
    quiet = window(3, 6)
    speech_rms, quiet_rms = (band_rms(x, rate) for x in (speech, quiet))
    return {
        "file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "channel": channel, "sample_rate_hz": rate, "marker_times_s": [round(i/rate, 4) for i, _ in markers],
        "marker_correlations": [score for _, score in markers],
        "speech_band_dbfs": db(speech_rms), "background_band_dbfs": db(quiet_rms),
        "speech_plus_noise_over_background_db": db(speech_rms / quiet_rms) if quiet_rms else None,
        "speech_peak_dbfs": db(float(np.max(abs(speech)))),
        "speech_rail_samples": int(np.count_nonzero((speech == -1) | (speech == 32767/32768))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('clip', type=Path)
    parser.add_argument('phone', type=Path)
    parser.add_argument('--reference', type=Path, default=Path(__file__).with_name('reference.wav'),
                        help='Локальный эталон с двумя синхрометками')
    parser.add_argument('--distance', type=int, choices=[1, 3, 5], required=True)
    parser.add_argument('--phone-channel', type=int, default=1)
    args = parser.parse_args()
    try:
        master, fs = read_pcm(args.reference, 1)
        clip = measure(args.clip, 1, master, fs)
        phone = measure(args.phone, args.phone_channel, master, fs)
    except (ValueError, wave.Error, OSError, EOFError) as error:
        parser.exit(2, f"Дубль не обработан: {error}\n")
    print(json.dumps({"distance_m": args.distance, "ClipMic": clip, "phone": phone},
                     ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
