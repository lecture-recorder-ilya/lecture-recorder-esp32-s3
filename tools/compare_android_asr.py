import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

CLASSES = ('PhoneGigaAm', 'PcmWave', 'PhoneSpeechWindow', 'PhonePhrases', 'PhoneCtc', 'PhoneWordTimeline')
CONTEXT = '''package android.content;
import java.io.*;
public final class Context {
 private final File resources;
 public Context(File resources) { this.resources=resources; }
 public Context getResources() { return this; }
 public InputStream openRawResource(int id) {
  try { return new FileInputStream(new File(resources,id==1?"gigaam_frontend.onnx":"gigaam_tokens.txt")); }
  catch(IOException e) { throw new UncheckedIOException(e); }
 }
}'''
HARNESS = '''package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import org.json.*;
import ai.onnxruntime.OrtEnvironment;
class R { static class raw { static final int gigaam_frontend=1,gigaam_tokens=2; } }
class Store { static RandomAccessFile openAudio(Context c,String name)throws IOException { return new RandomAccessFile(name,"r"); } }
class Preview {
 double first=-1;int phrases=0;
 void startSpeech() { first=-1;phrases=0; }
 void addPhrase(JSONObject row) { if(first<0)first=(System.nanoTime()-Harness.started)/1e9;phrases++; }
}
class PhoneAnalysisService { static class Job { final Preview preview=new Preview();void check() {} void update(String text) {}
 void publishPhrase(JSONObject phrase) { preview.addPhrase(phrase); }
} }
public final class Harness {
 static long started;
 public static void main(String[] args)throws Exception {
  if(args[0].equals("--parse")) {
   for(int i=1;i<args.length;i++) {
    JSONObject row=new JSONObject().put("index",i-1);
    try(RandomAccessFile f=new RandomAccessFile(args[i],"r")) { row.put("data_bytes",PcmWave.seekData(f)); }
    catch(Exception error) { row.put("error",error.getClass().getSimpleName()+": "+error.getMessage()); }
    System.out.println(row);
   }
   return;
  }
  Context context=new Context(new File(args[0]));File model=new File(args[1]);int repeats=Integer.parseInt(args[2]);
  for(int i=3;i<args.length;i++)for(int repeat=0;repeat<repeats;repeat++) {
   PhoneAnalysisService.Job job=new PhoneAnalysisService.Job();started=System.nanoTime();
   JSONObject row=new JSONObject().put("index",i-3).put("repeat",repeat);
   try { row.put("segments",PhoneGigaAm.transcribe(context,job,args[i],model)); }
   catch(Exception error) { row.put("segments",new JSONArray()).put("error",error.getClass().getSimpleName()+": "+error.getMessage()); }
   row.put("elapsed_seconds",(System.nanoTime()-started)/1e9).put("first_preview_seconds",job.preview.first)
    .put("preview_phrases",job.preview.phrases).put("logical_cpus",Runtime.getRuntime().availableProcessors())
    .put("providers",OrtEnvironment.getAvailableProviders().toString());
   System.out.println(row);System.out.flush();
  }
 }
}'''


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, data):
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def prepare(repo, output):
    output.mkdir(parents=True,exist_ok=True)
    if (output/'manifest.json').exists():
        raise FileExistsError('Состав уже зафиксирован')
    source_manifests = {
        'short':repo/'work/asr-speed/round3/reproduced/manifest.json',
        'control':repo/'work/clipmic-next/asr-qa/work/asr-qa/control/manifest.json',
        'independent':repo/'work/asr-speed/round4/independent/manifest.json',
        'quiet':repo/'work/asr-speed/round4/quiet-holdout/manifest.json',
    }
    (output/'wav').mkdir(exist_ok=True)
    manifest=[]
    for cohort,path in source_manifests.items():
        for original in json.loads(path.read_text()):
            source=(path.parent/original['audio']).resolve()
            assert original.get('audio_sha256',sha(source))==sha(source)
            with wave.open(str(source)) as stream:
                assert stream.getparams()[:3]==(1,2,16000)
                pcm=stream.readframes(stream.getnframes())
            target=output/'wav'/f'{len(manifest):04d}.wav'
            with wave.open(str(target),'wb') as stream:
                stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(pcm)
            manifest.append(dict(id=cohort+':'+original['id'],source_id=original['id'],cohort=cohort,
                subset=cohort+'/'+original.get('subset','unspecified'),reference=original['reference'],
                critical_phrases=original.get('critical_phrases',[]),audio=str(target.relative_to(output)),
                audio_sha256=sha(target),pcm_sha256=hashlib.sha256(pcm).hexdigest(),duration=len(pcm)/32000,
                original_audio=str(source),original_audio_sha256=sha(source),terms=[],
                synthetic=original.get('synthetic')))
    assert len(manifest)==267
    write(output/'manifest.json',manifest)
    pieces=[r for r in manifest if r['cohort']=='independent']
    frames=[];timeline=[];offset=0
    for index,row in enumerate(pieces):
        with wave.open(str(output/row['audio'])) as stream:pcm=stream.readframes(stream.getnframes())
        timeline.append(dict(id=row['id'],start=offset/16000,end=(offset+len(pcm)//2)/16000,pcm_sha256=row['pcm_sha256']))
        frames.append(pcm);offset+=len(pcm)//2
        if index+1<len(pieces):frames.append(bytes(8000));offset+=4000
    joined=output/'joined.wav'
    with wave.open(str(joined),'wb') as stream:
        stream.setparams((1,2,16000,0,'NONE','not compressed'));stream.writeframes(b''.join(frames))
    write(output/'long-manifest.json',[dict(id='joined-24',subset='joined_public_clips',cohort='joined',audio=joined.name,
        audio_sha256=sha(joined),pcm_sha256=hashlib.sha256(b''.join(frames)).hexdigest(),duration=offset/16000,
        reference=' '.join(r['reference'] for r in pieces),terms=[],critical_phrases=[],
        synthetic=True,condition='24 открытых фрагмента, соединённых по прежнему порядку с 0.25 с цифровой паузы; не непрерывная лекция',
        timeline=timeline)])
    write(output/'lock.json',dict(created_utc=datetime.now(timezone.utc).isoformat(),inference_runs=0,
        rule='Все 139+92+24+12 фиксированных случаев без отбора по выходам моделей. '
             'Только канонический WAV-заголовок: PCM побайтно сохранён. '
             'Все 24 independent соединены по прежнему порядку с паузой 0.25 с для режима >=90 с. '
             'Исходные заголовки дополнительно проверяются отдельным parser-only проходом.',
        source_manifests={str(p):sha(p) for p in source_manifests.values()},
        files={str(p.relative_to(output)):sha(p) for p in sorted(output.rglob('*')) if p.is_file()}))
    print('Зафиксировано',len(manifest),'WAV;',sha(output/'manifest.json'),flush=True)


def build(source, directory, deps, jdk):
    directory.mkdir(parents=True,exist_ok=False)
    sources={}
    for name in CLASSES:
        path=source/'outputs/android/src/ru/ilya/lecturerecorder'/(name+'.java')
        if path.exists():
            shutil.copyfile(path,directory/path.name);sources[name]=sha(path)
    (directory/'Context.java').write_text(CONTEXT)
    (directory/'Harness.java').write_text(HARNESS)
    cp=os.pathsep.join(str(p) for p in [deps/'ort.jar',deps/'android-json.jar',directory])
    subprocess.run([jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',cp,'-d',directory,*sorted(directory.glob('*.java'))],check=True)
    assert all(sha(directory/(name+'.java'))==value for name,value in sources.items())
    return cp,sources


def run(args):
    if args.output.exists():raise FileExistsError(args.output)
    source=args.source.resolve();manifest=args.manifest.resolve();output=args.output.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    cases=json.loads(manifest.read_text());wavs=[(manifest.parent/r['audio']).resolve() for r in cases]
    for row,path in zip(cases,wavs):assert sha(path)==row['audio_sha256']
    cp,sources=build(source,output.parent/(output.stem+'-jvm'),args.deps.resolve(),args.jdk.resolve())
    command=[str(args.jdk.resolve()/'bin/java'),'-Xmx3g','-cp',cp,'ru.ilya.lecturerecorder.Harness']
    if args.native:
        wavs=[Path(r['original_audio']) for r in cases]
        command+=['--parse',*map(str,wavs)]
    else:
        command+=[str(source/'outputs/android/res/raw'),str(args.model.resolve()),str(args.repeats),*map(str,wavs)]
    start=time.monotonic();journal=output.with_suffix('.jsonl')
    with journal.open('x') as stream:
        subprocess.run(command,stdout=stream,check=True)
    wall=time.monotonic()-start
    decoded=[json.loads(line) for line in journal.read_text().splitlines()]
    if args.native:
        assert len(decoded)==len(cases)
        write(output,dict(source_sha256=sources,manifest_sha256=sha(manifest),mode='parser-only',
            errors=sum('error' in r for r in decoded),cases=[dict(id=c['id'],**r) for c,r in zip(cases,decoded)]))
        return
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from evaluate_asr import score,summarize_scores,summarize_subsets
    assert len(decoded)==len(cases)*args.repeats
    rows=[]
    for index,case in enumerate(cases):
        for repeat in range(args.repeats):
            result=decoded[index*args.repeats+repeat];assert result['index']==index and result['repeat']==repeat
            text=' '.join(segment['text'] for segment in result['segments'])
            rows.append(dict(id=case['id'],subset=case['subset'],cohort=case['cohort'],audio_sha256=case['audio_sha256'],
                pcm_sha256=case['pcm_sha256'],duration=case['duration'],reference=case['reference'],text=text,
                **result,**score(case['reference'],text,case.get('critical_phrases',[]))))
    first=[r for r in rows if r['repeat']==0]
    report=dict(source_commit=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),
        source_sha256=sources,manifest_sha256=sha(manifest),model_sha256=sha(args.model),
        resources_sha256={n:sha(source/'outputs/android/res/raw'/n) for n in ('gigaam_frontend.onnx','gigaam_tokens.txt')},
        dependencies_sha256={n:sha(args.deps/n) for n in ('ort.jar','android-json.jar')},script_sha256=sha(__file__),
        engine='Android PhoneGigaAm / GigaAM-v3-e2e-CTC-int8 / desktop JVM ONNX Runtime JNI CPU',
        repeats=args.repeats,process_wall_seconds=wall,summary=summarize_scores(first),subsets=summarize_subsets(first),
        cohorts={name:summarize_scores([r for r in first if r['cohort']==name]) for name in sorted({r['cohort'] for r in first})},
        error_cases=sum('error' in r for r in first),cases=rows,platform=platform.platform(),command=command)
    for name,value in sources.items():assert sha(source/'outputs/android/src/ru/ilya/lecturerecorder'/(name+'.java'))==value
    assert all(sha(path)==case['audio_sha256'] for path,case in zip(wavs,cases))
    write(output,report)
    print(json.dumps(dict(output=str(output),summary=report['summary']),ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='mode',required=True)
    p=sub.add_parser('prepare');p.add_argument('repo',type=Path);p.add_argument('output',type=Path)
    p=sub.add_parser('run');p.add_argument('manifest',type=Path)
    for name in ('source','deps','jdk','model','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--repeats',type=int,default=1);p.add_argument('--native',action='store_true')
    args=parser.parse_args()
    if args.mode=='prepare':prepare(args.repo.resolve(),args.output.resolve())
    else:run(args)


if __name__=='__main__':main()
