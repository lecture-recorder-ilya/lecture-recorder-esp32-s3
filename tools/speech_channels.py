import math


def choose_speech_channel(samples, speech_ranges=None):
    import numpy as np
    data = np.asarray(samples)
    if data.ndim == 1 or data.ndim == 2 and data.shape[1] == 1:
        return None, dict(mode='mono', changed=False)
    if data.ndim != 2 or data.shape[1] != 2 or not len(data):
        raise ValueError('Для выбора нужны два непустых PCM-канала.')
    if speech_ranges is None:
        from speech_gate import strict_speech_ranges
        speech_ranges = strict_speech_ranges
    normalized = data.astype(np.float64)
    if data.dtype.kind in 'iu':
        if data.dtype != np.int16:
            raise ValueError('Целочисленный PCM должен быть signed int16.')
        normalized /= 32768
    if not np.isfinite(normalized).all():
        raise ValueError('В PCM есть нечисловые значения.')
    metrics = []
    for channel in range(2):
        signal = normalized[:, channel]
        if float(np.ptp(signal)) <= 1/32768:
            metrics.append(dict(voice_seconds=0, clipped_fraction=0, snr_db=0, score=0))
            continue
        ranges = speech_ranges(signal.astype(np.float32))
        mask = np.zeros(len(signal), dtype=bool)
        for start, end in ranges:
            mask[max(0, int(start*16000)):min(len(signal), int(end*16000))] = True
        duration = float(np.sum(mask)/16000)
        clipped = float(np.mean(np.abs(signal) >= .98))
        quiet = signal[~mask]
        noise_power = float(np.mean(quiet**2)) if len(quiet) >= 800 else float(np.quantile(signal**2, .2))
        voice_power = float(np.mean(signal[mask]**2)) if mask.any() else 0
        snr = 10*math.log10(max(voice_power, 1e-12)/max(noise_power, 1e-12))
        clarity = .5+.5*max(0, min(1, snr/20))
        score = duration*clarity*max(0, 1-8*clipped)
        metrics.append(dict(voice_seconds=duration, clipped_fraction=clipped, snr_db=snr, score=score))
    scores = [m['score'] for m in metrics]
    best = int(scores[1] > scores[0])
    correlation = float(np.corrcoef(normalized.T)[0, 1]) if np.min(np.std(normalized, axis=0)) > 1e-9 else 0
    anti_phase = correlation < -.8 and min(m['voice_seconds'] for m in metrics) > .15
    decisive = scores[best] > max(.15, scores[1-best]*1.25)
    choice = best if anti_phase or decisive else None
    return choice, dict(mode='channel' if choice is not None else 'existing_downmix',
                        selected=choice, correlation=correlation, anti_phase=anti_phase, channels=metrics,
                        note='Качество речи не определяет, какой из разных говорящих является преподавателем.')
