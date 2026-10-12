package ru.ilya.lecturerecorder;

import android.app.Activity;
import android.content.*;
import android.content.pm.*;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;

final class AppUpdates {
 static final String REPO="lecture-recorder-ilya/lecture-recorder-esp32-s3";
 static volatile String status="Проверяю обновления приложения…";
 private static boolean checking=false;
 static File apk(Context c){return new File(new File(c.getFilesDir(),"updates"),"update.apk");}
 private static HttpURLConnection connection(String url)throws Exception{
  URL u=new URL(url);if(!u.getProtocol().equals("https"))throw new IOException("Нужен HTTPS");
  HttpURLConnection c=(HttpURLConnection)u.openConnection();c.setConnectTimeout(15000);c.setReadTimeout(60000);c.setRequestProperty("User-Agent","LectureRecorder-Android");return c;
 }
 private static byte[] read(InputStream in,int limit)throws IOException{
  ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] b=new byte[65536];int n;
  while((n=in.read(b))!=-1){if(out.size()+n>limit)throw new IOException("Ответ слишком большой");out.write(b,0,n);}return out.toByteArray();
 }
 static synchronized void check(Context c,boolean force){
  if(checking||CaptureService.recording)return;Context app=c.getApplicationContext();
  long last=app.getSharedPreferences("updates",0).getLong("checked",0);
  if(!force&&System.currentTimeMillis()-last<6*3600*1000L){ready(app);return;}
  checking=true;app.getSharedPreferences("updates",0).edit().putLong("checked",System.currentTimeMillis()).apply();
  new Thread(()->{try{
   HttpURLConnection conn=connection("https://api.github.com/repos/"+REPO+"/releases/latest");JSONObject release;
   try{if(conn.getResponseCode()==404)throw new IOException("Нет доступного релиза · владелец должен опубликовать обновление");try(InputStream in=conn.getInputStream()){release=new JSONObject(new String(read(in,2*1024*1024),StandardCharsets.UTF_8));}}finally{conn.disconnect();}
   if(release.optBoolean("draft")||release.optBoolean("prerelease"))return;
   PackageInfo installed=app.getPackageManager().getPackageInfo(app.getPackageName(),0);
   if(release.optString("tag_name").equals("v"+installed.versionName)){status="Установлена последняя версия";return;}
   JSONArray assets=release.getJSONArray("assets");JSONObject asset=null;for(int i=0;i<assets.length();i++)if(assets.getJSONObject(i).getString("name").equals("lecture-recorder.apk"))asset=assets.getJSONObject(i);
   if(asset==null)throw new IOException("В релизе пока нет APK");String digest=asset.optString("digest");long size=asset.getLong("size");
   if(!digest.matches("sha256:[a-f0-9]{64}")||size<=0||size>80*1024*1024)throw new IOException("Нет проверяемой контрольной суммы APK");
   String url=asset.getString("browser_download_url");if(!url.startsWith("https://github.com/"+REPO+"/releases/download/"))throw new IOException("Неизвестный источник обновления");
   status="Скачиваю обновление приложения…";File target=apk(app);target.getParentFile().mkdirs();File temp=new File(target.getPath()+".part");
   conn=connection(url);MessageDigest sha=MessageDigest.getInstance("SHA-256");long count=0;
   try(InputStream in=conn.getInputStream();FileOutputStream out=new FileOutputStream(temp)){byte[] b=new byte[65536];int n;while((n=in.read(b))!=-1){count+=n;if(count>size)throw new IOException("Размер APK изменился");sha.update(b,0,n);out.write(b,0,n);}out.getFD().sync();}finally{conn.disconnect();}
   if(count!=size||!SyncServer.hex(sha.digest()).equals(digest.substring(7))){temp.delete();throw new IOException("Контрольная сумма APK не совпала");}
   int code=verify(app,temp);if(!temp.renameTo(target))throw new IOException("Обновление не сохранено");
   app.getSharedPreferences("updates",0).edit().putString("sha256",digest.substring(7)).putInt("code",code).commit();status="Обновление скачано · нажми «Установить»";
  }catch(Exception e){status=e.getMessage()==null?"Проверю обновления позже":e.getMessage();}finally{synchronized(AppUpdates.class){checking=false;}}},"Application updates").start();
 }
 private static Set<String> signatures(PackageInfo p)throws Exception{
  Signature[] ss=Build.VERSION.SDK_INT>=28?(p.signingInfo==null?null:p.signingInfo.getApkContentsSigners()):p.signatures;
  if(ss==null||ss.length==0)throw new IOException("Нет подписи APK");Set<String> result=new HashSet<>();for(Signature s:ss)result.add(SyncServer.hash(s.toByteArray()));return result;
 }
 static int verify(Context c,File file)throws Exception{
  PackageManager pm=c.getPackageManager();int flags=Build.VERSION.SDK_INT>=28?PackageManager.GET_SIGNING_CERTIFICATES:PackageManager.GET_SIGNATURES;
  PackageInfo current=pm.getPackageInfo(c.getPackageName(),flags),next=pm.getPackageArchiveInfo(file.getPath(),flags);
  if(next==null||!c.getPackageName().equals(next.packageName)||next.versionCode<=current.versionCode)throw new IOException("APK не является новой версией этого приложения");
  if(!signatures(current).equals(signatures(next)))throw new IOException("Подпись обновления отличается · нужен ключ автора");
  return next.versionCode;
 }
 static boolean ready(Context c){try{
  android.content.SharedPreferences prefs=c.getSharedPreferences("updates",0);
  if(!apk(c).isFile()||!prefs.contains("sha256"))return false;
  if(prefs.getInt("code",0)<=c.getPackageManager().getPackageInfo(c.getPackageName(),0).versionCode){apk(c).delete();prefs.edit().remove("sha256").remove("code").apply();return false;}
  return true;
 }catch(Exception e){return false;}}
 static void install(Activity activity){try{
  if(CaptureService.recording)throw new IOException("Сначала останови и сохрани запись");
  File file=apk(activity);if(!Store.hash(file).equals(activity.getSharedPreferences("updates",0).getString("sha256","")))throw new IOException("APK изменился; проверь обновление повторно");verify(activity,file);
  if(!activity.getPackageManager().canRequestPackageInstalls()){activity.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+activity.getPackageName())));status="Разреши установку для приложения, затем нажми «Установить»";return;}
  Intent intent=new Intent(Intent.ACTION_VIEW);intent.setDataAndType(Uri.parse("content://ru.ilya.lecturerecorder.updates/update.apk"),"application/vnd.android.package-archive");intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);activity.startActivity(intent);
 }catch(Exception e){status=e.getMessage();}}
}
