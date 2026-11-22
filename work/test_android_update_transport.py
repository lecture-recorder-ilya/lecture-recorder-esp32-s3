import os, subprocess, tempfile, unittest
from pathlib import Path

class AndroidTransport(unittest.TestCase):
 def test_real_sync_server_rejects_bad_hmac_replay_truncation_and_corruption(self):
  root=Path(__file__).resolve().parents[1]
  jdk=Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home','-v','17'],text=True).strip())
  files={
   'android/content/Context.java':'''package android.content;
import java.io.File; import android.content.pm.PackageManager;
public class Context {
 public File files; public final PackageManager pm=new PackageManager();
 public PackageManager getPackageManager(){return pm;} public String getPackageName(){return pm.current.packageName;}
 public File getFilesDir(){return files;} public void startForegroundService(Intent i){}
 public SharedPreferences getSharedPreferences(String n,int m){return new SharedPreferences();}
}''',
   'android/content/SharedPreferences.java':'''package android.content;
public class SharedPreferences {
 public String getString(String k,String d){return k.equals("sync_token")?"fixture-key":d;}
 public int getInt(String k,int d){return d;} public boolean contains(String k){return false;}
 public Editor edit(){return new Editor();} public static class Editor {
  public Editor putString(String k,String v){return this;} public Editor putInt(String k,int v){return this;}
  public Editor remove(String k){return this;} public void apply(){} public boolean commit(){return true;}
 }
}''',
   'android/content/Intent.java':'''package android.content; import android.net.Uri;
public class Intent {public static final String ACTION_VIEW="view";public static final int FLAG_GRANT_READ_URI_PERMISSION=1;
 public Intent(String s){} public Intent(String s,Uri u){} public void setDataAndType(Uri u,String t){} public void addFlags(int f){} }''',
   'android/app/Activity.java':'''package android.app; import android.content.*; public class Activity extends Context {public void startActivity(Intent i){} }''',
   'android/net/Uri.java':'''package android.net; public class Uri {public static Uri parse(String s){return new Uri();}}''',
   'android/os/Build.java':'''package android.os; public class Build {public static class VERSION {public static int SDK_INT=33;}}''',
   'android/provider/Settings.java':'''package android.provider; public class Settings {public static final String ACTION_MANAGE_UNKNOWN_APP_SOURCES="settings";}''',
   'android/content/pm/PackageManager.java':'''package android.content.pm;
public class PackageManager {
 public static final int GET_SIGNATURES=64, GET_SIGNING_CERTIFICATES=134217728;
 public PackageInfo current,next; public int inspected;
 public PackageInfo getPackageInfo(String name,int flags){return current;}
 public PackageInfo getPackageArchiveInfo(String path,int flags){inspected++;return next;}
 public boolean canRequestPackageInstalls(){return true;}
}''',
   'android/content/pm/PackageInfo.java':'''package android.content.pm; public class PackageInfo {
 public String packageName,versionName;public int versionCode;public Signature[] signatures;public SigningInfo signingInfo;
}''',
   'android/content/pm/Signature.java':'''package android.content.pm; public class Signature {
 private final byte id;public Signature(int id){this.id=(byte)id;}public byte[] toByteArray(){return new byte[]{id};}
}''',
   'android/content/pm/SigningInfo.java':'''package android.content.pm; public class SigningInfo {
 private final Signature[] signers;public SigningInfo(Signature[] ss){signers=ss;}public Signature[] getApkContentsSigners(){return signers;}
}''',
   'org/json/JSONObject.java':'''package org.json; import java.util.*;
public class JSONObject {private final Map<String,Object> fields=new HashMap<>();
 public JSONObject(){} public JSONObject(String s){} public JSONObject put(String k,Object v){fields.put(k,v);return this;}
 public String getString(String k){return String.valueOf(fields.get(k));} public String toString(){return "{}";}
}''',
   'org/json/JSONArray.java':'''package org.json; public class JSONArray {public int length(){return 0;}public String toString(){return "[]";}}''',
   'ru/ilya/lecturerecorder/CaptureService.java':'''package ru.ilya.lecturerecorder; import android.content.*; class CaptureService {static boolean recording=false;static boolean paired(Context c){return !c.getSharedPreferences("settings",0).getString("sync_token","").isEmpty();}}''',
   'ru/ilya/lecturerecorder/Store.java':'''package ru.ilya.lecturerecorder;import java.io.*;import android.content.Context;import org.json.*;class Store{static String hash(File f){return "";}static JSONArray list(Context c){return new JSONArray();}static File transferFile(Context c,String n){return new File(n);}static void acknowledge(Context c,String n,String sha){}}''',
   'ru/ilya/lecturerecorder/LectureNotes.java':'''package ru.ilya.lecturerecorder;import android.content.Context;import org.json.*;class LectureNotes{static JSONObject index(Context c){return new JSONObject();}static String save(Context c,byte[] b){return "";}}''',
   'ru/ilya/lecturerecorder/Harness.java':r'''package ru.ilya.lecturerecorder;
import java.io.*;import java.util.*;import java.nio.charset.StandardCharsets;import java.nio.file.Files;
import android.content.Context;import android.content.pm.*;import org.json.JSONObject;
public class Harness{
 static byte[] body="fixture-apk".getBytes(StandardCharsets.UTF_8);
 static String request(SyncServer server,String nonce,byte[] payload,int length,String digest,String key)throws Exception{
  String t=""+(System.currentTimeMillis()/1000),canonical="POST\n/app-update\n"+t+"\n"+nonce+"\n\n"+digest;
  String h="POST /app-update HTTP/1.1\r\nContent-Length: "+length+"\r\nX-Lecture-Time: "+t+"\r\nX-Lecture-Nonce: "+nonce+"\r\nX-Lecture-Signature: "+SyncServer.sign(key,canonical)+"\r\nX-Lecture-Body-SHA256: "+digest+"\r\n\r\n";
  ByteArrayOutputStream input=new ByteArrayOutputStream();input.write(h.getBytes(StandardCharsets.US_ASCII));input.write(payload);ByteArrayOutputStream out=new ByteArrayOutputStream();server.handle(new ByteArrayInputStream(input.toByteArray()),out,false);return out.toString("UTF-8");
 }
 static void require(boolean v)throws Exception{if(!v)throw new Exception("Проверка протокола не пройдена");}
 static PackageInfo build(String name,int code,int signer){
  PackageInfo info=new PackageInfo();info.packageName=name;info.versionName="0.5.4";info.versionCode=code;
  info.signatures=new Signature[]{new Signature(signer)};info.signingInfo=new SigningInfo(info.signatures);return info;
 }
 static void rejected(Context c,PackageInfo next)throws Exception{
  c.pm.next=next;
  try{AppUpdates.verify(c,new File(c.files,"fixture.apk"));}catch(IOException expected){return;}
  throw new AssertionError("Несовместимый APK принят");
 }
 static void checkPackages(Context c)throws Exception{
  String stable="ru.ilya.lecturerecorder",preview=stable+".preview";
  for(String id:List.of(stable,preview)){
   int code=id.equals(stable)?11:22;
   c.pm.current=build(id,code,1);
   JSONObject status=AppUpdates.info(c);
   require(id.equals(status.getString("installed_package")));
   require((""+code).equals(status.getString("installed_code"))&&"v0.5.4".equals(status.getString("installed_tag")));
   c.pm.next=build(id,code+1,1);require(AppUpdates.verify(c,new File(c.files,"fixture.apk"))==code+1);
   rejected(c,build(id.equals(stable)?preview:stable,code+1,1));
   rejected(c,build(id,code+1,2));rejected(c,build(id,code,1));
  }
 }
 public static void main(String[] args)throws Exception{
  Context c=new Context();c.files=new File(args[0]);checkPackages(c);
  c.pm.current=build("ru.ilya.lecturerecorder",11,1);c.pm.next=build(c.getPackageName(),12,1);c.pm.inspected=0;
  SyncServer server=new SyncServer(c);server.close();String sha=SyncServer.hash(body);
  require(request(server,"a".repeat(32),body,body.length,sha,"wrong-key").startsWith("HTTP/1.1 403"));require(c.pm.inspected==0);
  require(request(server,"b".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 200"));require(c.pm.inspected==1);
  require(request(server,"b".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 403"));require(c.pm.inspected==1);
  require(request(server,"c".repeat(32),new byte[body.length],body.length,sha,"fixture-key").startsWith("HTTP/1.1 422"));require(c.pm.inspected==1);
  require(request(server,"d".repeat(32),new byte[1],body.length,sha,"fixture-key").startsWith("HTTP/1.1 422"));require(c.pm.inspected==1);
  CaptureService.recording=true;require(request(server,"e".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 409"));require(c.pm.inspected==1);
  require(request(server,"f".repeat(32),body,80*1024*1024+1,sha,"fixture-key").startsWith("HTTP/1.1 413"));
  File saved=AppUpdates.apk(c);require(saved.getParentFile().list().length==1&&Arrays.equals(Files.readAllBytes(saved.toPath()),body));
  System.out.println("7 проверок реального SyncServer пройдены");
 }
}'''}
  with tempfile.TemporaryDirectory() as d:
   temp=Path(d);sources=[]
   for name,content in files.items():
    p=temp/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);sources.append(str(p))
   android=root/'outputs/android/src/ru/ilya/lecturerecorder'
   sources.extend(str(android/name) for name in ('SyncServer.java','AppUpdates.java'))
   subprocess.run([str(jdk/'bin/javac'),'-encoding','UTF-8','-d',d,*sources],check=True,capture_output=True)
   data=temp/'data';data.mkdir()
   result=subprocess.run([str(jdk/'bin/java'),'-cp',d,'ru.ilya.lecturerecorder.Harness',str(data)],check=True,capture_output=True,text=True,timeout=15)
   self.assertIn('7 проверок',result.stdout)

if __name__=='__main__':unittest.main()
