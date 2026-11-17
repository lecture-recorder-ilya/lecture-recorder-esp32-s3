def normalize_audio(samples):
    import numpy as np
    audio = np.asarray(samples, dtype=np.float32).copy()
    if audio.ndim != 1:
        raise ValueError('Ожидается монофоническая запись.')
    if not audio.size:
        return audio
    np.nan_to_num(audio, copy=False, nan=0, posinf=0, neginf=0)
    level = float(np.quantile(np.abs(audio), .995))
    audio *= min(8.0, .8 / max(level, .001))
    return np.clip(audio, -1, 1, out=audio)


ENHANCEMENT = 'local-speech-v1'
PROFILES = {'gentle': .28, 'strong': .14}


def enhance_audio(samples, speech, profile='gentle', level=True):
    import numpy as np
    from scipy.ndimage import uniform_filter1d
    from scipy.signal import butter, istft, sosfiltfilt, stft

    if profile not in PROFILES:
        raise ValueError('Выбери бережную или усиленную очистку.')
    audio = np.asarray(samples, dtype=np.float32).copy()
    if audio.ndim != 1:
        raise ValueError('Ожидается монофоническая запись.')
    np.nan_to_num(audio, copy=False, nan=0, posinf=0, neginf=0)
    if len(audio) < 512 or not np.any(audio):
        return audio
    audio = sosfiltfilt(butter(2, 65, fs=16000, btype='highpass', output='sos'), audio).astype(np.float32)
    _, times, spectrum = stft(audio, fs=16000, nperseg=512, noverlap=384, boundary='zeros')
    voiced = np.zeros(len(times), dtype=bool)
    for start, end in speech:
        voiced |= (times >= max(0, start - .16)) & (times <= end + .16)
    power = np.abs(spectrum) ** 2
    quiet = (~voiced) & (times > .032) & (times < len(audio) / 16000 - .032)
    if np.count_nonzero(quiet) >= 25:
        noise = np.quantile(power[:, quiet], .5, axis=1)[:, None]
        smooth = uniform_filter1d(power, 5, axis=1, mode='nearest')
        gain = np.maximum(PROFILES[profile], np.sqrt(np.maximum(0, 1 - noise / np.maximum(smooth, 1e-18))))
        gain = uniform_filter1d(uniform_filter1d(gain, 3, axis=0, mode='nearest'), 5, axis=1, mode='nearest')
        spectrum *= gain
        _, restored = istft(spectrum, fs=16000, nperseg=512, noverlap=384, boundary=True)
        audio = restored[:len(audio)].astype(np.float32)
    if level and np.any(voiced):
        frames = np.minimum((times * 16000).astype(int), len(audio) - 1)
        energy = uniform_filter1d(audio.astype(np.float64) ** 2, 8000, mode='nearest')
        rms = np.sqrt(energy[frames])
        gains = np.ones(len(times))
        supported = voiced & (rms > .0005)
        gains[supported] = np.clip(.09 / np.maximum(rms[supported], .0005), .4, 6)
        gains = uniform_filter1d(gains, 125, mode='nearest')
        audio *= np.interp(np.arange(len(audio)), frames, gains).astype(np.float32)
    peak = float(np.max(np.abs(audio)))
    if peak > .96:
        audio *= .96 / peak
    return audio
