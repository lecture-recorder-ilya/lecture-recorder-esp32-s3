"""Поставить записанные короткие слова около стыка Android-окон; PCM речи неизменён."""
import argparse
import hashlib
import json
from pathlib import Path
import wave

RATE=16000
SOURCES={'не':'CPci7a8l-oU_0101-не-isolated',
         'три':'cPhc8OVB2Rk_0078-три-isolated',
         'да':'6hoeGxsHS6c_0000-да-isolated'}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    with wave.open(str(path)) as stream:
        if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate())!=(1,2,RATE):
            raise ValueError('Нужен PCM16 mono 16 кГц')
        return stream.readframes(stream.getnframes())


def prepare(args):
    args.output.mkdir(parents=True)
    index={r['id']:r for r in json.loads(args.short_manifest.read_text())}
    phrase=read(args.context)
    rows=[]
    for target,source_id in SOURCES.items():
        source=index[source_id];path=(args.short_manifest.parent/source['audio']).resolve()
        if sha(path)!=source['audio_sha256']:raise ValueError('Изменилась вырезка')
        word=read(path)
        for position in (17.72,18.04,18.36):
            for context in (False,True):
                pcm=bytearray(25*RATE*2)
                start=round(position*RATE)*2;pcm[start:start+len(word)]=word
                if context:pcm[RATE*2:RATE*2+len(phrase)]=phrase
                name=target+'-'+str(position)+('-context' if context else '-alone')
                output=args.output/(name+'.wav')
                with wave.open(str(output),'wb') as stream:
                    stream.setparams((1,2,RATE,0,'NONE','not compressed'));stream.writeframes(pcm)
                rows.append(dict(id=name,audio=str(output.resolve()),audio_sha256=sha(output),
                                 reference=((args.reference+' ') if context else '')+target,
                                 subset='seam-context' if context else 'seam-alone',target=target,
                                 position_seconds=position,source_id=source_id,
                                 source_audio_sha256=source['audio_sha256'],
                                 synthetic_speech=False,synthetic_layout=True))
    (args.output/'manifest.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    proof=dict(script_sha256=sha(Path(__file__)),source_manifest_sha256=sha(args.short_manifest),
               context_sha256=sha(args.context),expected='Каждый целевой ответ один раз; без новых слов на тишине',
               limits='Вырезки с автоматической разметкой из живой речи, искусственные паузы и расположение около 18 с')
    (args.output/'plan.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('short_manifest',type=Path);parser.add_argument('--context',type=Path,required=True)
    parser.add_argument('--reference',required=True);parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args())
