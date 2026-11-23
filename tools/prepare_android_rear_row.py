"""Freeze disjoint Android ASR tuning/control sets from existing local corpora.

mTEDx is split by talk (first talk for tuning, other two for control); FLEURS
37–42 vs 43–48 by source sentence. Quiet copies only attenuate PCM by 30 dB;
they do not simulate microphone distance. Original room-6db copies already
contain synthetic noise/reflections. No speech audio is downloaded or committed.
"""
import argparse
import json
from pathlib import Path
import wave

import numpy as np

from evaluate_asr import audio_sha256


def write_wave(path, samples):
    with wave.open(str(path), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(np.round(np.clip(samples, -1, 32767/32768)*32768).astype('<i2').tobytes())


def prepare(args):
    if args.output.exists():
        raise ValueError('Use a new corpus directory to preserve the frozen split.')
    args.output.mkdir(parents=True)
    sets = {'tune': [], 'control': []}
    for corpus, manifest in (('mtedx', args.mtedx), ('fleurs', args.fleurs)):
        for row in json.loads(manifest.read_text()):
            if not row['reference']:
                continue
            path = (manifest.parent / row['audio']).resolve()
            sha = audio_sha256(path)
            if row.get('audio_sha256', sha) != sha:
                raise ValueError(f"{row['id']}: changed source audio")
            if corpus == 'mtedx':
                split = 'tune' if row['id'].startswith('6hoeGxsHS6c_') else 'control'
                subset = 'mtedx-original'
            else:
                split = 'tune' if int(row['id'].split('-')[1]) <= 42 else 'control'
                subset = 'fleurs-' + row['subset']
            base = dict(row, id=corpus+'-'+row['id'], audio=str(path),
                        subset=subset, audio_sha256=sha)
            sets[split].append(base)
            if corpus == 'mtedx' or row['subset'] == 'clean':
                with wave.open(str(path)) as stream:
                    if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
                        raise ValueError('Expected PCM16 mono 16 kHz WAV')
                    signal = np.frombuffer(stream.readframes(stream.getnframes()), '<i2') / 32768
                quiet = args.output / (base['id']+'-quiet.wav')
                write_wave(quiet, signal * 10**(-30/20))
                sets[split].append(dict(base, id=base['id']+'-quiet', audio=quiet.name,
                                        subset=corpus+'-quiet-minus30db',
                                        audio_sha256=audio_sha256(quiet),
                                        attenuation_db=-30, parent_audio_sha256=sha,
                                        synthetic_transform=True))
    for split, rows in sets.items():
        rng = np.random.default_rng(174 if split == 'tune' else 175)
        n = 8*16000
        t = np.arange(n)/16000
        white = rng.normal(0, .01, n)
        clicks = np.zeros(n)
        clicks[rng.choice(n, 16, replace=False)] = rng.uniform(-.7, .7, 16)
        signals = {'silence': np.zeros(n), 'noise': white,
                   'hum': .02*np.sin(2*np.pi*50*t)+.003*rng.normal(size=n), 'clicks': clicks}
        for label, signal in signals.items():
            path = args.output/(split+'-'+label+'.wav')
            write_wave(path, signal)
            rows.append(dict(id=split+'-'+label, audio=path.name, reference='',
                             subset='no-speech', synthetic=True, audio_sha256=audio_sha256(path)))
        (args.output/(split+'.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
    rng = np.random.default_rng(901)
    white = rng.normal(size=8*16000)
    frequency = np.fft.rfftfreq(len(white), 1/16000)
    fan = np.fft.irfft(np.fft.rfft(white)/(1+1j*frequency/250), n=len(white))
    probes = []
    for label, background in (('white', white), ('fan', fan)):
        background = background / np.sqrt(np.mean(background**2))
        for amplitude in (.0003, .001, .003, .01):
            ident = f'probe-{label}-{amplitude}'
            path = args.output/(ident+'.wav')
            write_wave(path, background*amplitude)
            probes.append(dict(id=ident, audio=path.name, reference='', subset='noise-probes',
                               synthetic=True, audio_sha256=audio_sha256(path)))
    (args.output/'noise-probes.json').write_text(json.dumps(probes, ensure_ascii=False, indent=2)+'\n')
    (args.output/'provenance.json').write_text(json.dumps(dict(
        split_rule=__doc__, numpy=np.__version__, script_sha256=audio_sha256(Path(__file__)),
        sources={str(path.resolve()): audio_sha256(path) for path in (args.mtedx, args.fleurs)},
        manifests={name: audio_sha256(args.output/(name+'.json')) for name in sets}),
        ensure_ascii=False, indent=2)+'\n')
    print({name: len(rows) for name, rows in sets.items()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mtedx', type=Path, required=True)
    parser.add_argument('--fleurs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args())
