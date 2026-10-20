package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.security.MessageDigest;
import java.util.*;

final class Store {
 static File root(Context c){File f=new File(c.getFilesDir(),"recordings");f.mkdirs();return f;}
 static File library(Context c){File f=new File(c.getFilesDir(),"library-audio");f.mkdirs();return f;}
 static void header(RandomAccessFile f,long bytes)throws IOException{
  f.seek(0);f.writeBytes("RIFF");le(f,bytes+36,4);f.writeBytes("WAVEfmt ");le(f,16,4);le(f,1,2);le(f,1,2);le(f,16000,4);le(f,32000,4);le(f,2,2);le(f,16,2);f.writeBytes("data");le(f,bytes,4);
 }
 static void le(RandomAccessFile f,long n,int count)throws IOException{for(int i=0;i<count;i++)f.write((int)(n>>(8*i))&255);}
 static String hash(File f)throws Exception{MessageDigest d=MessageDigest.getInstance("SHA-256");try(InputStream in=new FileInputStream(f)){byte[] b=new byte[65536];int n;while((n=in.read(b))>0)d.update(b,0,n);}StringBuilder s=new StringBuilder();for(byte v:d.digest())s.append(String.format(Locale.US,"%02x",v&255));return s.toString();}
 static boolean transferable(String name){return name.matches("lecture-[0-9-]+\\.wav|board-[0-9]{13}-[a-f0-9]{32}\\.jpg");}
 static File file(Context c,String name)throws IOException{if(!transferable(name))throw new IOException("Некорректное имя записи");return new File(root(c),name);}
 static synchronized void seal(File part)throws Exception{
  if(part.length()<44)throw new IOException("Незавершённый заголовок WAV");
  try(RandomAccessFile f=new RandomAccessFile(part,"rw")){long n=(f.length()-44)/2*2;f.setLength(44+n);header(f,n);f.getFD().sync();}
  File target=new File(part.getParentFile(),part.getName().replace(".part",".wav"));if(target.exists()||!part.renameTo(target))throw new IOException("Не удалось сохранить WAV");
  File meta=new File(part.getPath()+".json");if(meta.exists()&&!meta.renameTo(new File(target.getPath()+".json")))throw new IOException("Метаданные записи не сохранены");
 }
 static void recover(Context c)throws Exception{File[] fs=root(c).listFiles();if(fs!=null)for(File f:fs)if(f.getName().endsWith(".part"))seal(f);BoardPhotos.recover(c);}
 static synchronized JSONArray list(Context c)throws Exception{
  JSONArray a=new JSONArray();File[] fs=root(c).listFiles();if(fs!=null){Arrays.sort(fs);for(File f:fs)if(transferable(f.getName())){
   File meta=new File(f.getPath()+".json");JSONObject j=meta.exists()?new JSONObject(read(meta)):new JSONObject();
   j.put("name",f.getName()).put("bytes",f.length()).put("sha256",hash(f)).put("seconds",Math.max(0,f.length()-44)/32000.0);if(f.getName().startsWith("board-"))j.put("kind","board_photo");a.put(j);
  }}return a;
 }
 static String read(File f)throws IOException{try(InputStream i=new FileInputStream(f);ByteArrayOutputStream o=new ByteArrayOutputStream()){byte[] b=new byte[8192];int n;while((n=i.read(b))>0)o.write(b,0,n);return o.toString("UTF-8");}}
 static void write(File f,JSONObject j)throws IOException{File temp=new File(f.getPath()+".tmp");try(FileOutputStream o=new FileOutputStream(temp)){o.write(j.toString().getBytes("UTF-8"));o.getFD().sync();}if(!temp.renameTo(f))throw new IOException("Не удалось сохранить метаданные");}
 static synchronized void acknowledge(Context c,String name,String digest)throws Exception{File f=file(c,name);if(!f.exists())return;if(!hash(f).equals(digest))throw new IOException("Контрольная сумма отличается");if(name.endsWith(".wav")&&c.getSharedPreferences("settings",0).getBoolean("keep_audio_copy",true)){File saved=new File(library(c),name);if(saved.exists()){if(!hash(saved).equals(digest))throw new IOException("Аудиокопия в библиотеке отличается");if(!f.delete())throw new IOException("Не удалось завершить перенос в библиотеку");}else if(!f.renameTo(saved))throw new IOException("Не удалось сохранить аудиокопию для прослушивания");}else if(!f.delete())throw new IOException("Не удалось удалить подтверждённую копию");new File(f.getPath()+".json").delete();if(name.startsWith("board-")){String id=name.substring(name.lastIndexOf('-')+1,name.length()-4);new File(BoardPhotos.camera(c),id+".jpg").delete();new File(BoardPhotos.camera(c),id+".json").delete();}}
}
