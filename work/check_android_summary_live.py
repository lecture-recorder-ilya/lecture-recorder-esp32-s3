import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile

PROBE=r'''package ru.clipmic.summarycompare;
import android.app.*;
import android.os.*;
import android.content.*;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.*;
import java.util.*;
import java.util.function.Consumer;
public final class Probe extends Instrumentation {
 Bundle options;
 public void onCreate(Bundle b){super.onCreate(b);options=b;start();}
 public void onStart(){
  Bundle output=new Bundle();JSONArray results=new JSONArray();
  try {
   Context context=getTargetContext();ClassLoader loader=context.getClassLoader();
   JSONObject input=new JSONObject(new String(Files.readAllBytes(new File(context.getFilesDir(),"qa-summary-comparison.json").toPath()),StandardCharsets.UTF_8));
   JSONArray cases=input.getJSONArray("cases");
   if(options.getString("variant").equals("candidate")) {
    String quote="Икс не равен пяти.";
    JSONObject unicode=new JSONObject().put("segments",new JSONArray().put(new JSONObject().put("id",7).put("start",1).put("end",4).put("text","Икс\u00a0не\u2003равен\u0085пяти.\u001c")))
      .put("summary",new JSONArray().put(quote)).put("summary_evidence",new JSONArray().put(new JSONObject().put("quote",quote).put("segment_id",7).put("start",1).put("end",4)));
    Class<?> sources=Class.forName("ru.ilya.lecturerecorder.SummarySources",true,loader);
    Method reconcile=sources.getDeclaredMethod("reconcile",JSONObject.class,boolean.class,boolean.class);reconcile.setAccessible(true);reconcile.invoke(null,unicode,false,true);
    String fingerprint=unicode.getJSONArray("summary_evidence").getJSONObject(0).getString("source_fingerprint");
    if(!fingerprint.equals("96ef901c669bbe7404464ae8a4b6d7042df5d3e4a2139564526a6217d77ca32f"))throw new IllegalStateException("Unicode source mismatch");
    output.putString("unicode_source",fingerprint);
   }
   Class<?> jobType=Class.forName("ru.ilya.lecturerecorder.PhoneAnalysisService$Job",true,loader);
   Constructor<?> constructor=jobType.getDeclaredConstructor(Consumer.class);constructor.setAccessible(true);
   Class<?> analysis=Class.forName("ru.ilya.lecturerecorder.PhoneLectureAnalysis",true,loader);
   Method run=null;for(Method method:analysis.getDeclaredMethods())if(method.getName().equals("run"))run=method;
   run.setAccessible(true);
   int offset=options.getString("variant").equals("ilya")?1000:options.getString("variant").equals("stable")?2000:3000;
   for(int i=0;i<cases.length();i++) {
    JSONObject item=cases.getJSONObject(i);String file="lecture-2026-11-23-00-00-"+String.format(java.util.Locale.ROOT,"%06d",offset+i)+".wav";
    File folder=new File(context.getFilesDir(),"phone-notes");folder.mkdirs();File note=new File(folder,file+".json");
    JSONObject report=new JSONObject().put("segments",new JSONArray(item.getJSONArray("rows").toString())).put("subject","Контроль учебных цитат").put("local_summary_pending",true);
    JSONObject document=new JSONObject().put("file",file).put("report",report);
    Files.write(note.toPath(),document.toString().getBytes(StandardCharsets.UTF_8));
    ArrayList<String> stages=new ArrayList<>();Object job=constructor.newInstance((Consumer<String>)(value->stages.add(value)));
    JSONObject result=new JSONObject().put("name",item.getString("name"));long start=SystemClock.elapsedRealtime();
    try {
     if(run.getParameterTypes().length==6)run.invoke(null,context,job,file,"Контроль учебных цитат",false,true);
     else run.invoke(null,context,job,file,"Контроль учебных цитат",false);
     result.put("status","ready");
    } catch(InvocationTargetException error){Throwable cause=error.getCause();result.put("status","refused").put("error",String.valueOf(cause.getMessage()));}
    result.put("elapsed_ms",SystemClock.elapsedRealtime()-start).put("stages",new JSONArray(stages));
    result.put("report",new JSONObject(new String(Files.readAllBytes(note.toPath()),StandardCharsets.UTF_8)).getJSONObject("report"));
    results.put(result);Bundle update=new Bundle();update.putString("progress",options.getString("variant")+"/"+item.getString("name")+"/"+result.getString("status"));sendStatus(0,update);
   }
   output.putString("evidence",results.toString());finish(Activity.RESULT_OK,output);
  }catch(Throwable error){output.putString("error",android.util.Log.getStackTraceString(error));output.putString("partial",results.toString());finish(Activity.RESULT_CANCELED,output);}
 }
}'''

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('variant',choices=['ilya','stable','candidate']);parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--adb',type=Path,required=True)
    parser.add_argument('--serial',default='emulator-5590')
    parser.add_argument('--fixture',type=Path)
    parser.add_argument('--disposable-emulator',action='store_true',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    common=Path(subprocess.check_output(['git','rev-parse','--path-format=absolute','--git-common-dir'],text=True).strip()).parent
    folder=root/'work/summary-live/probe';folder.mkdir(parents=True,exist_ok=True)
    jdk=Path(os.environ['JAVA_HOME']);tools=Path(os.environ['ANDROID_BUILD_TOOLS']);platform=Path(os.environ['ANDROID_PLATFORM_JAR'])
    def execute(*command,**kw):return subprocess.run([str(v) for v in command],check=True,**kw)
    manifest='<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ru.clipmic.summarycompare"><uses-sdk android:minSdkVersion="26" android:targetSdkVersion="34"/><application android:label="Summary check"/><instrumentation android:name=".Probe" android:targetPackage="ru.ilya.lecturerecorder"/></manifest>'
    (folder/'AndroidManifest.xml').write_text(manifest);(folder/'Probe.java').write_text(PROBE)
    classes=folder/'classes';classes.mkdir(exist_ok=True);dex=folder/'dex';dex.mkdir(exist_ok=True)
    execute(tools/'aapt2','link','-I',platform,'--manifest',folder/'AndroidManifest.xml','-o',folder/'base.apk')
    execute(jdk/'bin/javac','--release','8','-encoding','UTF-8','-cp',platform,'-d',classes,folder/'Probe.java')
    execute(jdk/'bin/jar','cf',folder/'classes.jar','-C',classes,'.')
    execute(jdk/'bin/java','-cp',root/'work/android-deps/r8.jar','com.android.tools.r8.D8','--min-api','26','--lib',platform,'--output',dex,folder/'classes.jar')
    with zipfile.ZipFile(folder/'base.apk','a') as package:package.write(dex/'classes.dex','classes.dex')
    execute(tools/'zipalign','-f','4',folder/'base.apk',folder/'aligned.apk')
    env=dict(os.environ);env.setdefault('LECTURE_KEY_PASSWORD','android')
    execute(tools/'apksigner','sign','--ks',common/'work/android-tools/lectures.keystore','--ks-pass','env:LECTURE_KEY_PASSWORD','--out',folder/'probe.apk',folder/'aligned.apk',env=env)
    adb=[args.adb,'-s',args.serial]
    name=subprocess.check_output([str(v) for v in [*adb,'emu','avd','name']],text=True)
    if name.splitlines()[0]!='Motion0510':raise ValueError('Нужен отдельный тестовый эмулятор Motion0510')
    weights='/data/local/tmp/qa-summary-weights.litertlm'
    execute(*adb,'shell','sh','-c',"'test -f "+weights+" || cp /data/data/ru.ilya.lecturerecorder/files/phone-models/qwen3-0.6b-int4.litertlm "+weights+"'")
    checksum=subprocess.check_output([str(v) for v in [*adb,'shell','sha256sum',weights]],text=True).split()[0]
    if checksum!='bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0':raise ValueError('Неверная модель на стенде')
    execute(*adb,'uninstall','ru.ilya.lecturerecorder')
    execute(*adb,'install','-r','--no-incremental',args.apk)
    execute(*adb,'install','-r','--no-incremental',folder/'probe.apk')
    private='/data/data/ru.ilya.lecturerecorder/files'
    execute(*adb,'shell','mkdir','-p',private+'/phone-models')
    execute(*adb,'shell','cp',weights,private+'/phone-models/qwen3-0.6b-int4.litertlm')
    fixture=args.fixture or root/'tests/fixtures/summary/android-path.json'
    execute(*adb,'push',fixture,'/data/local/tmp/summary-compare.json')
    execute(*adb,'shell','cp','/data/local/tmp/summary-compare.json','/data/data/ru.ilya.lecturerecorder/files/qa-summary-comparison.json')
    owner=subprocess.check_output([str(v) for v in [*adb,'shell','stat','-c','%u:%g','/data/data/ru.ilya.lecturerecorder']],text=True).strip()
    execute(*adb,'shell','chown','-R',owner,private)
    owner=subprocess.check_output([str(v) for v in [*adb,'shell','stat','-c','%u:%g','/data/data/ru.ilya.lecturerecorder/files']],text=True).strip()
    execute(*adb,'shell','chown',owner,'/data/data/ru.ilya.lecturerecorder/files/qa-summary-comparison.json')
    execute(*adb,'shell','restorecon','/data/data/ru.ilya.lecturerecorder/files/qa-summary-comparison.json')
    log=args.output.with_suffix('.log');log.parent.mkdir(parents=True,exist_ok=True)
    command=[str(v) for v in [*adb,'shell','am','instrument','-w','-e','variant',args.variant,'ru.clipmic.summarycompare/.Probe']]
    with log.open('w') as stream:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        for line in process.stdout:
            stream.write(line);stream.flush()
            if 'progress=' in line:print(line.strip(),flush=True)
        if process.wait()!=0:raise RuntimeError('Сбой инструментирования')
    raw=log.read_text()
    if 'INSTRUMENTATION_CODE: -1' not in raw:raise RuntimeError(raw[-2000:])
    result=json.loads(raw.split('evidence=',1)[1].splitlines()[0])
    args.output.write_text(json.dumps(dict(kind='Живой штатный путь по готовому тексту, без аудио и ASR',variant=args.variant,
        apk_sha256=hashlib.sha256(args.apk.read_bytes()).hexdigest(),input_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
        model_sha256='bf1aba9ce8d963124407353c6aa4cbf72eba78db21ae133de983eac672ce83e0',
        unicode_source=(raw.split('unicode_source=',1)[1].splitlines()[0] if 'unicode_source=' in raw else None),results=result),ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':main()
