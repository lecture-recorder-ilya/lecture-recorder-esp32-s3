import os, subprocess, tempfile, unittest
from pathlib import Path

class AndroidTransport(unittest.TestCase):
 def test_real_sync_server_rejects_bad_hmac_replay_truncation_and_corruption(self):
  root=Path(__file__).resolve().parents[1]
  jdk=Path(os.environ.get('JAVA_HOME') or subprocess.check_output(['/usr/libexec/java_home','-v','17'],text=True).strip())
  files={
   'android/content/Context.java':'''package android.content; public class Context { public SharedPreferences getSharedPreferences(String n,int m){return new SharedPreferences();} }''',
   'android/content/SharedPreferences.java':'''package android.content; public class SharedPreferences {public String getString(String k,String d){return "fixture-key";}}''',
   'org/json/JSONObject.java':'''package org.json; public class JSONObject { public JSONObject(){} public JSONObject(String s){} public JSONObject put(String k,Object v){return this;} public String getString(String k){return "";} public String toString(){return "{}";} }''',
   'org/json/JSONArray.java':'''package org.json; public class JSONArray {public int length(){return 0;}public String toString(){return "[]";}}''',
   'ru/ilya/lecturerecorder/CaptureService.java':'''package ru.ilya.lecturerecorder; class CaptureService {static boolean recording=false;}''',
   'ru/ilya/lecturerecorder/AppUpdates.java':'''package ru.ilya.lecturerecorder; import java.io.*;import android.content.Context;import org.json.*;class AppUpdates{static File folder;static int received=0;static File apk(Context c){return new File(folder,"update.apk");}static int receive(Context c,File p,String sha){received++;return 8;}static JSONObject info(Context c){return new JSONObject();}}''',
   'ru/ilya/lecturerecorder/Store.java':'''package ru.ilya.lecturerecorder;import java.io.*;import android.content.Context;import org.json.*;class Store{static JSONArray list(Context c){return new JSONArray();}static File file(Context c,String n){return new File(n);}static void acknowledge(Context c,String n,String sha){}}''',
   'ru/ilya/lecturerecorder/LectureNotes.java':'''package ru.ilya.lecturerecorder;import android.content.Context;import org.json.*;class LectureNotes{static JSONObject index(Context c){return new JSONObject();}static String save(Context c,byte[] b){return "";}}''',
   'ru/ilya/lecturerecorder/Harness.java':r'''package ru.ilya.lecturerecorder;
import java.io.*;import java.util.*;import java.nio.charset.StandardCharsets;import android.content.Context;
public class Harness{
 static byte[] body="fixture-apk".getBytes(StandardCharsets.UTF_8);
 static String request(SyncServer server,String nonce,byte[] payload,int length,String digest,String key)throws Exception{
  String t=""+(System.currentTimeMillis()/1000),canonical="POST\n/app-update\n"+t+"\n"+nonce+"\n\n"+digest;
  String h="POST /app-update HTTP/1.1\r\nContent-Length: "+length+"\r\nX-Lecture-Time: "+t+"\r\nX-Lecture-Nonce: "+nonce+"\r\nX-Lecture-Signature: "+SyncServer.sign(key,canonical)+"\r\nX-Lecture-Body-SHA256: "+digest+"\r\n\r\n";
  ByteArrayOutputStream input=new ByteArrayOutputStream();input.write(h.getBytes(StandardCharsets.US_ASCII));input.write(payload);ByteArrayOutputStream out=new ByteArrayOutputStream();server.handle(new ByteArrayInputStream(input.toByteArray()),out,false);return out.toString("UTF-8");
 }
 static void require(boolean v)throws Exception{if(!v)throw new Exception("Проверка протокола не пройдена");}
 public static void main(String[] args)throws Exception{
  AppUpdates.folder=new File(args[0]);SyncServer server=new SyncServer(new Context());server.close();String sha=SyncServer.hash(body);
  require(request(server,"a".repeat(32),body,body.length,sha,"wrong-key").startsWith("HTTP/1.1 403"));require(AppUpdates.received==0);
  require(request(server,"b".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 200"));require(AppUpdates.received==1);
  require(request(server,"b".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 403"));require(AppUpdates.received==1);
  require(request(server,"c".repeat(32),new byte[body.length],body.length,sha,"fixture-key").startsWith("HTTP/1.1 422"));require(AppUpdates.received==1);
  require(request(server,"d".repeat(32),new byte[1],body.length,sha,"fixture-key").startsWith("HTTP/1.1 422"));require(AppUpdates.received==1);
  CaptureService.recording=true;require(request(server,"e".repeat(32),body,body.length,sha,"fixture-key").startsWith("HTTP/1.1 409"));require(AppUpdates.received==1);
  require(request(server,"f".repeat(32),body,80*1024*1024+1,sha,"fixture-key").startsWith("HTTP/1.1 413"));require(AppUpdates.folder.list().length==0);
  System.out.println("7 проверок реального SyncServer пройдены");
 }
}'''}
  with tempfile.TemporaryDirectory() as d:
   temp=Path(d);sources=[]
   for name,content in files.items():
    p=temp/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);sources.append(str(p))
   sources.append(str(root/'outputs/android/src/ru/ilya/lecturerecorder/SyncServer.java'))
   subprocess.run([str(jdk/'bin/javac'),'-encoding','UTF-8','-d',d,*sources],check=True,capture_output=True)
   data=temp/'data';data.mkdir()
   result=subprocess.run([str(jdk/'bin/java'),'-cp',d,'ru.ilya.lecturerecorder.Harness',str(data)],check=True,capture_output=True,text=True,timeout=15)
   self.assertIn('7 проверок',result.stdout)

if __name__=='__main__':unittest.main()
