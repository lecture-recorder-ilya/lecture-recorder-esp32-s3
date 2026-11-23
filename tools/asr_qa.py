"""Фиксация, прогон и сравнение независимого контроля ClipMic."""

import argparse
from collections import defaultdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import subprocess
import sys

from evaluate_asr import NEGATIONS, audio_sha256, indexed_rows, numeric_token, score, tokens
from prepare_asr_qa import load, save


PHRASE_MIN_WORDS = 3
LECTURE_SUBSETS = {'lecture_tune', 'lecture_holdout'}
SOURCES = {
    'openstt_lectures': {
        'source': 'OpenSTT public_lecture_1',
        'url': 'https://github.com/snakers4/open_stt#links',
        'archive': 'https://zenodo.org/records/4899885/files/public_lecture_1.tar.gz',
        'index': 'https://azureopendatastorage.blob.core.windows.net/openstt/ru_open_stt_opus/manifests/public_lecture_1.csv',
        'license': 'CC BY-NC 4.0 (условия корпуса)',
        'annotation': 'Человеческие субтитры/ручная разметка по описанию корпуса',
        'condition': 'Лекционная речь, исходный фон и микрофон; расстояние неизвестно',
    },
    'mtedx_public_talks': {
        'source': 'Multilingual TEDx, русский test',
        'url': 'https://www.openslr.org/100/',
        'parquet': 'https://huggingface.co/datasets/deepdml/mtedx/blob/89e77b30f14b8c580b19dc51087f675ff90cda07/ru/test-00000-of-00001.parquet',
        'license': 'CC BY-NC-ND 4.0',
        'annotation': 'Субтитры TEDx, выровненные авторами корпуса',
        'condition': 'Публичное выступление, исходный фон; расстояние неизвестно',
    },
    'golos_farfield': {
        'source': 'Golos Farfield, повтор прежней пробы',
        'url': 'https://huggingface.co/datasets/bond005/sberdevices_golos_100h_farfield',
        'license': 'https://github.com/sberdevices/golos/blob/master/license/en_us.pdf',
        'annotation': 'Ручная крауд-разметка Golos',
        'condition': 'Короткие команды; метка дистанции и парная дорожка для отдельных ID отсутствуют',
    },
    'no_speech': {'source': 'Контроль без речи', 'condition': 'Цифровая тишина и синтетический шум из стенда rear-row'},
}
SOURCES['modeled_room_6db'] = dict(SOURCES['openstt_lectures'],
    condition='Те же исходные лекции. Отражения, ограничение полосы и смоделированный шум +6 дБ SNR.')
for name in LECTURE_SUBSETS:
    SOURCES[name] = dict(
        source='Multilingual TEDx ru-en', url='https://www.openslr.org/100/',
        license='CC BY-NC-ND 4.0', annotation='Субтитры из архива авторов',
        condition='Непрерывное окно исходной дорожки. Расстояние неизвестно.')


def validate_lecture_splits(rows):
    groups = {}
    for row in rows:
        subset = row['subset']
        if subset not in LECTURE_SUBSETS:
            raise ValueError('Длинные лекции фиксируются отдельным набором.')
        if not row.get('lecture_id') or row.get('reference_type') not in ('subtitles', 'manual_verified'):
            raise ValueError(f"{row['id']}: нужны исходная лекция и немашинный эталон.")
        for key in ('lecture_id', 'speaker_id'):
            if row.get(key) and groups.setdefault((key, row[key]), subset) != subset:
                raise ValueError(f"{row['id']}: {key} попал в настройку и контроль.")


def lock_control(manifest):
    cases = indexed_rows(load(manifest), 'Контроль')
    if any(row['subset'] in LECTURE_SUBSETS for row in cases.values()):
        validate_lecture_splits(cases.values())
    specs = []
    for row in cases.values():
        path = manifest.parent / row['audio']
        if Path(row['audio']).name != row['audio'] or audio_sha256(path) != row['audio_sha256']:
            raise ValueError(f"{row['id']}: WAV не совпадает с манифестом.")
        if row['subset'] not in SOURCES:
            raise ValueError(f"{row['id']}: неизвестное условие записи.")
        metadata = {key: row[key] for key in ('source_id', 'source_item', 'reference_item', 'source_revision',
                    'source_audio_sha256', 'parent_audio_sha256', 'source_video', 'source_start',
                    'source_end', 'selection', 'seed', 'lecture_id', 'speaker_id', 'source_split',
                    'clip_start', 'clip_end', 'full_seconds', 'reference_type', 'source_vtt_sha256') if key in row}
        specs.append(dict(id=row['id'], subset=row['subset'], audio_sha256=row['audio_sha256'],
                          reference_sha256=hashlib.sha256(row['reference'].encode()).hexdigest(), **metadata))
    originals = {row['source_id']: row for row in specs if row['subset'] == 'openstt_lectures'}
    for row in specs:
        if row['subset'] == 'modeled_room_6db':
            parent = originals.get(row['source_id'])
            if (not parent or row['parent_audio_sha256'] != parent['audio_sha256']
                    or row['reference_sha256'] != parent['reference_sha256']):
                raise ValueError(f"{row['id']}: потеряна связь с исходной лекцией.")
    return dict(manifest_sha256=audio_sha256(manifest), phrase_min_words=PHRASE_MIN_WORDS,
                sources={name: SOURCES[name] for name in sorted({row['subset'] for row in specs})}, cases=specs)


def deletion_runs(edits):
    runs = []
    for edit in edits:
        if edit['op'] != 'deletions':
            continue
        index = edit['reference_index']
        if runs and runs[-1][1] == index:
            runs[-1][1] += 1
        else:
            runs.append([index, index + 1])
    return [span for span in runs if span[1] - span[0] >= PHRASE_MIN_WORDS]


def critical_counts(expected, edits, predicate):
    def critical(word):
        return bool(word and predicate(word))

    return dict(reference=sum(map(critical, expected)),
                lost_or_changed=sum(critical(edit['reference']) for edit in edits),
                inserted_or_changed=sum(critical(edit['hypothesis']) for edit in edits))


def audit(row, result):
    stats = score(row['reference'], result['text'])
    edits = stats['word_edits']
    expected = tokens(row['reference'])
    phrases = deletion_runs(edits)
    return dict(stats, id=row['id'], subset=row['subset'], audio_sha256=row['audio_sha256'],
                elapsed_seconds=result['elapsed_seconds'], duration=result['duration'],
                phrase_deletions=phrases, phrase_count=len(phrases),
                empty_decode=int(bool(expected) and not tokens(result['text'])),
                numbers=critical_counts(expected, edits, numeric_token),
                negations=critical_counts(expected, edits, NEGATIONS.__contains__))


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row['subset']].append(row)
    output = {}
    for subset, group in sorted(groups.items()):
        words = sum(row['reference_words'] for row in group)
        errors = sum(row['word_errors'] for row in group if row['reference_words'])
        elapsed = sum(row['elapsed_seconds'] for row in group)
        seconds = sum(row['duration'] for row in group)
        output[subset] = dict(clips=len(group), words=words, errors=errors, wer=errors/words if words else None,
                              elapsed_seconds=round(elapsed, 3), audio_seconds=round(seconds, 3),
                              no_speech_words=sum(row['hallucinated_words'] for row in group),
                              empty_decodes=sum(row['empty_decode'] for row in group),
                              phrase_deletions=sum(row['phrase_count'] for row in group))
        for metric in ('word_error_breakdown', 'numbers', 'negations'):
            output[subset][metric] = {key: sum(row[metric][key] for row in group) for key in group[0][metric]}
    return output


def model_provenance(source):
    models = []
    for name in ('gigaam', 'gigaam-rnnt', 'gigaam-beam'):
        root = source / 'work/models'
        manifest = root / (name + '-manifest.json')
        value = load(manifest)
        for spec in value['files']:
            if audio_sha256(root / name / spec['name']) != spec['sha256']:
                raise ValueError(f"{spec['name']}: SHA-256 весов не совпадает.")
        models.append(dict(value, manifest_sha256=audio_sha256(manifest)))
    return dict(models=models, onnxruntime=version('onnxruntime'), onnx_asr=version('onnx-asr'))


def run(args):
    manifest = args.manifest.resolve()
    source = args.source_root.resolve()
    lock = load(args.lock)
    if lock_control(manifest) != lock:
        raise ValueError('Контроль отличается от зафиксированного набора.')
    revision = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
    evaluator = Path(__file__).with_name('evaluate_asr.py')
    lecture_run = bool(LECTURE_SUBSETS.intersection(lock['sources']))
    if lecture_run and args.android:
        raise ValueError('Длинный контроль использует конвейер Mac.')
    if lecture_run:
        evaluator = evaluator.with_name('evaluate_lecture_asr.py')
    if args.android:
        if not all((args.jdk, args.deps, args.model)):
            raise ValueError('Для Android нужны --jdk, --deps и --model.')
        evaluator = Path(__file__).with_name('evaluate_android_asr.py')
        extra = ['--jdk', args.jdk, '--deps', args.deps, '--model', args.model]
        provenance = {}
    else:
        extra = []
        provenance = model_provenance(source)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    raw = output.with_name(output.stem + '.decoded.json')
    if output.exists() or raw.exists():
        raise ValueError(f'{output}: укажи новый файл результата.')
    with output.with_suffix('.log').open('x') as log:
        subprocess.run([sys.executable, evaluator, manifest, '--source-root', source, '--output', raw, *extra],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    decoded = load(raw)
    decoded_index = indexed_rows(decoded['cases'], revision)
    cases = indexed_rows(load(manifest), 'Контроль')
    if decoded_index.keys() != cases.keys():
        raise ValueError('Декодер вернул другой список WAV.')
    rows = []
    for ident, row in cases.items():
        result = decoded_index[ident]
        if result['audio_sha256'] != row['audio_sha256']:
            raise ValueError(f'{ident}: декодер получил другой WAV.')
        rows.append(audit(row, result))
    if args.android:
        for key in ('model_sha256', 'sources_sha256', 'resources_sha256', 'dependencies_sha256', 'jdk'):
            provenance[key] = decoded[key]
    else:
        provenance['source_sha256'] = {name: audio_sha256(source / 'outputs/recorder' / (name + '.py'))
                                       for name in ('quality_asr', 'speech_gate', 'asr_guard', 'asr_segments')}
    save(output, dict(revision=revision, engine=decoded['engine'], platform='android-jvm' if args.android else 'mac',
                      lock_sha256=audio_sha256(args.lock), manifest_sha256=lock['manifest_sha256'],
                      evaluator_sha256=audio_sha256(evaluator), provenance=provenance,
                      subsets=summarize(rows), cases=rows))
    print(output)


def compare(base, candidate):
    if any(base[key] != candidate[key] for key in ('platform', 'lock_sha256', 'manifest_sha256')):
        raise ValueError('Нужны одна платформа и один зафиксированный набор.')
    def audio_index(report):
        return {ident: row['audio_sha256'] for ident, row in indexed_rows(report['cases'], 'Прогон').items()}
    if audio_index(base) != audio_index(candidate):
        raise ValueError('В прогонах разные WAV.')

    def critical(old, new, key):
        a, b = old[key], new[key]
        return (f"{a['lost_or_changed']}/{a['inserted_or_changed']} → "
                f"{b['lost_or_changed']}/{b['inserted_or_changed']} из {a['reference']}")

    print(f"{base['platform']} · {base['revision'][:7]} → {candidate['revision'][:7]}\n")
    print('| Набор | WAV | Ошибки/слова | Пропуски фраз | Числа | Отрицания | Время, с |')
    print('| --- | ---: | ---: | ---: | ---: | ---: | ---: |')
    for name, old in base['subsets'].items():
        new = candidate['subsets'][name]
        quality = (f"{old['errors']} → {new['errors']} / {old['words']}" if old['words']
                   else f"{old['no_speech_words']} → {new['no_speech_words']} лишних")
        print(f"| {name} | {old['clips']} | {quality} | {old['phrase_deletions']} → {new['phrase_deletions']} | "
              f"{critical(old, new, 'numbers')} | {critical(old, new, 'negations')} | "
              f"{old['elapsed_seconds']:.2f} → {new['elapsed_seconds']:.2f} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    freeze = commands.add_parser('freeze')
    freeze.add_argument('manifest', type=Path)
    freeze.add_argument('output', type=Path)
    measure = commands.add_parser('run')
    measure.add_argument('manifest', type=Path)
    measure.add_argument('--lock', type=Path, required=True)
    measure.add_argument('--source-root', type=Path, required=True)
    measure.add_argument('--output', type=Path, required=True)
    measure.add_argument('--android', action='store_true')
    for name in ('jdk', 'deps', 'model'):
        measure.add_argument('--' + name, type=Path)
    table = commands.add_parser('compare')
    table.add_argument('base', type=Path)
    table.add_argument('candidate', type=Path)
    args = parser.parse_args()
    if args.command == 'freeze':
        save(args.output, lock_control(args.manifest))
    elif args.command == 'run':
        run(args)
    else:
        compare(load(args.base), load(args.candidate))


if __name__ == '__main__':
    main()
