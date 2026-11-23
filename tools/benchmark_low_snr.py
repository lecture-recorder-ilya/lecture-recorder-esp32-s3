"""Собрать неизменённые ответы Mac ASR и акустические проходы для опыта."""
import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time
import types
import wave

from evaluate_asr import audio_sha256, score, summarize_scores, summarize_subsets


def instrument(source):
    original = source.read_text()
    source_text = original
    anchor = '  windows=speech_windows(ranges,len(samples)/16000,padding=.5,max_seconds=24)'
    if source_text.count(anchor) != 1:
        raise ValueError('Изменился код подготовки окон; проверь инструментирование.')
    source_text = source_text.replace(anchor, '  self._probe_group += 1\n' + anchor)
    anchor = '    selected_all.extend(selected);raw_all.extend(raw)'
    if source_text.count(anchor) != 1:
        raise ValueError('Изменился код сборки проходов; проверь инструментирование.')
    source_text = source_text.replace(anchor,
        "    self._probe_trace.append(__import__('copy').deepcopy(dict(group=self._probe_group, "
        "left=left, right=finish/16000, ctc=ctc, rnnt=rnnt, character=character)))\n" + anchor)
    module = types.ModuleType('quality_asr')
    module.__file__ = str(source)
    sys.modules['quality_asr'] = module
    exec(compile(source_text, str(source), 'exec'), module.__dict__)
    return module, hashlib.sha256(source_text.encode()).hexdigest()


def run(args):
    if args.output.exists():
        raise ValueError('Укажи новый результат: старые измерения не перезаписываются.')
    import numpy as np
    source = args.source_root.resolve()
    sys.path.insert(0, str(source/'outputs/recorder'))
    module, instrumentation_sha = instrument(source/'outputs/recorder/quality_asr.py')
    from speech_quality import clean_asr_text
    from asr_segments import phrase_rows
    if args.gap_crops:
        from asr_low_snr_policy import gap_windows
        from asr_guard import prepare, supported_words
        from speech_gate import strict_speech_ranges
    if args.raw:
        import speech_audio
        speech_audio.enhance_audio = lambda samples, *a, **kw: np.asarray(samples, dtype=np.float32).copy()
    decoder = module.Decoder()
    results = []
    cases = json.loads(args.manifest.read_text())
    if len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Повторяются ID.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    journal = args.output.with_suffix('.jsonl')
    with journal.open('x') as log:
        try:
            for case in cases:
                path = (args.manifest.parent/case['audio']).resolve()
                sha = audio_sha256(path)
                if case.get('audio_sha256', sha) != sha:
                    raise ValueError('Изменился WAV: '+case['id'])
                with wave.open(str(path)) as stream:
                    if (stream.getnchannels(), stream.getsampwidth(), stream.getframerate()) != (1, 2, 16000):
                        raise ValueError('Нужен PCM16 mono 16 кГц.')
                    pcm = stream.readframes(stream.getnframes())
                audio = np.frombuffer(pcm, dtype='<i2').astype(np.float32)/32768
                started = time.monotonic()
                rows, chunks, crop_elapsed = [], [], 0.0
                for offset in range(0, len(audio), 320000):
                    left, right = max(0, offset-32000), min(len(audio), offset+352000)
                    decoder._probe_trace, decoder._probe_group = [], 0
                    first, last = (offset-left)/16000, (min(len(audio), offset+320000)-left)/16000
                    text = clean_asr_text(decoder.transcribe(audio[left:right], case.get('terms', []), emit_start=first, emit_end=last))
                    evidence = deepcopy(decoder.last)
                    crop_trace = []
                    crop_started = time.monotonic()
                    if args.gap_crops and text:
                        core = strict_speech_ranges(audio[left:right])
                        for crop_left, crop_right in gap_windows(evidence.get('word_evidence', []), core, (right-left)/16000):
                            begin, finish = int(crop_left*16000), int(crop_right*16000)
                            crop_left = begin/16000
                            crop = prepare(audio[left+begin:left+finish], highpass=False)
                            local_core = [(max(0, a-crop_left), min(len(crop)/16000, b-crop_left))
                                          for a, b in core if b > crop_left and a < crop_right]
                            trace = dict(group=1, kind='gap_crop', left=crop_left, right=finish/16000)
                            for kind in ('ctc', 'rnnt'):
                                result = decoder._load(kind).recognize(crop, sample_rate=16000)
                                words = supported_words(result, local_core)
                                for word in words:
                                    word['start'] += crop_left
                                    word['end'] = min(finish/16000, word['end']+crop_left)
                                trace[kind] = words
                            crop_trace.append(trace)
                    if args.gap_crops:
                        crop_elapsed += time.monotonic()-crop_started
                    chunks.append(dict(text=text, offset=left/16000, emit_start=offset/16000,
                                       emit_end=min(len(audio), offset+320000)/16000,
                                       evidence=evidence, trace=deepcopy(decoder._probe_trace), gap_trace=crop_trace))
                    rows.extend(phrase_rows(text, decoder.last, left/16000, offset/16000,
                                            min(len(audio), offset+320000)/16000, len(rows)))
                elapsed = time.monotonic()-started
                text = ' '.join(row['text'] for row in rows)
                row = dict(id=case['id'], subset=case['subset'], audio_sha256=sha,
                           pcm_sha256=hashlib.sha256(pcm).hexdigest(), reference=case['reference'],
                           duration=len(audio)/16000, elapsed_seconds=elapsed, text=text,
                           base_elapsed_seconds=elapsed-crop_elapsed, gap_elapsed_seconds=crop_elapsed,
                           chunks=chunks, segments=rows, **score(case['reference'], text, case.get('critical_phrases', [])))
                results.append(row)
                log.write(json.dumps(row, ensure_ascii=False)+'\n')
                log.flush()
                print(case['id'], row['word_errors'], '/', row['reference_words'], text, flush=True)
        finally:
            decoder.close()
    files = [source/'outputs/recorder'/name for name in
             ('quality_asr.py', 'asr_guard.py', 'speech_gate.py', 'speech_audio.py', 'context_review.py', 'asr_terms.py', 'asr_segments.py', 'speech_quality.py')]
    model_paths = [p for subdir in ('gigaam', 'gigaam-rnnt', 'gigaam-beam')
                   for p in (source/'work/models'/subdir).iterdir() if p.suffix in ('.onnx', '.txt', '.json')]
    report = dict(engine=module.ENGINE, raw_audio=args.raw, gap_crops=args.gap_crops, source_root=str(source),
                  manifest_sha256=audio_sha256(args.manifest),
                  script_sha256=audio_sha256(Path(__file__)), instrumented_source_sha256=instrumentation_sha,
                  sources_sha256={p.name: audio_sha256(p) for p in files},
                  models_sha256={str(p.relative_to(source/'work/models')): audio_sha256(p) for p in model_paths},
                  runtime={name: importlib.metadata.version(name) for name in ('onnx-asr', 'onnxruntime', 'numpy', 'torch', 'silero-vad')},
                  platform=dict(system=platform.system(), machine=platform.machine(), python=sys.version),
                  summary=summarize_scores(results), subsets=summarize_subsets(results), cases=results)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(report['summary'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-root', required=True, type=Path)
    parser.add_argument('--raw', action='store_true')
    parser.add_argument('--gap-crops', action='store_true')
    parser.add_argument('--output', required=True, type=Path)
    run(parser.parse_args())
