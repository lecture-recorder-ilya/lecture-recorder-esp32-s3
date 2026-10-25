import argparse
import json
import subprocess
import wave
from pathlib import Path

REFERENCE = ('Если функция непрерывна на отрезке, то она достигает своего наибольшего и наименьшего значения. '
             'Это теорема Вейерштрасса. Не путайте необходимое условие с достаточным. '
             'На следующую пару решите задачи пять и шесть.')


def make_fixture(output):
    import numpy as np
    if output.exists() and any(output.iterdir()):
        raise ValueError('Выбери новую или пустую папку для контрольных файлов.')
    output.mkdir(parents=True, exist_ok=True)
    (output/'reference.txt').write_text(REFERENCE+'\n')
    subprocess.run(['/usr/bin/say', '-v', 'Milena', '-r', '155', '-o', str(output/'source.aiff'),
                    '-f', str(output/'reference.txt')], check=True)
    subprocess.run(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16@16000', '-c', '1',
                    str(output/'source.aiff'), str(output/'source.wav')], check=True)
    with wave.open(str(output/'source.wav')) as stream:
        audio = np.frombuffer(stream.readframes(stream.getnframes()), dtype='<i2').astype(np.float32)/32768
    rng = np.random.default_rng(20261025)
    variants = dict(clean=audio, quiet_click=audio*.02, quiet_noise=audio*.09+rng.normal(0, .002, len(audio)),
                    noise=rng.normal(0, .003, 12*16000), silence=np.zeros(12*16000))
    variants['quiet_click'] = variants['quiet_click'].copy()
    variants['quiet_click'][1600] = .99
    frames = audio[:len(audio)//2//800*800].reshape(-1, 800)
    rms = np.sqrt(np.mean(frames*frames, axis=1))
    gap = int(np.argmin(rms[len(rms)//2:])+len(rms)//2)*800
    variants['pause'] = np.concatenate((audio[:gap], np.zeros(4*16000), audio[gap:]))
    manifest = []
    for name, samples in variants.items():
        path = output/(name+'.wav')
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'none'))
            stream.writeframes((np.clip(samples, -1, 1)*32767).astype('<i2').tobytes())
        manifest.append(dict(id=name, audio=path.name, reference='' if name in ('noise', 'silence') else REFERENCE,
                             terms=['Вейерштрасса'], synthetic=True))
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Контрольные записи для распознавания: голос, пауза, тихая речь, шум.')
    parser.add_argument('output', type=Path)
    make_fixture(parser.parse_args().output)
