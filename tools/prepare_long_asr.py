"""Собрать непрерывные WAV из полных дорожек mTEDx и исходных VTT."""

import argparse
import hashlib
import html
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import wave

from evaluate_asr import audio_sha256, tokens
from prepare_asr_qa import save
from prepare_mtedx_asr import NON_SPEECH, decode


ARCHIVE = 'https://openslr.elda.org/resources/100/mtedx_ru-en.tgz'
PATH = re.compile(r'ru-en/data/train/(?:(?:wav/([\w-]+)\.flac)|(?:vtt/([\w-]+)\.ru\.vtt))$')
TIMING = re.compile(r'(?m)^([\d:.]+)\s+-->\s+([\d:.]+)[^\n]*\n')
MARKUP = re.compile(r'<[^>]*>')
SPEECH_RATE = 16000


def seconds(value):
    total = 0.0
    for part in value.split(':'):
        total = total * 60 + float(part)
    return total


def parse_vtt(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        match = TIMING.search(block)
        if match is None:
            continue
        start, end = map(seconds, match.groups())
        plain = html.unescape(MARKUP.sub('', block[match.end():]))
        plain = ' '.join(NON_SPEECH.sub('', plain).split())
        if end <= start:
            raise ValueError('Обратный или пустой интервал WebVTT.')
        cues.append(dict(start=start, end=end, text=plain))
    return sorted(cues, key=lambda cue: (cue['start'], cue['end']))


def caption_coverage(cues, start):
    seconds_covered, cursor = 0.0, start
    for cue in cues:
        if cue['text']:
            seconds_covered += max(0.0, cue['end'] - max(cursor, cue['start']))
            cursor = max(cursor, cue['end'])
    return seconds_covered


def continuous_window(cues):
    """Pick a 120–150 s window by cue boundaries before seeing hypotheses."""
    for i, first in enumerate(cues[:-1]):
        start = first['start']
        if start < 15 or not first['text'] or (i and cues[i-1]['end'] > start):
            continue
        end = start
        for j in range(i, len(cues) - 1):
            end = max(end, cues[j]['end'])
            duration = end - start
            if duration > 150:
                break
            if duration < 120 or cues[j+1]['start'] < end:
                continue
            group = cues[i:j+1]
            if caption_coverage(group, start) >= .80 * duration:
                return group, start, end
    return None


def cut(full, target, start, end):
    begin, finish = round(start * SPEECH_RATE), round(end * SPEECH_RATE)
    with wave.open(str(full)) as source:
        if not 0 <= begin < finish <= source.getnframes():
            raise ValueError('Интервал субтитров выходит за границы полной дорожки.')
        source.setpos(begin)
        samples = source.readframes(finish - begin)
    with wave.open(str(target), 'wb') as result:
        result.setparams((1, 2, SPEECH_RATE, 0, 'NONE', 'not compressed'))
        result.writeframes(samples)


def lecture_case(ident, vtt, payload, output, scratch, window, all_cues=None):
    full = scratch / 'full.wav'
    decode(payload, scratch, full)
    target = output / f'mtedx-{ident}.wav'
    with wave.open(str(full)) as source:
        full_seconds = source.getnframes() / SPEECH_RATE
    if all_cues is None:
        cues, start, end = window
        cut(full, target, start, end)
    else:
        cues, start, end = all_cues, 0.0, full_seconds
        shutil.copyfile(full, target)
    full.unlink()
    useful = [cue for cue in cues if tokens(cue['text'])]
    return dict(id=f'mtedx-{ident}', source_id=ident, lecture_id=ident, source_split='mTEDx ru-en train',
                source_video=f'https://www.youtube.com/watch?v={ident}', source_archive=ARCHIVE,
                clip_start=start, clip_end=end, full_seconds=round(full_seconds, 3),
                source_audio_sha256=hashlib.sha256(payload).hexdigest(),
                source_vtt_sha256=hashlib.sha256(vtt).hexdigest(), audio=target.name,
                audio_sha256=audio_sha256(target), reference_type='subtitles',
                reference=' '.join(cue['text'] for cue in useful), cues=useful)


def prepare(archive_path, output, count, full=False):
    output.mkdir(parents=True, exist_ok=False)
    subtitles, cases = {}, []
    with tempfile.TemporaryDirectory() as temp, tarfile.open(archive_path, 'r|gz') as archive:
        for member in archive:
            match = PATH.fullmatch(member.name)
            if not member.isfile() or match is None:
                continue
            audio_id, vtt_id = match.groups()
            if vtt_id:
                subtitles[vtt_id] = archive.extractfile(member).read()
                continue
            if audio_id not in subtitles:
                continue
            vtt = subtitles[audio_id]
            cues = parse_vtt(vtt.decode('utf-8-sig'))
            selected = continuous_window(cues)
            if selected is None:
                continue
            payload = archive.extractfile(member).read()
            cases.append(lecture_case(audio_id, vtt, payload, output, Path(temp), selected, cues if full else None))
            if len(cases) == count:
                break
    if len(cases) != count:
        raise ValueError('Не хватило целых лекционных дорожек в архиве.')
    cases.sort(key=lambda row: hashlib.sha256(('clipmic-long-v1:' + row['lecture_id']).encode()).digest())
    for index, case in enumerate(cases):
        case['subset'] = 'lecture_tune' if index < 2 else 'lecture_holdout'
    save(output / 'manifest.json', cases)
    print(output / 'manifest.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path, help='Архив ru-en или непрерывный префикс с нужными полными FLAC')
    parser.add_argument('output', type=Path)
    parser.add_argument('--count', type=int, choices=range(5, 10), default=5)
    parser.add_argument('--full', action='store_true', help='Сохранить те же исходные лекции целиком')
    args = parser.parse_args()
    prepare(args.archive, args.output, args.count, args.full)
