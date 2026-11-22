"""Run the production Android ASR classes on desktop ONNX Runtime JNI.

Adapted from work/clipmic-asr-quality/results/android_jvm.py. This measures the
Java decoder, not Android hardware, microphone capture, battery use or thermals.
"""
import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import wave

from evaluate_asr import audio_sha256, score, summarize_scores, summarize_subsets

CLASSES = ('PhoneGigaAm', 'PcmWave', 'PhoneSpeechWindow', 'PhonePhrases', 'PhoneCtc')
# Experimental transformations apply only to the copied harness sources.
# The production checkout is never changed by this evaluator.
VARIANTS = {
    'gain32': 'PhoneSpeechWindow.normalize(wave, level, 32);',
    'gain128': 'PhoneSpeechWindow.normalize(wave, level, 128);',
    'quiet-clean': ('PhoneSpeechWindow.normalize(wave, level, 32);\n'
                    '                        if (level < .05f) wave = PhoneSpeechWindow.clean(raw);'),
    'quiet-gain32': 'PhoneSpeechWindow.normalize(wave, level, level < .01f ? 32 : 8);',
    'quiet-gain128': 'PhoneSpeechWindow.normalize(wave, level, level < .01f ? 128 : 8);',
}
RETRIES = {
    'raw-retry32': ('float[] clean = raw.clone();\n'
                    '                            PhoneSpeechWindow.normalize(clean, level, 32);'),
    'mixed-retry': ('float[] clean = PhoneSpeechWindow.clean(raw);\n'
                    '                            float[] normalized = raw.clone();\n'
                    '                            PhoneSpeechWindow.normalize(normalized, level, 32);\n'
                    '                            for (int i = 0; i < clean.length; i++) clean[i] = (clean[i] + normalized[i]) * .5f;'),
}
STUBS = {
    'Context.java': '''
package android.content;
import java.io.*;
public final class Context {
    private final File resources;
    public Context(File resources) { this.resources = resources; }
    public Context getResources() { return this; }
    public InputStream openRawResource(int id) {
        try {
            return new FileInputStream(new File(resources, id==1?"gigaam_frontend.onnx":"gigaam_tokens.txt"));
        } catch (IOException e) { throw new UncheckedIOException(e); }
    }
}
''',
    'Harness.java': '''
package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import org.json.*;
class R { static class raw { static final int gigaam_frontend=1,gigaam_tokens=2; } }
class Store {
    static RandomAccessFile openAudio(Context c,String name)throws IOException { return new RandomAccessFile(name,"r"); }
}
class PhoneAnalysisService { static class Job { void check() {} void update(String s) {} } }
public final class Harness {
    public static void main(String[] args)throws Exception {
        Context context = new Context(new File(args[0]));
        File model = new File(args[1]);
        for (int i = 2; i < args.length; i++) {
            long started = System.nanoTime();
            JSONArray rows = PhoneGigaAm.transcribe(context, new PhoneAnalysisService.Job(), args[i], model);
            System.out.println(new JSONObject().put("elapsed_seconds", (System.nanoTime()-started)/1e9).put("segments", rows));
        }
    }
}
''',
}


def run(args):
    source, output = args.source_root.resolve(), args.output.resolve()
    android = source / 'outputs/android'
    runner = output.parent / (output.stem + '-jvm')
    if output.exists() or runner.exists():
        raise ValueError('Use a new output path: existing results are never overwritten.')
    cases = json.loads(args.manifest.read_text())
    if not cases or len({case['id'] for case in cases}) != len(cases):
        raise ValueError('Expected nonempty cases with unique ids.')
    wavs = [(args.manifest.parent / case['audio']).resolve() for case in cases]
    hashes, durations = [], []
    for case, wav in zip(cases, wavs, strict=True):
        sha = audio_sha256(wav)
        if case.get('audio_sha256', sha) != sha:
            raise ValueError(f"{case['id']}: audio hash differs from manifest")
        with wave.open(str(wav)) as stream:
            if (stream.getframerate(), stream.getnchannels(), stream.getsampwidth()) != (16000, 1, 2):
                raise ValueError('Expected PCM16 mono 16 kHz WAV')
            durations.append(stream.getnframes() / stream.getframerate())
        hashes.append(sha)
    runner.mkdir(parents=True)
    # OpenSTT WAVs may use the extensible PCM header. Android's import step
    # produces plain PCM WAV; do the same here without changing a single sample.
    inputs_dir = runner / 'inputs'
    inputs_dir.mkdir()
    canonical, pcm_hashes = [], []
    for index, wav in enumerate(wavs):
        with wave.open(str(wav)) as stream:
            pcm = stream.readframes(stream.getnframes())
        target = inputs_dir / f'{index:04}.wav'
        with wave.open(str(target), 'wb') as stream:
            stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            stream.writeframes(pcm)
        with wave.open(str(target)) as stream:
            if stream.readframes(stream.getnframes()) != pcm:
                raise ValueError('Canonical WAV changed PCM samples')
        canonical.append(target)
        pcm_hashes.append(hashlib.sha256(pcm).hexdigest())
    sources, original_sources = {}, {}
    for name in CLASSES:
        path = android / 'src/ru/ilya/lecturerecorder' / (name + '.java')
        original_sources[name] = audio_sha256(path)
        shutil.copyfile(path, runner / path.name)
    patch = ''
    if args.variant:
        path = runner / 'PhoneGigaAm.java'
        before = path.read_text()
        original = ('float[] clean = PhoneSpeechWindow.clean(raw);' if args.variant in RETRIES else
                    'PhoneSpeechWindow.normalize(wave, level, 8);')
        if before.count(original) != 1:
            raise ValueError('Experimental variant requires the unmodified v0.5.9 source block.')
        after = before.replace(original, (RETRIES | VARIANTS)[args.variant])
        path.write_text(after)
        patch = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                           fromfile='a/PhoneGigaAm.java', tofile='b/PhoneGigaAm.java'))
    sources = {name: audio_sha256(runner / (name + '.java')) for name in CLASSES}
    for name, content in STUBS.items():
        (runner / name).write_text(content)
    deps = [args.deps / 'ort.jar', args.deps / 'android-json.jar']
    cp = os.pathsep.join(map(str, [*deps, runner]))
    subprocess.run([args.jdk/'bin/javac', '-encoding', 'UTF-8', '--release', '8', '-cp', cp,
                    '-d', runner, *sorted(runner.glob('*.java'))], check=True)
    raw = output.with_suffix('.jsonl')
    with raw.open('x') as stream:
        subprocess.run([args.jdk/'bin/java', '-cp', cp, 'ru.ilya.lecturerecorder.Harness',
                        android/'res/raw', args.model, *canonical], stdout=stream, check=True)
    rows = []
    for case, sha, duration, decoded_wav, pcm_sha, line in zip(
            cases, hashes, durations, canonical, pcm_hashes, raw.read_text().splitlines(), strict=True):
        decoded = json.loads(line)
        text = ' '.join(segment['text'] for segment in decoded['segments'])
        # Validate emitted phrase/word intervals without assuming acoustic accuracy.
        for segment in decoded['segments']:
            if not 0 <= segment['start'] < segment['end'] <= duration + .001:
                raise ValueError(f"{case['id']}: invalid phrase interval")
            for begin, end, millis in segment['word_times']:
                if not (0 <= begin < end <= len(segment['text']) and
                        segment['start'] - .001 <= millis / 1000 <= segment['end'] + .001):
                    raise ValueError(f"{case['id']}: invalid word interval")
        rows.append(dict(id=case['id'], subset=case['subset'], audio_sha256=sha, duration=duration,
                         decoder_audio_sha256=audio_sha256(decoded_wav), pcm_sha256=pcm_sha,
                         reference=case['reference'], text=text, **decoded,
                         **score(case['reference'], text, case.get('critical_phrases', []))))
    result = dict(engine='Android PhoneGigaAm / desktop JVM', source_root=str(source),
                  variant=args.variant, experimental_patch=patch, original_sources_sha256=original_sources,
                  evaluator_sha256=audio_sha256(Path(__file__)),
                  scorer_sha256=audio_sha256(Path(__file__).with_name('evaluate_asr.py')),
                  sources_sha256=sources, manifest_sha256=audio_sha256(args.manifest),
                  dependencies_sha256={str(path): audio_sha256(path) for path in deps},
                  model_sha256=audio_sha256(args.model),
                  resources_sha256={path.name: audio_sha256(path) for path in
                                    (android/'res/raw/gigaam_frontend.onnx', android/'res/raw/gigaam_tokens.txt')},
                  jdk=subprocess.check_output([args.jdk/'bin/java', '-version'], stderr=subprocess.STDOUT, text=True),
                  summary=summarize_scores(rows), subsets=summarize_subsets(rows), cases=rows)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(output=str(output), summary=result['summary'], subsets=result['subsets']),
                     ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--source-root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--deps', type=Path, required=True)
    parser.add_argument('--jdk', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--variant', choices=VARIANTS | RETRIES, help='Experiment on copied sources from v0.5.9')
    run(parser.parse_args())
