"""Изолировать пять причин повреждения речи на известных WAV; исходники не меняются."""
import argparse
import json
from pathlib import Path
import wave

import numpy as np
from scipy.signal import fftconvolve, lfilter

from evaluate_asr import audio_sha256


def read(path):
    with wave.open(str(path)) as stream:
        if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
            raise ValueError('Нужен PCM16 mono 16 кГц.')
        return np.frombuffer(stream.readframes(stream.getnframes()), '<i2').astype(np.float64)/32768


def write(path, signal):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.round(np.clip(signal, -1, 32767/32768)*32768).astype('<i2').tobytes())


def rms(signal):
    return float(np.sqrt(np.mean(signal**2)))


def prepare(args):
    if args.output.exists():
        raise ValueError('Укажи новую папку.')
    args.output.mkdir(parents=True)
    source = json.loads(args.manifest.read_text())
    selected = [next(row for row in source if row['id'] == name) for name in args.ids]
    distractor = read(args.distractor)
    manifest, pairs = [], []
    for number, row in enumerate(selected):
        original = (args.manifest.parent/row['audio']).resolve()
        if audio_sha256(original) != row['audio_sha256']:
            raise ValueError('Изменился исходный WAV.')
        signal = read(original)
        parent = dict(row, id=f'source-{number}', audio=str(original), subset='original')
        manifest.append(parent)
        rng = np.random.default_rng(90110+number)
        taps = np.zeros(6561)
        taps[[0, 720, 1760, 2960, 4320, 6560]] = [1, .75, -.58, .45, -.33, .22]
        reflected = fftconvolve(signal, taps)/np.sqrt(np.sum(taps**2))
        if np.max(np.abs(reflected)) > .95:
            reflected *= .95/np.max(np.abs(reflected))
        background = lfilter([1], [1, -.92], rng.normal(size=len(signal)))
        background *= rms(signal)/rms(background)
        noisy = signal+background
        noisy *= min(1, .95/np.max(np.abs(noisy)))
        gain = 1/max(float(np.quantile(np.abs(signal), .8)), 1e-5)
        clipped = np.clip(signal*gain, -1, 32767/32768)
        other = np.resize(distractor, len(signal))
        other *= rms(signal)/max(rms(other), 1e-12)
        overlap = signal+other
        overlap *= min(1, .95/np.max(np.abs(overlap)))
        factors = [
            ('weak', signal*10**(-36/20), {'attenuation_db': -36}),
            ('reflections', reflected, {'impulse_taps_samples': [0, 720, 1760, 2960, 4320, 6560], 'added_noise': False}),
            ('background', noisy, {'snr_db_before_common_scaling': 0, 'seed': 90110+number}),
            ('clipping', clipped, {'gain': gain, 'clipped_fraction': float(np.mean(np.abs(signal*gain)>=1))}),
            ('overlap', overlap, {'target_to_distractor_db': 0, 'distractor_sha256': audio_sha256(args.distractor)}),
        ]
        for factor, sound, parameters in factors:
            ident = f'source-{number}-{factor}'
            path = args.output/(ident+'.wav')
            write(path, sound)
            manifest.append(dict(parent, id=ident, audio=str(path.resolve()), subset=factor,
                                 audio_sha256=audio_sha256(path), synthetic_transform=True,
                                 parent_audio_sha256=row['audio_sha256']))
            pairs.append(dict(factor=factor, original=str(original), original_sha256=row['audio_sha256'],
                              modified=str(path.resolve()), modified_sha256=audio_sha256(path),
                              reference=row['reference'], parameters=parameters,
                              original_rms=rms(signal), modified_rms=rms(read(path))))
    (args.output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    (args.output/'pairs.json').write_text(json.dumps(dict(pairs=pairs, script_sha256=audio_sha256(Path(__file__)),
        note='Повреждения смоделированы отдельно. В наложении эталон относится к выбранному основному голосу; слова второго голоса считаются вставками.'), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--ids', nargs=2, required=True)
    parser.add_argument('--distractor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args())
