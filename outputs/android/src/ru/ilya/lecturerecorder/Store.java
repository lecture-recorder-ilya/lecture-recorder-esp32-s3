package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

final class Store {
 static File root(Context c){File f=new File(c.getFilesDir(),"recordings");f.mkdirs();return f;}
 static File library(Context c){File f=new File(c.getFilesDir(),"library-audio");f.mkdirs();return f;}
 static File audio(Context c,String name){File pending=new File(root(c),name);return pending.isFile()?pending:new File(library(c),name);}
 static Collection<File> audioFiles(Context c){
  SortedMap<String,File> audio=new TreeMap<>(Collections.reverseOrder());
  File pending=root(c);
  for(File folder:new File[]{library(c),pending}){
   File[] found=folder.listFiles(f->LectureNotes.valid(f.getName())&&f.isFile());
   if(found!=null)for(File file:found){
    try{if(folder.equals(pending)&&readObject(new File(file.getPath()+".json")).optBoolean("awaiting_lesson"))continue;}
    catch(Exception ignored){}
    audio.put(file.getName(),file);
   }
  }
  return audio.values();
 }
 static String recordingTitle(Context c,String file){
  try{
   String title=lesson(c,file).optString("subject");
   if(!title.isEmpty())return title+" · "+recordingTitle(file);
  }catch(Exception ignored){}
  return recordingTitle(file);
 }
 static String recordingTitle(String file){
  String name=file.substring("lecture-".length(),file.length()-".wav".length());
  try {
   java.text.SimpleDateFormat parser=new java.text.SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);
   parser.setLenient(false);
   parser.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));
   Date date=parser.parse(name.substring(0,19));
   java.text.SimpleDateFormat label=new java.text.SimpleDateFormat("d MMMM · HH:mm",new Locale("ru"));
   label.setTimeZone(parser.getTimeZone());
   return label.format(date);
  }catch(Exception error){return name;}
 }
 static synchronized RandomAccessFile openAudio(Context c,String name)throws IOException{
  if(!LectureNotes.valid(name))throw new IOException("Некорректное имя записи");
  File source=audio(c,name);
  if(!source.isFile())throw new IOException("Аудиокопия на телефоне недоступна");
  return new RandomAccessFile(source,"r");
 }
 static void header(RandomAccessFile f,long bytes)throws IOException{
  f.seek(0);f.writeBytes("RIFF");le(f,bytes+36,4);f.writeBytes("WAVEfmt ");le(f,16,4);le(f,1,2);le(f,1,2);le(f,16000,4);le(f,32000,4);le(f,2,2);le(f,16,2);f.writeBytes("data");le(f,bytes,4);
 }
 static void le(RandomAccessFile f,long n,int count)throws IOException{for(int i=0;i<count;i++)f.write((int)(n>>(8*i))&255);}
 static String hash(File f)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(f)){byte[] b=new byte[65536];int n;while((n=in.read(b))>0)d.update(b,0,n);}StringBuilder s=new StringBuilder();for(byte v:d.digest())s.append(String.format(Locale.US,"%02x",v&255));return s.toString();}
 static boolean transferable(String name){return name.matches("lecture-[0-9-]+\\.wav|board-[0-9]{13}-[a-f0-9]{32}\\.jpg");}
 static File file(Context c,String name)throws IOException{if(!transferable(name))throw new IOException("Некорректное имя записи");return new File(root(c),name);}
 static synchronized File transferFile(Context c,String name)throws Exception{
  File wav=file(c,name);
  return wav.isFile()&&!readObject(new File(wav.getPath()+".json")).optBoolean("awaiting_lesson")?wav:null;
 }
 static synchronized void seal(File part)throws Exception{
  if(part.length()<44)throw new IOException("Незавершённый заголовок WAV");
  try(RandomAccessFile f=new RandomAccessFile(part,"rw")){long n=(f.length()-44)/2*2;f.setLength(44+n);header(f,n);f.getFD().sync();}
  File target=new File(part.getParentFile(),part.getName().replace(".part",".wav"));if(target.exists()||!part.renameTo(target))throw new IOException("Не удалось сохранить WAV");
  File meta=new File(part.getPath()+".json");if(meta.exists()&&!meta.renameTo(new File(target.getPath()+".json")))throw new IOException("Метаданные записи не сохранены");
 }
 static synchronized void recover(Context c)throws Exception{
  File[] files=root(c).listFiles();
  if(files!=null)for(File file:files){
   String name=file.getName();
   if(name.endsWith(".part")){
    if(file.length()>44)seal(file);
    else if(file.delete())new File(file.getPath()+".json").delete();
   }else if(name.endsWith(".part.json")){
    String base=name.substring(0,name.length()-".part.json".length());
    File target=new File(root(c),base+".wav");
    File metadata=new File(target.getPath()+".json");
    if(target.isFile()&&!metadata.exists()&&!file.renameTo(metadata))throw new IOException("Не удалось восстановить метаданные");
   }
  }
  BoardPhotos.recover(c);
 }
 static synchronized JSONArray list(Context c)throws Exception{
  JSONArray a=new JSONArray();File[] fs=root(c).listFiles();if(fs!=null){Arrays.sort(fs);for(File f:fs)if(transferable(f.getName())){
   File meta=new File(f.getPath()+".json");JSONObject j=meta.exists()?new JSONObject(read(meta)):new JSONObject();
   if(j.optBoolean("awaiting_lesson"))continue;
   j.put("name",f.getName()).put("bytes",f.length()).put("sha256",hash(f)).put("seconds",Math.max(0,f.length()-44)/32000.0);if(f.getName().startsWith("board-"))j.put("kind","board_photo");a.put(j);
  }}return a;
 }
 static JSONObject readObject(File f)throws Exception{return f.isFile()?new JSONObject(read(f)):new JSONObject();}
 static JSONObject lesson(Context c,String name)throws Exception{return readObject(lessonFile(c,name));}
 static File lessonFile(Context c,String name){
  File directory=new File(c.getFilesDir(),"recording-lessons");
  directory.mkdirs();
  return new File(directory,name+".json");
 }
 static synchronized String pendingLesson(Context c){
  File[] files=root(c).listFiles(f->LectureNotes.valid(f.getName())&&f.isFile());
  if(files==null)return "";
  Arrays.sort(files,Collections.reverseOrder());
  for(File f:files){
   try{if(readObject(new File(f.getPath()+".json")).optBoolean("awaiting_lesson"))return f.getName();}
   catch(Exception ignored){}
  }
  return "";
 }
 static synchronized JSONObject pendingMetadata(Context c,String name)throws Exception{
  if(!LectureNotes.valid(name)||!file(c,name).isFile())throw new IOException("Запись не найдена");
  JSONObject metadata=readObject(new File(file(c,name).getPath()+".json"));
  if(!metadata.optBoolean("awaiting_lesson"))throw new IOException("Запись уже обработана");
  return metadata;
 }
 static synchronized void finishLesson(Context c,String name,JSONObject lesson)throws Exception{
  JSONObject metadata=pendingMetadata(c,name);
  if(lesson!=null){
   write(lessonFile(c,name),lesson);
   metadata.put("lesson",lesson);
  }else{
   File previous=lessonFile(c,name);
   if(previous.exists()&&!previous.delete())throw new IOException("Не удалось очистить сведения о паре");
   metadata.remove("lesson");
  }
  metadata.put("lesson_decided",true);
  metadata.remove("awaiting_lesson");
  write(new File(file(c,name).getPath()+".json"),metadata);
 }
 static synchronized void discardLesson(Context c,String name)throws Exception{
  pendingMetadata(c,name);
  File wav=file(c,name);
  if(!wav.delete())throw new IOException("Не удалось удалить запись");
  new File(wav.getPath()+".json").delete();
  lessonFile(c,name).delete();
 }
 static String read(File f)throws IOException{try(InputStream i=new FileInputStream(f);ByteArrayOutputStream o=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=i.read(b))>0)o.write(b,0,n);return o.toString("UTF-8");}}
 static void write(File f,JSONObject j)throws IOException{File temp=new File(f.getPath()+".tmp");try(FileOutputStream o=new FileOutputStream(temp)){o.write(j.toString().getBytes("UTF-8"));o.getFD().sync();}if(!temp.renameTo(f))throw new IOException("Не удалось сохранить метаданные");}
 static synchronized void acknowledge(Context c,String name,String digest)throws Exception{File f=file(c,name);if(!f.exists())return;if(readObject(new File(f.getPath()+".json")).optBoolean("awaiting_lesson"))throw new IOException("Нужно выбрать пару");if(!hash(f).equals(digest))throw new IOException("Контрольная сумма отличается");if(name.endsWith(".wav")&&c.getSharedPreferences("settings",0).getBoolean("keep_audio_copy",true)){File saved=new File(library(c),name);if(saved.exists()){if(!hash(saved).equals(digest))throw new IOException("Аудиокопия в библиотеке отличается");if(!f.delete())throw new IOException("Не удалось завершить перенос в библиотеку");}else if(!f.renameTo(saved))throw new IOException("Не удалось сохранить аудиокопию для прослушивания");}else if(!f.delete())throw new IOException("Не удалось удалить подтверждённую копию");new File(f.getPath()+".json").delete();if(name.startsWith("board-")){String id=name.substring(name.lastIndexOf('-')+1,name.length()-4);new File(BoardPhotos.camera(c),id+".jpg").delete();new File(BoardPhotos.camera(c),id+".json").delete();}}
}
