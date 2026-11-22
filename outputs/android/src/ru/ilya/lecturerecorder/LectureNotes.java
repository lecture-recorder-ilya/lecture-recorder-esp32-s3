package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.*;

final class LectureNotes {
 static final String SUMMARY_PENDING="local_summary_pending";
 static File root(Context c){File f=new File(c.getFilesDir(),"notes");f.mkdirs();return f;}
 static File file(Context c,String name,boolean local){return new File(local?localRoot(c):root(c),name+".json");}
 private static File localRoot(Context c){File f=new File(c.getFilesDir(),"phone-notes");f.mkdirs();return f;}

 static JSONObject saveTranscript(Context c,String name,String title,JSONObject document,
                                  JSONArray segments,String recognizer)throws Exception{
  if(segments.length()==0)throw new IOException("В записи не удалось распознать русскую речь");
  JSONObject lesson=Store.lesson(c,name);
  String subject=lesson.optString("subject",title);
  if(document==null){
   JSONObject report=new JSONObject().put("subject",subject).put("topic",subject);
   document=new JSONObject().put("report",report);
  }
  JSONObject report=document.getJSONObject("report");
  for(String field:new String[]{"summary","summary_evidence","homework","formulas","overview","warnings","draft"})report.remove(field);
  // Отметки проверки относятся к конкретной расшифровке.
  String reviewPrefix="phone:"+name+":"+UUID.randomUUID()+":";
  for(int i=0;i<segments.length();i++)segments.getJSONObject(i).put("review_key",reviewPrefix+i);
  document.put("file",name);
  if(lesson.length()>0)document.put("lesson",lesson);
  report.put("segments",segments).put("asr_engine",recognizer).put(SUMMARY_PENDING,true);
  saveLocal(c,document,true);
  return document;
 }

 static void saveSummary(Context c,JSONObject document)throws Exception{
  SummarySources.reconcile(document.getJSONObject("report"),true,true);
  document.getJSONObject("report").remove(SUMMARY_PENDING);
  saveLocal(c,document,false);
 }

 private static synchronized void saveLocal(Context c,JSONObject document,boolean archivePrevious)throws Exception{
  String name=document.getString("file");
  if(!valid(name))throw new IOException("Некорректное имя записи");
  File target=file(c,name,true);
  if(archivePrevious&&target.isFile()){
   File history=new File(new File(c.getFilesDir(),"phone-note-history"),name);
   if(!history.isDirectory()&&!history.mkdirs())throw new IOException("Не удалось сохранить предыдущую расшифровку");
   // При повторной попытке используем уже сохранённую копию.
   File archived=new File(history,Store.hash(target)+".json");
   if(!archived.isFile()){
    File part=new File(archived.getPath()+".tmp");
    try{
     try(FileInputStream input=new FileInputStream(target);FileOutputStream output=new FileOutputStream(part)){
      byte[] buffer=new byte[65536];
      for(int size;(size=input.read(buffer))!=-1;)output.write(buffer,0,size);
      output.getFD().sync();
     }
     Files.move(part.toPath(),archived.toPath(),StandardCopyOption.ATOMIC_MOVE);
    }finally{
     part.delete();
    }
   }
  }
  Store.write(target,document);
 }
 static boolean valid(String n){return n!=null&&n.matches("lecture-[0-9-]+\\.wav");}
 static synchronized JSONObject index(Context c)throws Exception{
  JSONObject j=new JSONObject();File[] fs=root(c).listFiles(f->f.getName().endsWith(".wav.json"));
  if(fs!=null)for(File f:fs)j.put(f.getName().replaceFirst("\\.json$",""),Store.hash(f));return j;
 }
 static final class RevisionConflict extends IOException {
  RevisionConflict() { super("На телефоне уже сохранена другая или более новая версия"); }
 }
 private static long revision(JSONObject note) throws IOException {
  if (!note.has("sync_revision")) return 0;
  Object value = note.opt("sync_revision");
  if (!(value instanceof String) || !((String)value).matches("[1-9][0-9]{0,17}"))
   throw new IOException("Некорректная версия текста");
  return Long.parseLong((String)value);
 }
 static synchronized String save(Context c,byte[] body)throws Exception{
  if(body.length>2*1024*1024)throw new IOException("Текст слишком большой");
  JSONObject j=new JSONObject(new String(body,StandardCharsets.UTF_8));String name=j.getString("file");
  if(!valid(name)||!j.has("report"))throw new IOException("Некорректный текст лекции");j.getJSONObject("report");
  File target=new File(root(c),name+".json"),tmp=new File(root(c),name+".tmp");
  long next = revision(j);
  if (target.isFile()) {
   byte[] stored = Files.readAllBytes(target.toPath());
   long current = revision(new JSONObject(new String(stored, StandardCharsets.UTF_8)));
   if (current > 0 && next <= current) {
    if (next == current && Arrays.equals(stored, body)) return Store.hash(target);
    throw new RevisionConflict();
   }
  }
  try(FileOutputStream out=new FileOutputStream(tmp)){out.write(body);out.getFD().sync();}
  if(!tmp.renameTo(target))throw new IOException("Текст не сохранён");return Store.hash(target);
 }
 static File[] files(Context c,boolean local){File[] fs=(local?localRoot(c):root(c)).listFiles(f->f.getName().endsWith(".wav.json"));if(fs==null)return new File[0];Arrays.sort(fs,Collections.reverseOrder());return fs;}
 static String title(JSONObject value){JSONObject r=value.optJSONObject("report"),m=value.optJSONObject("lesson");String subject=r.optString("subject",m==null?"":m.optString("subject"));String date=m==null?"":m.optString("date");return subject.isEmpty()?value.optString("file"):subject+(date.isEmpty()?"":" · "+date);}
 static String text(JSONObject v)throws Exception{return text(v,true);}
 static String summary(JSONObject v)throws Exception{return text(v,false);}
 private static String text(JSONObject v,boolean includeTranscript)throws Exception{
  JSONObject r=v.getJSONObject("report"),m=v.optJSONObject("lesson");StringBuilder s=new StringBuilder();
  if(r.optBoolean("draft"))s.append("Предварительная расшифровка · может содержать ошибки\n\n");
  s.append(r.optString("topic",title(v))).append("\n");
  if(m!=null)s.append(m.optString("date")).append("\n");
  String teacher=r.optString("teacher",m==null?"":m.optString("teacher"));if(!teacher.isEmpty())s.append("Преподаватель: ").append(teacher).append("\n");
  if(!r.optString("overview").isEmpty())s.append("\n").append(r.optString("overview")).append("\n");
  JSONArray summary=r.optJSONArray("summary");if(summary!=null&&summary.length()>0){s.append("\nКонспект\n");for(int i=0;i<summary.length();i++)s.append("• ").append(summary.get(i)).append("\n");}
  JSONArray rows=includeTranscript?r.optJSONArray("segments"):null;if(includeTranscript)s.append("\nПолный текст\n");if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);s.append("[").append((row.has("start")?LectureReaderActivity.clock(row.optDouble("start")):"Без таймкода")).append("] ");if(row.optBoolean("needs_review"))s.append("Проверь по аудио · ");s.append(row.optString("text")).append("\n\n");}
  JSONArray tasks=r.optJSONArray("homework");if(tasks!=null&&tasks.length()>0){s.append("\nЗадания из записи\n");for(int i=0;i<tasks.length();i++){JSONObject task=tasks.optJSONObject(i);if(task==null)continue;s.append("• ").append(task.optString("task"));String deadline=task.optString("deadline");if(!deadline.isEmpty())s.append(" · ").append(deadline);s.append("\n");String quote=task.optString("quote");if(!quote.isEmpty())s.append("Основание: «").append(quote).append("»\n");}}
  JSONArray warnings=r.optJSONArray("warnings");if(warnings!=null&&warnings.length()>0){s.append("\nПримечания\n");for(int i=0;i<warnings.length();i++)s.append("• ").append(warnings.optString(i)).append("\n");}
  return s.toString();
 }
}
