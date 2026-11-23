"""Проверить текущий импорт Mac против отдельного выбора речевого канала."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import wave

import numpy as np
from scipy.signal import lfilter

from evaluate_asr import audio_sha256
from prepare_asr_factors import read, write, rms


def run(args):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/'outputs/recorder'))
    from audio_import import normalize
    from speech_channels import choose_speech_channel
    if args.output.exists():
        raise ValueError('Укажи новую папку.')
    args.output.mkdir(parents=True)
    source = json.loads(args.manifest.read_text())
    cases, proof = [], []
    for number, name in enumerate(args.ids):
        row = next(r for r in source if r['id'] == name)
        signal = read((args.manifest.parent/row['audio']).resolve())
        rng = np.random.default_rng(8810+number)
        fan = lfilter([1], [1, -.9], rng.normal(size=len(signal)))
        fan *= rms(signal)/rms(fan)
        broken = np.clip(signal*50, -1, 32767/32768)
        variants = {
            'remote_noise': np.column_stack([signal, signal*.15+fan]),
            'right_loud_noise': np.column_stack([signal, signal*.15+3*fan]),
            'left_loud_noise': np.column_stack([signal*.15+3*fan, signal]),
            'right_clipped': np.column_stack([signal, broken]),
            'left_clipped': np.column_stack([broken, signal]),
            'opposite_phase': np.column_stack([signal, -signal]),
            'left_silent': np.column_stack([np.zeros_like(signal), signal]),
            'same_channels': np.column_stack([signal, signal]),
            'mono': signal,
        }
        for kind, channels in variants.items():
            ident = f'stereo-{number}-{kind}'
            original = args.output/(ident+'-input.wav')
            pcm = np.round(np.clip(channels, -1, 32767/32768)*32768).astype('<i2')
            with wave.open(str(original), 'wb') as stream:
                stream.setparams((1 if pcm.ndim == 1 else 2, 2, 16000, 0, 'NONE', 'not compressed'))
                stream.writeframes(pcm.tobytes())
            before = pcm.copy()
            choice, metrics = choose_speech_channel(pcm)
            if not np.array_equal(before, pcm):
                raise ValueError('Выбор изменил входной PCM.')
            downmix = args.output/(ident+'-downmix.wav')
            selected = args.output/(ident+'-selected.wav')
            normalize(original, downmix, root)
            if choice is None:
                shutil.copyfile(downmix, selected)
            else:
                with wave.open(str(selected), 'wb') as stream:
                    stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                    stream.writeframes(pcm[:, choice].tobytes())
            same = audio_sha256(downmix) == audio_sha256(selected)
            if kind == 'mono' and not same:
                raise ValueError('Изменился импорт моно.')
            for label, path in (('downmix', downmix), ('selected', selected)):
                cases.append(dict(id=ident+'-'+label, audio=str(path.resolve()), reference=row['reference'],
                                  audio_sha256=audio_sha256(path), subset=kind+'-'+label,
                                  source_audio_sha256=audio_sha256(original)))
            proof.append(dict(id=ident, input=str(original.resolve()), input_sha256=audio_sha256(original),
                              selected=choice, metrics=metrics, mono_or_fallback_byte_identical=same,
                              baseline_sha256=audio_sha256(downmix), candidate_sha256=audio_sha256(selected)))
    (args.output/'manifest.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (args.output/'probe.json').write_text(json.dumps(dict(cases=proof,
        importer_sha256=audio_sha256(root/'outputs/recorder/audio_import.py'),
        selector_sha256=audio_sha256(root/'tools/speech_channels.py'),
        integration='Отдельный адаптер PCM16 16кГц. Текущий audio_import.normalize не изменён. Для None используется его результат без изменений.'), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--ids', nargs=2, required=True)
    parser.add_argument('--output', type=Path, required=True)
    run(parser.parse_args())
