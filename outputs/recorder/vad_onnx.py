from importlib.metadata import distribution

import numpy as np


FRAME = 512
CONTEXT = 64
BLOCK = FRAME * 512
RATE = 16000


class VoiceDetector:
    def __init__(self):
        import onnxruntime as ort

        path = distribution('silero-vad').locate_file('silero_vad/data/silero_vad_16k_sequence.onnx')
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(str(path), sess_options=options, providers=['CPUExecutionProvider'])

    def audio_forward(self, samples):
        hidden = np.zeros((1, 1, 128), dtype=np.float32)
        cell = np.zeros_like(hidden)
        probabilities = []
        for start in range(0, len(samples), BLOCK):
            end = min(start + BLOCK, len(samples))
            block = samples[max(0, start - CONTEXT):end]
            prefix, suffix = (0 if start else CONTEXT), -end % FRAME
            if prefix or suffix:
                block = np.pad(block, (prefix, suffix))
            frames = np.lib.stride_tricks.sliding_window_view(block, FRAME + CONTEXT)[::FRAME]
            scores, hidden, cell = self.session.run(
                ['speech_probs', 'hn', 'cn'],
                {'input': np.ascontiguousarray(frames), 'h': hidden, 'c': cell},
            )
            probabilities.append(scores.reshape(-1))
        return np.concatenate(probabilities) if probabilities else np.empty(0, dtype=np.float32)


def speech_intervals(probabilities, length, threshold, min_speech_duration_ms, min_silence_duration_ms, speech_pad_ms):
    minimum = RATE * min_speech_duration_ms / 1000
    silence = RATE * min_silence_duration_ms / 1000
    pad = RATE * speech_pad_ms // 1000
    release = max(threshold - .15, .01)
    ranges = []
    start = quiet = None
    for frame, probability in enumerate(probabilities):
        position = frame * FRAME
        if probability >= threshold:
            quiet = None
            if start is None:
                start = position
        elif start is not None and probability < release:
            if quiet is None:
                quiet = position
            if position - quiet >= silence:
                if quiet - start > minimum:
                    ranges.append([start, quiet])
                start = quiet = None
    if start is not None and length - start > minimum:
        ranges.append([start, length])
    if ranges and pad:
        ranges[0][0] = max(0, ranges[0][0] - pad)
        for previous, following in zip(ranges, ranges[1:]):
            side = min(pad, (following[0] - previous[1]) // 2)
            previous[1] += side
            following[0] -= side
        ranges[-1][1] = min(length, ranges[-1][1] + pad)
    return [(left / RATE, right / RATE) for left, right in ranges]
