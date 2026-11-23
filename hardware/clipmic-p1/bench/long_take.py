"""Сформировать длинный эталон или проверить непрерывный дубль по семи меткам."""
import argparse
import hashlib
import json
import wave
from pathlib import Path

import numpy as np

from compare import band_rms, db, locate

RATE = 16000
STEP = 30
COUNT = 7


def marker(index, rate):
    t = np.arange(round(.32 * rate)) / rate
    f0, f1 = 630 + index * 137, 3100 - index * 91
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t**2 / .64)
    return .34 * np.sin(np.pi * t / .32)**2 * np.sin(phase)


def window(reader, start, end, channel):
    rate = reader.getframerate()
    a = max(0, round(start * rate))
    b = min(reader.getnframes(), round(end * rate))
    if b <= a:
        return np.empty(0)
    reader.setpos(a)
    data = np.frombuffer(reader.readframes(b - a), "<i2").reshape(-1, reader.getnchannels())
    if len(data) != b - a:
        raise ValueError("Неполный WAV")
    return data[:, channel - 1].astype(float) / 32768


def make(path, voice):
    source = voice or Path(__file__).with_name("reference.wav")
    with wave.open(str(source)) as reader:
        if reader.getparams()[:3] != (1, 2, RATE):
            raise ValueError("Для исходной речи нужен WAV PCM16 моно 16 кГц")
        if voice and reader.getnframes() < 6 * 26 * RATE:
            raise ValueError("Для свободной речи нужно хотя бы 156 с")
        speech = window(reader, 0, 156, 1) if voice else window(reader, 7, 22.25, 1)
    audio = np.zeros(183 * RATE)
    for i in range(COUNT):
        at = (1 + STEP * i) * RATE
        m = marker(i, RATE)
        audio[at:at + len(m)] = m
        if i < COUNT - 1:
            excerpt = (speech[i*26*RATE:(i+1)*26*RATE] if voice
                       else np.resize(speech, 26 * RATE))
            audio[at + 3*RATE:at + 29*RATE] = excerpt
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        writer.writeframes(np.rint(audio * 32768).astype("<i2").tobytes())
    print(hashlib.sha256(path.read_bytes()).hexdigest(), str(path))


def inspect(path, channel):
    blocks = []
    with wave.open(str(path)) as reader:
        rate = reader.getframerate()
        if not (reader.getsampwidth() == 2 and 8000 <= rate <= 96000 and
                1 <= channel <= reader.getnchannels()):
            raise ValueError("Нужен WAV PCM16, 8–96 кГц, существующий канал")
        anchors = []
        first = None
        for i in range(COUNT):
            start = max(0, first + i * STEP - 2) if i else 0
            stop = first + i * STEP + 2 if i else 12
            try:
                at, _ = locate(window(reader, start, stop, channel), marker(i, rate), rate)
                found = (round(start * rate) + at) / rate
            except ValueError:
                if i == 0:
                    raise ValueError("Начальная метка не найдена в первых 12 с")
                found = None
            if i == 0:
                first = found
            anchors.append(found)
        intervals = [None if a is None or b is None else b-a for a, b in zip(anchors, anchors[1:])]
        valid = [v for v in intervals if v is not None]
        typical = np.median(valid) if valid else None
        for i, interval in enumerate(intervals):
            if interval is None:
                blocks.append({"block": i+1, "missing_marker": True})
                continue
            def part(a, b):
                return window(reader, anchors[i] + a*interval/STEP,
                              anchors[i] + b*interval/STEP, channel)
            quiet = part(.6, 2.6)
            speech = part(3, 29)
            blocks.append({"block": i+1, "marker_interval_s": round(interval, 5),
                           "relative_timing_jump_ms": round((interval-typical)*1000, 2),
                           "background_band_dbfs": db(band_rms(quiet, rate)),
                           "speech_band_dbfs": db(band_rms(speech, rate)),
                           "peak_dbfs": db(np.max(abs(speech))),
                           "rail_samples": int(np.count_nonzero((speech == -1) | (speech == 32767/32768)))})
    return {"file": str(path), "channel": channel, "markers_s": anchors, "blocks": blocks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest="cmd", required=True)
    gen = cmd.add_parser("make")
    gen.add_argument("output", type=Path)
    gen.add_argument("--voice", type=Path)
    check = cmd.add_parser("inspect")
    check.add_argument("input", type=Path)
    check.add_argument("--channel", type=int, default=1)
    args = parser.parse_args()
    if args.cmd == "make":
        make(args.output, args.voice)
    else:
        print(json.dumps(inspect(args.input, args.channel), ensure_ascii=False, indent=2))
