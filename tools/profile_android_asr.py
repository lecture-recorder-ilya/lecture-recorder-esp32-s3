"""Измерить этапы настоящего Android ASR на настольном ONNX Runtime JNI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import wave

from evaluate_asr import audio_sha256, score, summarize_scores, summarize_subsets

CLASSES = ('PhoneGigaAm', 'PcmWave', 'PhoneSpeechWindow', 'PhonePhrases', 'PhoneCtc')
CONTEXT = '''package android.content;
import java.io.*;
public final class Context {
 private final File directory;
 public Context(File path) { directory=path; }
 public Context getResources() { return this; }
 public InputStream openRawResource(int id) { try { return new FileInputStream(new File(directory,
  id==1?"gigaam_frontend.onnx":"gigaam_tokens.txt")); } catch(IOException e) { throw new UncheckedIOException(e); } }
}'''
HARNESS = '''package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import org.json.*;
class R { static class raw { static final int gigaam_frontend=1,gigaam_tokens=2; } }
class Store { static RandomAccessFile openAudio(Context c,String n)throws IOException { return new RandomAccessFile(n,"r"); } }
class PhoneAnalysisService { static class Job { void check() {} void update(String s) {} } }
class Probe {
 static long started,primary,clean,onset; static int primaryCalls,cleanCalls,onsetCalls;
 static double loaded,firstPrimary,firstPhrase;
 static JSONArray windows,before,alternate,check;
 static double seconds() { return (System.nanoTime()-started)/1e9; }
 static void reset() { started=System.nanoTime();primary=clean=onset=0;primaryCalls=cleanCalls=onsetCalls=0;
  loaded=firstPrimary=firstPhrase=-1;windows=new JSONArray();before=alternate=null; }
 static void primary(JSONArray words) throws Exception { primaryCalls++;
  before=new JSONArray(words.toString());alternate=check=null;
  if(words.length()>0 && firstPrimary<0)firstPrimary=seconds(); }
 static void record(JSONArray words,double start,double end,double left,double duration)throws Exception {
  JSONObject row=new JSONObject().put("primary",before).put("final",new JSONArray(words.toString()))
   .put("emit_start",start).put("emit_end",end).put("audio_start",left).put("audio_end",left+duration);
  if(alternate!=null)row.put("cleaned",alternate);if(check!=null)row.put("onset_check",check);windows.put(row); }
}
public final class Harness {
 public static void main(String[] args)throws Exception {
  Context context=new Context(new File(args[0]));File model=new File(args[1]);int repeats=Integer.parseInt(args[2]);
  for(int i=3;i<args.length;i++)for(int r=0;r<repeats;r++) {
   Probe.reset();JSONArray segments=PhoneGigaAm.transcribe(context,new PhoneAnalysisService.Job(),args[i],model);
   double elapsed=Probe.seconds();System.out.println(new JSONObject().put("repeat",r).put("elapsed_seconds",elapsed)
    .put("load_seconds",Probe.loaded).put("first_primary_seconds",Probe.firstPrimary)
    .put("first_phrase_built_seconds",Probe.firstPhrase).put("available_at_return_seconds",elapsed)
    .put("primary_seconds",Probe.primary/1e9).put("clean_seconds",Probe.clean/1e9)
    .put("primary_calls",Probe.primaryCalls).put("clean_calls",Probe.cleanCalls)
    .put("onset_calls",Probe.onsetCalls).put("onset_seconds",Probe.onset/1e9)
    .put("windows",Probe.windows).put("segments",segments));
  }
 }
}'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('Изменился измеряемый код: '+before[:60])
    return text.replace(before, after)


def prepare_sources(source, folder, instrument=True):
    folder.mkdir(parents=True)
    sources = {}
    classes = CLASSES + (('PhoneWordTimeline',) if (source/'outputs/android/src/ru/ilya/lecturerecorder/PhoneWordTimeline.java').exists() else ())
    for name in classes:
        path = source/'outputs/android/src/ru/ilya/lecturerecorder'/(name+'.java')
        sources[name] = audio_sha256(path)
        shutil.copyfile(path, folder/path.name)
    if instrument:
        path=folder/'PhoneGigaAm.java';text=path.read_text()
        text=replace_once(text,'                int progress = -1;', '                Probe.loaded=Probe.seconds();\n                int progress = -1;')
        primary='                        JSONArray words = recognize(environment, frontend, acoustic, wave, tokens, offset, first, last, true);'
        text=replace_once(text,primary,'                        long primaryStart=System.nanoTime();\n'+primary+'\n                        Probe.primary+=System.nanoTime()-primaryStart;Probe.primary(words);')
        check='''                            JSONArray check = recognize(environment, frontend, acoustic, shifted, tokens,
                                    0, 0, shifted.length / (double) RATE, true);'''
        if check in text:
            text=replace_once(text,check,'                            long onsetStart=System.nanoTime();\n'+check+'\n                            Probe.onset+=System.nanoTime()-onsetStart;Probe.onsetCalls++;Probe.check=new JSONArray(check.toString());')
        text=replace_once(text,'                            float[] clean = PhoneSpeechWindow.clean(raw);',
                         '                            long cleanStart=System.nanoTime();\n                            float[] clean = PhoneSpeechWindow.clean(raw);')
        alternate='                            JSONArray alternate = recognize(environment, frontend, acoustic, clean, tokens, offset, first, last, true);'
        text=replace_once(text,alternate,alternate+'\n                            Probe.clean+=System.nanoTime()-cleanStart;Probe.cleanCalls++;Probe.alternate=new JSONArray(alternate.toString());')
        accept='                        timeline.accept(words, last);' if 'timeline.accept(words, last)' in text else '                        phrases.accept(words);'
        text=replace_once(text,accept,'                        Probe.record(words,first,last,offset,wave.length/16000.0);\n'+accept)
        path.write_text(text)
        path=folder/'PhonePhrases.java';text=path.read_text()
        text=replace_once(text,'        count = 0;', '        if(Probe.firstPhrase<0 && segments.length()>0)Probe.firstPhrase=Probe.seconds();\n        count = 0;')
        path.write_text(text)
    (folder/'Context.java').write_text(CONTEXT)
    (folder/'Harness.java').write_text(HARNESS)
    return sources


def run(args):
    if args.output.exists():
        raise ValueError('Укажи новый результат.')
    folder=args.output.parent/(args.output.stem+'-jvm')
    if folder.exists():
        raise ValueError('Копия стенда уже существует.')
    source=args.source_root.resolve()
    sources=prepare_sources(source,folder)
    rows=json.loads(args.manifest.read_text());wavs=[]
    inputs=folder/'inputs';inputs.mkdir()
    metadata=[]
    for i,row in enumerate(rows):
        wav=(args.manifest.parent/row['audio']).resolve();sha=audio_sha256(wav)
        if row.get('audio_sha256',sha)!=sha:raise ValueError('Изменился WAV')
        with wave.open(str(wav)) as stream:
            if (stream.getnchannels(),stream.getsampwidth(),stream.getframerate())!=(1,2,16000):raise ValueError('Нужен PCM16 mono 16кГц.')
            pcm=stream.readframes(stream.getnframes())
        canonical=inputs/f'{i:04}.wav'
        with wave.open(str(canonical),'wb') as stream:
            stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(pcm)
        wavs.append(canonical);metadata.append(dict(audio_sha256=sha,pcm_sha256=hashlib.sha256(pcm).hexdigest(),duration=len(pcm)/32000))
    cp=os.pathsep.join(map(str,[args.deps/'ort.jar',args.deps/'android-json.jar',folder]))
    subprocess.run([args.jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cp,'-d',folder,*sorted(folder.glob('*.java'))],check=True)
    journal=args.output.with_suffix('.jsonl')
    with journal.open('x') as output:
        subprocess.run([args.jdk/'bin/java','-cp',cp,'ru.ilya.lecturerecorder.Harness',source/'outputs/android/res/raw',args.model,str(args.repeats),*wavs],stdout=output,check=True)
    decoded=[json.loads(line) for line in journal.read_text().splitlines()]
    if len(decoded)!=len(rows)*args.repeats:raise ValueError('Неполный ответ JVM.')
    cases=[]
    for i,(row,meta) in enumerate(zip(rows,metadata,strict=True)):
        for r in range(args.repeats):
            result=decoded[i*args.repeats+r];text=' '.join(s['text'] for s in result['segments'])
            cases.append(dict(id=row['id'],subset=row['subset'],reference=row['reference'],text=text,
                              **meta,**result,**score(row['reference'],text)))
    report=dict(source_root=str(source),sources_sha256=sources,script_sha256=audio_sha256(Path(__file__)),
                manifest_sha256=audio_sha256(args.manifest),model_sha256=audio_sha256(args.model),
                dependencies_sha256={name:audio_sha256(args.deps/name) for name in ('ort.jar','android-json.jar')},
                summary=summarize_scores([c for c in cases if c['repeat']==0]),
                subsets=summarize_subsets([c for c in cases if c['repeat']==0]),cases=cases)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(summary=report['summary'],output=str(args.output)),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--deps',required=True,type=Path)
    parser.add_argument('--jdk',required=True,type=Path)
    parser.add_argument('--model',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--repeats',type=int,default=2,choices=(1,2,3))
    run(parser.parse_args())
