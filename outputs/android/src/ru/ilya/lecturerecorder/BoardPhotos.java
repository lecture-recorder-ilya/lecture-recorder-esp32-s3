package ru.ilya.lecturerecorder;
import android.content.Context;
import android.graphics.*;
import android.media.ExifInterface;
import org.json.JSONObject;
import java.io.*;
import java.text.SimpleDateFormat;
import java.util.*;

final class BoardPhotos {
 static File camera(Context c){File f=new File(c.getFilesDir(),"camera");f.mkdirs();return f;}
 static String prepare(Context c)throws Exception{
  String id=UUID.randomUUID().toString().replace("-","");File file=new File(camera(c),id+".jpg");try(FileOutputStream out=new FileOutputStream(file)){out.getFD().sync();}
  JSONObject meta=new JSONObject().put("launched_ms",System.currentTimeMillis());if(CaptureService.recording&&!CaptureService.current.isEmpty())meta.put("source_recording",CaptureService.current).put("launch_offset_seconds",CaptureService.samples/16000.0);
  Store.write(new File(camera(c),id+".json"),meta);return id;
 }
 static void markReady(Context c,String id)throws Exception{File meta=new File(camera(c),id+".json");JSONObject j=new JSONObject(Store.read(meta));j.put("ready",true);Store.write(meta,j);}
 static void recover(Context c){File[] metadata=camera(c).listFiles(f->f.getName().matches("[a-f0-9]{32}\\.json"));if(metadata!=null)for(File meta:metadata)try{JSONObject j=new JSONObject(Store.read(meta));if(j.optBoolean("ready",false))finish(c,meta.getName().replace(".json",""));}catch(Exception ignored){}}
 static void cancel(Context c,String id){if(id!=null&&id.matches("[a-f0-9]{32}")){new File(camera(c),id+".jpg").delete();new File(camera(c),id+".json").delete();}}
 static synchronized void finish(Context c,String id)throws Exception{
  if(id==null||!id.matches("[a-f0-9]{32}"))throw new IOException("Фото не найдено");
  File original=new File(camera(c),id+".jpg");JSONObject meta=new JSONObject(Store.read(new File(camera(c),id+".json")));long now=System.currentTimeMillis(),captured=now;
  File[] ready=Store.root(c).listFiles(f->f.getName().endsWith("-"+id+".jpg"));if(ready!=null&&ready.length>0)return;
  ExifInterface exif=new ExifInterface(original.getPath());String date=exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL);boolean exact=false;
  if(date!=null)try{long value=new SimpleDateFormat("yyyy:MM:dd HH:mm:ss",Locale.US).parse(date).getTime();if(value>=meta.getLong("launched_ms")-2000&&value<=now+2000){captured=value;exact=true;}}catch(Exception ignored){}
  BitmapFactory.Options bounds=new BitmapFactory.Options();bounds.inJustDecodeBounds=true;BitmapFactory.decodeFile(original.getPath(),bounds);if(bounds.outWidth<=0||bounds.outHeight<=0)throw new IOException("Камера не сохранила изображение");
  BitmapFactory.Options opts=new BitmapFactory.Options();opts.inSampleSize=1;while(Math.max(bounds.outWidth,bounds.outHeight)/opts.inSampleSize>4096)opts.inSampleSize*=2;
  Bitmap image=BitmapFactory.decodeFile(original.getPath(),opts);if(image==null)throw new IOException("Не удалось открыть фото");Matrix matrix=new Matrix();int orientation=exif.getAttributeInt(ExifInterface.TAG_ORIENTATION,1);
  if(orientation==6)matrix.postRotate(90);if(orientation==3)matrix.postRotate(180);if(orientation==8)matrix.postRotate(270);if(orientation==2)matrix.postScale(-1,1);if(orientation==4)matrix.postScale(1,-1);if(orientation==5){matrix.postScale(-1,1);matrix.postRotate(90);}if(orientation==7){matrix.postScale(-1,1);matrix.postRotate(270);}
  if(!matrix.isIdentity()){Bitmap adjusted=Bitmap.createBitmap(image,0,0,image.getWidth(),image.getHeight(),matrix,true);if(adjusted!=image)image.recycle();image=adjusted;}
  int edge=Math.max(image.getWidth(),image.getHeight());if(edge>3072){Bitmap resized=Bitmap.createScaledBitmap(image,image.getWidth()*3072/edge,image.getHeight()*3072/edge,true);image.recycle();image=resized;}
  String name="board-"+captured+"-"+id+".jpg";File target=new File(Store.root(c),name),temp=new File(target.getPath()+".tmp");
  try{try(FileOutputStream out=new FileOutputStream(temp)){if(!image.compress(Bitmap.CompressFormat.JPEG,94,out))throw new IOException("Фото не сохранено");out.getFD().sync();}}finally{image.recycle();}
  if(temp.length()>12*1024*1024)throw new IOException("Фото больше 12 МБ; сделай обычный снимок доски");
  meta.put("kind","board_photo").put("captured_ms",captured).put("time_uncertainty_seconds",exact?2:20).put("clock_source",exact?"camera-exif":"camera-return");
  if(meta.has("launch_offset_seconds"))meta.put("offset_seconds",Math.max(0,meta.getDouble("launch_offset_seconds")+(captured-meta.getLong("launched_ms"))/1000.0));
  Store.write(new File(target.getPath()+".json"),meta);if(target.exists()||!temp.renameTo(target))throw new IOException("Не удалось завершить сохранение фото");
 }
}
