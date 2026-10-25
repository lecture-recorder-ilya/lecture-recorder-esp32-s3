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
