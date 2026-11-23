import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from test_phone_summary_state import STUBS,SOURCE,JSON_SHA256

HARNESS=r'''package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
public final class PathTest {
 static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
 static JSONObject select(JSONArray rows,String response)throws Exception{
  JSONArray points=new JSONArray(),sources=new JSONArray(),tasks=new JSONArray(),review=new JSONArray();
  PhoneSummarySelection.add(response,0,rows.length(),rows,points,sources,tasks,review,new HashSet<>(),new HashSet<>());
  return new JSONObject().put("summary",points).put("sources",sources).put("homework",tasks);
 }
 static void check(JSONObject item,JSONObject result)throws Exception{
  JSONArray rows=item.getJSONArray("rows"),points=result.getJSONArray("summary"),sources=result.getJSONArray("sources"),tasks=result.getJSONArray("homework");
  Set<Integer> academic=new HashSet<>(),assigned=new HashSet<>();
  for(int i=0;i<item.getJSONArray("academic_rows").length();i++)academic.add(item.getJSONArray("academic_rows").getInt(i));
  for(int i=0;i<item.getJSONArray("homework_rows").length();i++)assigned.add(item.getJSONArray("homework_rows").getInt(i));
  require(points.length()>=item.getInt("summary_min")&&points.length()<=4,"Полнота: "+item.getString("name"));
  require(tasks.length()==assigned.size(),"ДЗ: "+item.getString("name"));
  require(points.length()==sources.length(),"Потеряна цитата");
  for(JSONArray anchors:new JSONArray[]{sources,tasks})for(int i=0;i<anchors.length();i++){
   JSONObject anchor=anchors.getJSONObject(i);int index=anchor.getInt("segment_id");
   require((anchors==sources?academic:assigned).contains(index),"Неверная роль цитаты: "+item.getString("name"));
   JSONObject row=rows.getJSONObject(index);
   require(anchor.getString("quote").equals(row.getString("text"))&&anchor.getDouble("start")==row.getDouble("start")&&anchor.getDouble("end")==row.getDouble("end"),"Цифры, цитата или время изменились");
  }
 }
 public static void main(String[] args)throws Exception{
  JSONArray cases=new JSONObject(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8)).getJSONArray("cases");
  JSONArray results=new JSONArray();
  for(int i=0;i<cases.length();i++){
   JSONObject item=cases.getJSONObject(i);JSONArray rows=item.getJSONArray("rows");String before=rows.toString();
   for(String answer:new String[]{"","KEY: 1,2,3,4\nTASK: 1,2,3,4"}){
    JSONObject result=select(rows,answer);check(item,result);results.put(new JSONObject().put("name",item.getString("name")).put("response",answer).put("result",result));
    require(rows.toString().equals(before),"Изменён исходный текст");
   }
  }
  Context context=new Context(new File(args[1]));String name="lecture-2026-11-23-00-00-00-555555.wav";
  String quote="Икс не равен пяти.";
  JSONObject unicode=new JSONObject().put("segments",new JSONArray().put(new JSONObject().put("id",7).put("start",1).put("end",4).put("text","Икс\u00a0не\u2003равен\u0085пяти.\u001c")))
   .put("summary",new JSONArray().put(quote)).put("summary_evidence",new JSONArray().put(new JSONObject().put("quote",quote).put("segment_id",7).put("start",1).put("end",4)));
  SummarySources.reconcile(unicode,false,true);
  require(unicode.getJSONArray("summary_evidence").getJSONObject(0).getString("source_fingerprint").equals("96ef901c669bbe7404464ae8a4b6d7042df5d3e4a2139564526a6217d77ca32f"),"Unicode изменил общий отпечаток источника");
  String editedName="lecture-2026-11-23-00-00-00-666666.wav",original="Число девять не равно семи.";
  JSONObject edited=new JSONObject().put("file",editedName).put("report",new JSONObject().put("segments",new JSONArray().put(new JSONObject().put("text",original).put("start",0).put("end",4))));
  TranscriptEdits.Line line=new TranscriptEdits.Line(edited.getJSONObject("report").getJSONArray("segments").getJSONObject(0),0,true,new JSONObject());
  TranscriptEdits.save(context,editedName,line,1,"девяносто");
  PhoneSummarySelection.prepare(edited,TranscriptEdits.read(TranscriptEdits.file(context,editedName)));
  JSONObject corrected=edited.getJSONObject("report").getJSONArray("segments").getJSONObject(0);
  require(corrected.getString("text").equals("Число девяносто не равно семи.")&&corrected.getString("original_text").equals(original),"Ручная правка числа не передана разбору");
  JSONObject editedResult=select(edited.getJSONObject("report").getJSONArray("segments"),"");
  require(editedResult.getJSONArray("summary").getString(0).equals(corrected.getString("text"))&&editedResult.getJSONArray("sources").getJSONObject(0).getDouble("end")==4,"Конспект потерял исправленное число или время");
  JSONArray rows=cases.getJSONObject(2).getJSONArray("rows");
  PhoneSummaryProgress progress=PhoneSummaryProgress.open(context,name,rows);
  if(args[2].equals("write")){
   PhoneSummarySelection.add("",0,2,rows,progress.summary,progress.sources,progress.homework,progress.review,progress.points,progress.tasks);
   progress.checkpoint(2);require(progress.summary.length()==2,"Первый блок не сохранён");
  }else{
   require(progress.next==2&&progress.summary.length()==2,"Продолжение потеряло первый блок");
   PhoneSummarySelection.add("",progress.next,rows.length(),rows,progress.summary,progress.sources,progress.homework,progress.review,progress.points,progress.tasks);
   require(progress.summary.length()==2&&progress.homework.length()==1,"Продолжение повторило блок или потеряло ДЗ");
   progress.checkpoint(rows.length());
   for(String field:new String[]{"text","start","needs_review","speaker_role"}){
    JSONArray changed=new JSONArray(rows.toString());JSONObject row=changed.getJSONObject(0);
    if(field.equals("start"))row.put(field,0.5);else if(field.equals("needs_review"))row.put(field,true);else row.put(field,"Изменено");
    require(PhoneSummaryProgress.open(context,name,changed).next==0,"Старая версия блока пережила изменение "+field);
   }
   File saved=new File(new File(context.getFilesDir(),"phone-summary-progress"),name+".json");
   JSONObject broken=new JSONObject(Store.read(saved));broken.getJSONArray("sources").getJSONObject(0).put("quote","Выдумано 999");Store.write(saved,broken);
   require(PhoneSummaryProgress.open(context,name,rows).next==0,"Повреждённая цитата принята из контрольной точки");
   PhoneSummaryProgress.clear(context,name);require(!saved.exists(),"Контрольная точка не удалена");
  }
  Files.write(Paths.get(args[3]),results.toString(2).getBytes(StandardCharsets.UTF_8));
  System.out.println("PASS: "+cases.length()+" примеров × 2 ответа, точные цитаты, числа, роли и отдельный процесс "+args[2]);
 }
}'''

def main():
    root=Path(__file__).resolve().parents[1]
    jdk=Path(os.environ['JAVA_HOME'])/'bin'
    jar=Path(os.environ['ANDROID_JSON_JAR'])
    if hashlib.sha256(jar.read_bytes()).hexdigest()!=JSON_SHA256:raise ValueError('Неверный android-json')
    with tempfile.TemporaryDirectory(prefix='summary-path-') as folder:
        folder=Path(folder)
        for name,source in dict(STUBS,**{'PathTest.java':HARNESS}).items():(folder/name).write_text(source)
        names=['LectureNotes','Store','PhoneSummaryEvidence','PhonePhrases','TranscriptEdits','SummarySources','HomeworkEvidence','PhoneSummarySelection','PhoneSummaryProgress']
        subprocess.run([jdk/'javac','-encoding','UTF-8','-cp',jar,'-d',folder,*[SOURCE/(name+'.java') for name in names],*folder.glob('*.java')],check=True)
        target=root/'work/summary-live/fixed.json';target.parent.mkdir(exist_ok=True,parents=True)
        inputs=json.loads((root/'tests/fixtures/summary/android-path.json').read_text())
        inputs['cases']+=json.loads((root/'tests/fixtures/summary/android-speech-act.json').read_text())['cases']
        source=folder/'inputs.json';source.write_text(json.dumps(inputs,ensure_ascii=False))
        for phase in ['write','resume']:
            subprocess.run([jdk/'java','-cp',os.pathsep.join([str(folder),str(jar)]),'ru.ilya.lecturerecorder.PathTest',source,folder/'data',phase,target],check=True)

if __name__=='__main__':main()
