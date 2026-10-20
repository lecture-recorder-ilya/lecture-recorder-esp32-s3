package ru.ilya.lecturerecorder;

import android.content.Context;
import org.json.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.*;

final class LectureNotes {
 static File root(Context c){File f=new File(c.getFilesDir(),"notes");f.mkdirs();return f;}
 static boolean valid(String n){return n!=null&&n.matches("lecture-[0-9-]+\\.wav");}
 static synchronized JSONObject index(Context c)throws Exception{
  JSONObject j=new JSONObject();File[] fs=root(c).listFiles(f->f.getName().endsWith(".wav.json"));
  if(fs!=null)for(File f:fs)j.put(f.getName().replaceFirst("\\.json$",""),Store.hash(f));return j;
 }
 static synchronized String save(Context c,byte[] body)throws Exception{
  if(body.length>2*1024*1024)throw new IOException("Текст слишком большой");
  JSONObject j=new JSONObject(new String(body,StandardCharsets.UTF_8));String name=j.getString("file");
  if(!valid(name)||!j.has("report"))throw new IOException("Некорректный текст лекции");j.getJSONObject("report");
  File target=new File(root(c),name+".json"),tmp=new File(root(c),name+".tmp");
  try(FileOutputStream out=new FileOutputStream(tmp)){out.write(body);out.getFD().sync();}
  if(!tmp.renameTo(target))throw new IOException("Текст не сохранён");return Store.hash(target);
 }
 static File[] files(Context c){File[] fs=root(c).listFiles(f->f.getName().endsWith(".wav.json"));if(fs==null)return new File[0];Arrays.sort(fs,Collections.reverseOrder());return fs;}
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
