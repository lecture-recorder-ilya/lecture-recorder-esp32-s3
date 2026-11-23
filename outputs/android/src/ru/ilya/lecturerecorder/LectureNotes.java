package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.*;
import java.security.MessageDigest;

final class LectureNotes {
 static final String SUMMARY_PENDING="local_summary_pending";
 static File root(Context c){File f=new File(c.getFilesDir(),"notes");f.mkdirs();return f;}
 static File file(Context c,String name,boolean local){return new File(local?localRoot(c):root(c),name+".json");}
 private static File localRoot(Context c){File f=new File(c.getFilesDir(),"phone-notes");f.mkdirs();return f;}

 static JSONObject saveTranscript(Context c,String name,String title,JSONObject document,
                                  JSONArray segments,String recognizer)throws Exception{
  document=prepareTranscript(c,name,title,document,segments,recognizer);
  saveLocal(c,document,true);
  return document;
 }

 static JSONObject prepareTranscript(Context c,String name,String title,JSONObject document,
                                     JSONArray segments,String recognizer)throws Exception{
  if(segments.length()==0)throw new IOException("В записи не удалось распознать русскую речь");
  JSONObject lesson=Store.lesson(c,name);
  String subject=lesson.optString("subject",title);
  if(document==null){
   JSONObject report=new JSONObject().put("subject",subject).put("topic",subject);
   document=new JSONObject().put("report",report);
  }
  JSONObject report=document.getJSONObject("report");
  for(String field:new String[]{"summary","summary_evidence","homework","homework_review","formulas","formula_review","overview","warnings","draft"})report.remove(field);
  // Отметки проверки относятся к конкретной расшифровке.
  String reviewPrefix="phone:"+name+":"+UUID.randomUUID()+":";
  for(int i=0;i<segments.length();i++)segments.getJSONObject(i).put("review_key",reviewPrefix+i).put("edit_generation",reviewPrefix);
  document.put("file",name);
  if(lesson.length()>0)document.put("lesson",lesson);
  report.put("segments",segments).put("asr_engine",recognizer).put(SUMMARY_PENDING,true);
  return document;
 }

 static void saveSummary(Context c,JSONObject document)throws Exception{
  saveSummary(c,document,false);
 }

 static void saveSummary(Context c,JSONObject document,boolean archivePrevious)throws Exception{
  SummarySources.reconcile(document.getJSONObject("report"),true,true);
  document.getJSONObject("report").remove(SUMMARY_PENDING);
  saveLocal(c,document,archivePrevious);
 }

 private static synchronized void saveLocal(Context c,JSONObject document,boolean archivePrevious)throws Exception{
  String name=document.getString("file");
  if(!valid(name))throw new IOException("Некорректное имя записи");
  File target=file(c,name,true);
  if(archivePrevious&&target.isFile())archive(c,name,target);
  Store.write(target,document);
 }
 private static File historyRoot(Context c,String name){return new File(new File(c.getFilesDir(),"phone-note-history"),name);}
 private static String historyId(byte[] document,byte[] edits)throws Exception{
  MessageDigest hash=MessageDigest.getInstance("SHA-256");hash.update(document);hash.update((byte)0);hash.update(edits);
  StringBuilder id=new StringBuilder();for(byte b:hash.digest())id.append(String.format(Locale.ROOT,"%02x",b&255));return id.toString();
 }
 private static void historyFile(File target,byte[] bytes)throws Exception{
  if(target.isFile()){if(!Arrays.equals(Files.readAllBytes(target.toPath()),bytes))throw new IOException("Архив конспекта повреждён");return;}
  File part=new File(target.getPath()+".tmp");
  try{
   try(FileOutputStream out=new FileOutputStream(part)){out.write(bytes);out.getFD().sync();}
   Files.move(part.toPath(),target.toPath(),StandardCopyOption.ATOMIC_MOVE);
  }finally{part.delete();}
 }
 private static void archive(Context c,String name,File target)throws Exception{
  File folder=historyRoot(c,name);if(!folder.isDirectory()&&!folder.mkdirs())throw new IOException("Не удалось сохранить предыдущий конспект");
  File edits=TranscriptEdits.file(c,name);byte[] document=Files.readAllBytes(target.toPath());
  byte[] corrections=edits.isFile()?Files.readAllBytes(edits.toPath()):"{}".getBytes(StandardCharsets.UTF_8);
  String id=historyId(document,corrections);
  historyFile(new File(folder,id+".json"),document);historyFile(new File(folder,id+".edits.json"),corrections);
 }
 static JSONArray history(Context c,String name)throws Exception{
  if(!valid(name))throw new IOException("Некорректное имя записи");JSONArray result=new JSONArray();
  File[] files=historyRoot(c,name).listFiles(f->f.getName().matches("[0-9a-f]{64}\\.json"));
  if(files!=null){Arrays.sort(files);for(File file:files)result.put(file.getName().substring(0,64));}return result;
 }
 static synchronized JSONObject restore(Context c,String name,String revision)throws Exception{
  if(!valid(name)||!revision.matches("[0-9a-f]{64}"))throw new IOException("Некорректная версия конспекта");
  File folder=historyRoot(c,name),source=new File(folder,revision+".json"),edits=new File(folder,revision+".edits.json");
  byte[] bytes=Files.readAllBytes(source.toPath()),corrections=edits.isFile()?Files.readAllBytes(edits.toPath()):"{}".getBytes(StandardCharsets.UTF_8);
  if(!(edits.isFile()?historyId(bytes,corrections):Store.hash(source)).equals(revision))throw new IOException("Архив конспекта повреждён");
  JSONObject document=new JSONObject(new String(bytes,StandardCharsets.UTF_8));
  if(!name.equals(document.getString("file")))throw new IOException("Версия относится к другой записи");
  TranscriptEdits.apply(document,new JSONObject(new String(corrections,StandardCharsets.UTF_8)),true);
  JSONArray rows=document.getJSONObject("report").optJSONArray("segments");String generation=UUID.randomUUID().toString();
  if(rows!=null)for(int i=0;i<rows.length();i++)rows.getJSONObject(i).put("edit_generation",generation);
  document.put("restored_from",revision);saveLocal(c,document,true);return document;
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
  SummarySources.reconcile(r,false,false);
  if(v.has("restored_from"))s.append("Восстановленная версия: ").append(v.getString("restored_from")).append("\n");
  if(r.optBoolean("draft"))s.append("Предварительная расшифровка · может содержать ошибки\n\n");
  s.append(r.optString("topic",title(v))).append("\n");
  if(m!=null)s.append(m.optString("date")).append("\n");
  String teacher=r.optString("teacher",m==null?"":m.optString("teacher"));if(!teacher.isEmpty())s.append("Преподаватель: ").append(teacher).append("\n");
  if(!r.optString("overview").isEmpty())s.append("\n").append(r.optString("overview")).append("\n");
  JSONArray summary=r.optJSONArray("summary"),sources=r.optJSONArray("summary_evidence");
  if(summary!=null&&summary.length()>0){s.append("\nКонспект\n");for(int i=0;i<summary.length();i++){
   s.append("• ").append(summary.get(i)).append("\n");if(sources!=null&&sources.optJSONObject(i)!=null)source(s,sources.getJSONObject(i));
  }}
  JSONArray rows=includeTranscript?r.optJSONArray("segments"):null;if(includeTranscript)s.append("\nПолный текст\n");if(rows!=null)for(int i=0;i<rows.length();i++){JSONObject row=rows.getJSONObject(i);s.append("[").append((row.has("start")?LectureReaderActivity.clock(row.optDouble("start")):"Без таймкода")).append("] ");if(row.optBoolean("needs_review"))s.append("Проверь по аудио · ");s.append(row.optString("text")).append("\n\n");}
  JSONArray tasks=r.optJSONArray("homework");if(tasks!=null&&tasks.length()>0){s.append("\nЗадания из записи\n");for(int i=0;i<tasks.length();i++){JSONObject task=tasks.optJSONObject(i);if(task==null)continue;s.append("• ").append(task.optString("task"));String deadline=task.optString("deadline");if(!deadline.isEmpty())s.append(" · ").append(deadline);s.append("\n");source(s,task);}}
  JSONArray formulas=r.optJSONArray("formulas");if(formulas!=null)for(int i=0;i<formulas.length();i++){
   JSONObject formula=formulas.optJSONObject(i);if(formula==null)continue;
   s.append(formula.optString("verification_status").equals("confirmed")?"Формула: ":"Формулу нужно сверить: ").append(formula.optString("latex")).append("\n");source(s,formula);
  }
  for(String field:new String[]{"formula_review","homework_review"}){
   JSONArray pending=r.optJSONArray(field);if(pending==null)continue;
   for(int i=0;i<pending.length();i++){JSONObject item=pending.optJSONObject(i);if(item!=null){s.append(item.optString("review_note","Нужно сверить.")).append("\n");source(s,item);}}
  }
  JSONArray warnings=r.optJSONArray("warnings");if(warnings!=null&&warnings.length()>0){s.append("\nПримечания\n");for(int i=0;i<warnings.length();i++)s.append("• ").append(warnings.optString(i)).append("\n");}
  return s.toString();
 }
 private static String time(double value){long ms=Math.round(value*1000);return String.format(Locale.ROOT,"%d:%02d.%03d",ms/60000,(ms/1000)%60,ms%1000);}
 private static void source(StringBuilder text,JSONObject item){
  if(item.has("start")&&item.has("end")&&!item.optString("source_status").equals("needs_review"))text.append("Источник [").append(time(item.optDouble("start"))).append("–").append(time(item.optDouble("end"))).append("]: «").append(item.optString("quote")).append("»\n");
  else if(!item.optString("quote").isEmpty())text.append("Неподтверждённая цитата: «").append(item.optString("quote")).append("». Источник нужно сверить.\n");
  JSONObject old=item.optJSONObject("original_source");
  if(old!=null&&old.has("start")&&old.has("end")&&(old.optDouble("start")!=item.optDouble("start",-1)||old.optDouble("end")!=item.optDouble("end",-1)))text.append("Исходная привязка [").append(time(old.optDouble("start"))).append("–").append(time(old.optDouble("end"))).append("]; до повторной сверки.\n");
 }
}
