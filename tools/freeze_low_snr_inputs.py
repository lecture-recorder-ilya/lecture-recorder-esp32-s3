"""Зафиксировать существующие наборы настройки и контроля без изменения WAV."""
import argparse
import json
from pathlib import Path

from evaluate_asr import audio_sha256


def freeze(args):
    if args.output.exists():
        raise ValueError('Укажи новую папку: существующий набор не перезаписывается.')
    sets, sources = {}, {}
    for label, manifest in (('tune', args.tune), ('control', args.control)):
        rows = json.loads(manifest.read_text())
        if not rows or len({row['id'] for row in rows}) != len(rows):
            raise ValueError('Нужны непустой список и уникальные ID.')
        for row in rows:
            audio = (manifest.parent/row['audio']).resolve()
            sha = audio_sha256(audio)
            if row.get('audio_sha256', sha) != sha:
                raise ValueError('Изменился WAV: '+row['id'])
            row.update(audio=str(audio), audio_sha256=sha)
        sets[label] = rows
        sources[label] = dict(manifest=str(manifest.resolve()), sha256=audio_sha256(manifest))
    a, b = (sets[key] for key in ('tune', 'control'))
    if {r['audio_sha256'] for r in a if r['reference']} & {r['audio_sha256'] for r in b if r['reference']}:
        raise ValueError('Речевой WAV попал и в настройку, и в контроль.')
    source_ids = lambda rows: {str(row.get('source_id', row.get('source_item'))) for row in rows
                               if row['reference'] and row.get('source_id', row.get('source_item')) is not None}
    if source_ids(a) & source_ids(b):
        raise ValueError('Исходный речевой фрагмент попал в оба набора.')
    args.output.mkdir(parents=True)
    for label, rows in sets.items():
        (args.output/(label+'.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2)+'\n')
    proof = dict(sources=sources, manifests_sha256={label: audio_sha256(args.output/(label+'.json')) for label in sets},
                 script_sha256=audio_sha256(Path(__file__)), speech_overlap=False,
                 note='Общие синтетические файлы без речи допустимы; они не объявляются новой независимой выборкой.')
    (args.output/'inputs.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(proof, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tune', type=Path)
    parser.add_argument('control', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    freeze(parser.parse_args())
