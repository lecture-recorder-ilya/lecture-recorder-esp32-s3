import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'outputs/android/src/ru/ilya/lecturerecorder'


class GitHubUpdatesTest(unittest.TestCase):
    def test_release_selection_and_download(self):
        gson = ROOT / 'work/android-deps/gson.jar'
        if not gson.is_file():
            self.skipTest('Build the Android APK to fetch its Gson dependency')
        java = Path(os.environ.get('JAVA_HOME', '')) / 'bin' if os.environ.get('JAVA_HOME') else Path()
        sources = {
            'android/content/Context.java': r'''
package android.content;
import java.io.*;
public class Context {
 public Context getAssets() { return this; }
 public InputStream open(String name) {
  return new ByteArrayInputStream("{\"client_id\":\"test\",\"repository\":\"org/repo\"}".getBytes());
 }
}''',
            'android/os/SystemClock.java': '''
package android.os;
public class SystemClock {
 public static long elapsedRealtime() { return System.nanoTime()/1000000; }
}''',
            'org/json/JSONObject.java': '''
package org.json;
import com.google.gson.*;
public class JSONObject {
 final JsonObject data;
 public JSONObject(String s) { this(JsonParser.parseString(s).getAsJsonObject()); }
 JSONObject(JsonObject item) { data = item; }
 public String getString(String key) { return data.get(key).getAsString(); }
 public long getLong(String key) { return data.get(key).getAsLong(); }
 public int getInt(String key) { return data.get(key).getAsInt(); }
 public int optInt(String key, int fallback) { return has(key) ? getInt(key) : fallback; }
 public boolean optBoolean(String key) { return has(key) && data.get(key).getAsBoolean(); }
 public String optString(String key) { return has(key) ? getString(key) : ""; }
 public JSONArray getJSONArray(String key) { return new JSONArray(data.getAsJsonArray(key)); }
 public boolean has(String key) { return data.has(key) && !data.get(key).isJsonNull(); }
}''',
            'org/json/JSONArray.java': '''
package org.json;
import com.google.gson.*;
public class JSONArray {
 final JsonArray data;
 public JSONArray(String s) { this(JsonParser.parseString(s).getAsJsonArray()); }
 JSONArray(JsonArray items) { data = items; }
 public int length() { return data.size(); }
 public JSONObject getJSONObject(int index) { return new JSONObject(data.get(index).getAsJsonObject()); }
}''',
            'ru/ilya/lecturerecorder/GitHubUpdates.java': '''
package ru.ilya.lecturerecorder;
class GitHubUpdates {
 static class Failure extends java.io.IOException { Failure(String message) { super(message); } }
}''',
            'ru/ilya/lecturerecorder/Store.java': '''
package ru.ilya.lecturerecorder;
import java.io.*;
import java.nio.file.*;
import java.security.*;
import java.util.HexFormat;
class Store {
 static String hash(File file) throws Exception {
  return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file.toPath())));
 }
}''',
            'ru/ilya/lecturerecorder/Harness.java': r'''
package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;

public class Harness {
 static final String API = "api.github.com";
 static final String CDN = "release-assets.githubusercontent.com";
 static final String ASSET = "lecture-recorder-android.apk";
 static final String BASE = "https://" + API + "/repos/org/repo/releases";
 static final byte[] PAYLOAD = "test APK".getBytes(StandardCharsets.UTF_8);
 static String checksum;
 static String latestTag = "v0.5.12", latestAsset = "lecture-recorder.apk", latestFlags = "";
 static String location = "https://" + CDN + "/fixture";
 static boolean corrupt;
 static int cdnRequests;

 static String release(String tag, String name, String flags) {
  return "{\"tag_name\":\"" + tag + "\"," + flags
   + "\"assets\":[{\"name\":\"" + name + "\",\"state\":\"uploaded\",\"id\":1,\"size\":"
   + PAYLOAD.length + ",\"digest\":\"sha256:" + checksum + "\"}]}";
 }

 static class Response extends HttpURLConnection {
  Response(URL url) { super(url); }
  public void connect() {}
  public void disconnect() {}
  public boolean usingProxy() { return false; }
  public int getResponseCode() {
   if (getURL().getHost().equals(API)) {
    require("Bearer fixture-token".equals(getRequestProperty("Authorization")), "Missing API authorization");
    return getURL().getPath().endsWith("/assets/1") ? 302 : 200;
   }
   require(getURL().getHost().equals(CDN), "Unexpected redirect");
   require(getRequestProperty("Authorization") == null, "GitHub token sent to asset CDN");
   cdnRequests++;
   return 200;
  }
  public String getHeaderField(String name) {
   if (name.equals("Location")) return location;
   if (name.equals("Link") && !getURL().getQuery().contains("page=2")) {
    return "<" + BASE + "?per_page=30&page=2>; rel=\"next\"";
   }
   return null;
  }
  public InputStream getInputStream() {
   if (getURL().getPath().endsWith("/latest")) {
    return new ByteArrayInputStream(release(latestTag, latestAsset, latestFlags).getBytes(StandardCharsets.UTF_8));
   }
   if (getURL().getHost().equals(CDN)) {
    byte[] bytes = PAYLOAD.clone();
    if (corrupt) bytes[0] ^= 1;
    return new ByteArrayInputStream(bytes);
   }
   String body = getURL().getQuery().contains("page=2")
    ? "[" + release("android-v0.5.10", ASSET, "") + "," + release("android-v0.5.11", ASSET, "") + "]"
    : "[" + release("android-v0.5.13", ASSET, "\"draft\":true,") + ","
    + release("android-v0.5.12", ASSET, "\"prerelease\":true,") + ","
    + release("v0.5.12", "lecture-recorder.apk", "") + ","
    + release("android-v0.5.9", ASSET, "") + "]";
   return new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));
  }
 }

 static void require(boolean value, String message) {
  if (!value) throw new AssertionError(message);
 }

 public static void main(String[] args) throws Exception {
  File target = new File(args[0]);
  Files.write(target.toPath(), PAYLOAD);
  checksum = Store.hash(target);
  URL.setURLStreamHandlerFactory(protocol -> new URLStreamHandler() {
   protected URLConnection openConnection(URL url) { return new Response(url); }
  });

  GitHubUpdateClient client = new GitHubUpdateClient(new Context());
  GitHubUpdateClient.Asset asset = client.latest("fixture-token", "0.5.9", ASSET);
  require("0.5.11".equals(asset.version), "Stable compatible asset was not selected");
  require(client.latest("fixture-token", "0.5.11", ASSET) == null, "Same version accepted");
  require("0.5.12".equals(client.latest("fixture-token", "0.5.9", "lecture-recorder.apk").version),
    "Stable package did not pick its own asset");
  client.download("fixture-token", asset, target, percent -> require(percent == 100, "Wrong progress"));
  require(checksum.equals(Store.hash(target)), "Wrong payload");
  location = "https://untrusted.example/fixture";
  try {
   latestTag = "android-v0.5.16";
  require(client.latest("fixture-token", "0.5.9", "lecture-recorder.apk") == null, "Самостоятельный тег попал в основной канал");
  latestTag = "v0.5.12";
  latestFlags = "\"prerelease\":true,";
  require(client.latest("fixture-token", "0.5.9", "lecture-recorder.apk") == null, "Предварительный выпуск принят");
  latestFlags = "";
  latestAsset = "lecture-recorder-android.apk";
  require(client.latest("fixture-token", "0.5.9", "lecture-recorder.apk") == null, "Чужой пакет принят");
  client.download("fixture-token", asset, target, percent -> {});
   throw new AssertionError("Untrusted redirect accepted");
  } catch (GitHubUpdates.Failure expected) {}
  require(cdnRequests == 1, "Unexpected download");
  location = "https://" + CDN + "/fixture";
  corrupt = true;
  try {
   client.download("fixture-token", asset, target, percent -> {});
   throw new AssertionError("Corrupt payload accepted");
  } catch (GitHubUpdates.Failure expected) {}
 }
}''',
        }
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for name, source in sources.items():
                file = fixture / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(source, encoding='utf-8')
            subprocess.run([str(java / 'javac'), '-encoding', 'UTF-8', '-cp', str(gson), '-d', directory,
                            str(SRC / 'GitHubUpdateClient.java'), *map(str, fixture.rglob('*.java'))], check=True)
            subprocess.run([str(java / 'java'), '-cp', f'{directory}{os.pathsep}{gson}',
                            'ru.ilya.lecturerecorder.Harness', str(fixture / 'apk')], check=True, timeout=30)


if __name__ == '__main__':
    unittest.main()
