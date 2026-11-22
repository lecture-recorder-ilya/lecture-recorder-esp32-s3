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
 static File apk(Context c){return new File(new File(c.getFilesDir(),"updates"),"update.apk");}
 static synchronized void check(Context c,boolean force){
  if(ready(c)){status="Обновление получено от Mac · нажми «Установить»";return;}
  if(c.getSharedPreferences("updates",0).contains("rejected_digest")){status=c.getSharedPreferences("updates",0).getString("rejected_message","APK отклонён · нужна совместимая подпись");return;}
  if(c.getSharedPreferences("settings",0).getString("sync_token","").isEmpty()){status="Подключи Mac в настройках · вход в GitHub нужен только на Mac";return;}
  status="Обновления приходят через Mac · включи на нём приложение и войди в GitHub";
  if(force&&!CaptureService.recording)c.startForegroundService(CaptureService.command(c,"SYNC"));
 }
 static JSONObject info(Context c)throws Exception{
  android.content.SharedPreferences p=c.getSharedPreferences("updates",0);
  PackageInfo installed=c.getPackageManager().getPackageInfo(c.getPackageName(),0);
  return new JSONObject().put("installed_package",c.getPackageName())
   .put("installed_tag","v"+installed.versionName).put("installed_code",installed.versionCode)
   .put("sha256",ready(c)?p.getString("sha256",""):"").put("recording",CaptureService.recording)
   .put("rejected_digest",p.getString("rejected_digest","")).put("message",status);
 }
 static synchronized int receive(Context c,File temp,String sha)throws Exception{
  if(CaptureService.recording)throw new IOException("Обновление будет передано после записи");
  int code;
  try{code=verify(c,temp);}catch(Exception e){
   status=e.getMessage();c.getSharedPreferences("updates",0).edit().putString("rejected_digest",sha).putString("rejected_message",status).commit();throw e;
  }
  File target=apk(c);target.getParentFile().mkdirs();
  if(!temp.renameTo(target))throw new IOException("Не удалось сохранить APK");
  if(!c.getSharedPreferences("updates",0).edit().putString("sha256",sha).putInt("code",code).remove("rejected_digest").remove("rejected_message").commit())throw new IOException("Не удалось сохранить сведения об APK");
  status="Обновление получено от Mac · нажми «Установить»";return code;
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
  Intent intent=new Intent(Intent.ACTION_VIEW);intent.setDataAndType(Uri.parse("content://"+activity.getPackageName()+".updates/update.apk"),"application/vnd.android.package-archive");intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);activity.startActivity(intent);
 }catch(Exception e){status=e.getMessage();}}
}
