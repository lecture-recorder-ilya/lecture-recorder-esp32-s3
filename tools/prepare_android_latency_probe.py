"""Сделать проверяемые тишину перед речью и стационарный фон без речи."""
import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import sys
import wave


def prepare(source, reference, output):
    output.mkdir(parents=True)
    with wave.open(str(source)) as stream:
        if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
            raise ValueError('Нужен PCM16 mono 16 кГц')
        speech = stream.readframes(stream.getnframes())
    rows = []

    def save(name, pcm, text):
        path = output / (name + '.wav')
        with wave.open(str(path), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(pcm)
        rows.append(dict(id=name, audio=str(path.resolve()), reference=text,
                         subset='synthetic-latency-probe',
                         audio_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))

    save('silence-20.3-before-speech', bytes(round(20.3*16000)*2)+speech, reference)
    save('digital-silence', bytes(8*16000*2), '')
    save('constant-dc', array('h', [100]*8*16000).tobytes(), '')
    for amplitude in (100, 1600):
        pcm = array('h', (round(amplitude*math.sin(2*math.pi*100*i/16000)) for i in range(8*16000)))
        if sys.byteorder != 'little':
            pcm.byteswap()
        save('steady-hum-'+str(amplitude), pcm.tobytes(), '')
    (output/'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.source, args.reference, args.output)
