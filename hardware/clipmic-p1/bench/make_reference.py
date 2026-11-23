"""Собрать 27-секундную фонограмму стенда из фиксированной записи FLEURS."""
import argparse
import hashlib
import wave
from pathlib import Path

import numpy as np

from long_take import RATE, marker

CLEAN_SHA256 = "fd9ae27c10c25e9d7814321bfaffbe5400ad46106510ad8b8f6421b6d60dc891"


def make(source, output):
    if hashlib.sha256(source.read_bytes()).hexdigest() != CLEAN_SHA256:
        raise ValueError("Контрольная сумма источника не совпала с fleurs-37-clean.wav")
    with wave.open(str(source), "rb") as audio:
        if audio.getparams()[:3] != (1, 2, RATE):
            raise ValueError("Ожидается моно PCM16 16 кГц")
        speech = np.frombuffer(audio.readframes(audio.getnframes()), "<i2").astype(np.float64)
    result = np.zeros(27 * RATE)
    speech *= 0.5 / np.max(np.abs(speech))
    start = 7 * RATE
    result[start:start + len(speech)] = speech
    for index, seconds in ((0, 1), (5, 25)):
        chirp = marker(index, RATE)
        result[seconds * RATE:seconds * RATE + len(chirp)] = chirp
    with wave.open(str(output), "wb") as audio:
        audio.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        audio.writeframes(np.rint(result * 32768).astype("<i2").tobytes())
    return hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(make(args.source, args.output))
