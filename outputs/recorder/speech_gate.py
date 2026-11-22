import threading
from typing import NamedTuple

from speech_audio import normalize_audio

_LOCK = threading.Lock()
_MODEL = None
_STRICT = dict(threshold=.7, min_speech_duration_ms=350, min_silence_duration_ms=300, speech_pad_ms=0)
_PADDED = dict(threshold=.45, min_speech_duration_ms=200, min_silence_duration_ms=700, speech_pad_ms=500)
_WEAK = dict(threshold=.55, min_speech_duration_ms=250, min_silence_duration_ms=300, speech_pad_ms=0)
_BRIEF = dict(threshold=.90, min_speech_duration_ms=96, min_silence_duration_ms=150, speech_pad_ms=0)
BRIEF_CONTEXT = .30


class SpeechProfile(NamedTuple):
    strict: list
    padded: list
    anchored: list
    brief: tuple = ()
    quiet: tuple = ()


def _probabilities(samples):
    global _MODEL
    import numpy as np
    values = np.asarray(samples)
    if values.ndim == 1 and not np.any(values):
        return []
    from vad_onnx import VoiceDetector
    audio = normalize_audio(samples)
    with _LOCK:
        if _MODEL is None:
            _MODEL = VoiceDetector()
        return _MODEL.audio_forward(audio).tolist()


def _ranges(probabilities, length, settings):
    if not len(probabilities):
        return []
    from vad_onnx import speech_intervals
    return speech_intervals(probabilities, length, **settings)


def _anchored(core, weak):
    selected = list(core)
    selected.extend((a, b) for a, b in weak if any(a < d+1.5 and b > c-1.5 for c, d in core))
    merged = []
    for a, b in sorted(selected):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def speech_profile(samples):
    probabilities = _probabilities(samples)
    length = len(samples)
    core = _ranges(probabilities, length, _STRICT)
    padded = _ranges(probabilities, length, _PADDED) if core else []
    anchored = _anchored(core, _ranges(probabilities, length, _WEAK)) if core else []
    brief = tuple((a, b) for a, b in _ranges(probabilities, length, _BRIEF)
                  if b - a <= .35 and not any(a <= d + .60 and b >= c - .60 for c, d in anchored))
    padded.extend((max(0, a - BRIEF_CONTEXT), min(length / 16000, b + BRIEF_CONTEXT)) for a, b in brief)
    quiet = () if anchored or brief else _quiet_ranges(samples, probabilities)
    return SpeechProfile(core, _anchored(padded, []) if brief else padded, anchored, brief, quiet)


def _quiet_ranges(samples, probabilities):
    peak = max(probabilities, default=0)
    if peak >= .5:
        gain, maximum_level = 4, .025
    elif peak >= .20 and any(first >= .20 and second >= .20 and third >= .20
                             for first, second, third in zip(probabilities, probabilities[1:], probabilities[2:])):
        gain, maximum_level = 16, .008
    else:
        return ()

    import numpy as np
    values = np.asarray(samples, dtype=np.float32)
    level = float(np.quantile(np.abs(values), .995))
    if not .001 <= level <= maximum_level:
        return ()
    return tuple(_ranges(_probabilities(values * gain), len(values), _STRICT))


def speech_ranges(samples):
    return _ranges(_probabilities(samples), len(samples), _PADDED)


def strict_speech_ranges(samples):
    return _ranges(_probabilities(samples), len(samples), _STRICT)


def anchored_speech_ranges(samples, core):
    if not core:
        return []
    return _anchored(core, _ranges(_probabilities(samples), len(samples), _WEAK))


def overlaps_speech(start,end,ranges):
 return sum(max(0,min(end,b)-max(start,a)) for a,b in ranges)>=min(.15,max(.05,(end-start)*.1))

def clips(ranges):return [v for pair in ranges for v in pair]


def supported_words(segment, ranges, strict_ranges=None):
 """Short stock decoder responses need confident words and unpadded speech."""
 import re
 words=segment.get('words',[])
 if words and sum(float(w.get('probability',0)) for w in words)/len(words)<.35:return False
 stock=bool(re.fullmatch(r'[\s.!?,…]*(?:спасибо|спасибо за внимание)[\s.!?,…]*',segment.get('text',''),re.I))
 if not stock:return True
 if not words or min(float(w.get('probability',0)) for w in words)<.9:return False
 start=min(w['start'] for w in words);end=max(w['end'] for w in words)
 core=ranges if strict_ranges is None else strict_ranges
 overlap=sum(max(0,min(end,b)-max(start,a)) for a,b in core)
 return end-start>=.2 and overlap>=max(.25,(end-start)*.6)
