import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'outputs/android/src/ru/ilya/lecturerecorder'


def client_fixtures():
    return {
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
 public long optLong(String key) { return has(key) ? getLong(key) : 0; }
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
    return "<https://api.github.com/repositories/42/releases?per_page=30&page=2>; rel=\"next\"";
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


class GitHubUpdatesTest(unittest.TestCase):
    def run_java(self, fixtures, production, main):
        gson = ROOT / 'work/android-deps/gson.jar'
        if not gson.is_file():
            self.skipTest('Build the Android APK to fetch its Gson dependency')
        java = Path(os.environ['JAVA_HOME']) / 'bin' if os.environ.get('JAVA_HOME') else Path()
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for name, source in fixtures.items():
                file = fixture / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(source, encoding='utf-8')
            subprocess.run([str(java / 'javac'), '-encoding', 'UTF-8', '-cp', str(gson), '-d', directory,
                            *map(str, production), *map(str, fixture.rglob('*.java'))], check=True)
            subprocess.run([str(java / 'java'), '-cp', f'{directory}{os.pathsep}{gson}',
                            'ru.ilya.lecturerecorder.' + main, str(fixture / 'apk')], check=True, timeout=45)

    def test_release_selection_and_download(self):
        self.run_java(client_fixtures(), [SRC / 'GitHubUpdateClient.java'], 'Harness')

    def test_automatic_public_and_interactive_private_updates(self):
        fixtures = client_fixtures()
        del fixtures['ru/ilya/lecturerecorder/GitHubUpdates.java']
        del fixtures['ru/ilya/lecturerecorder/Harness.java']
        fixtures.update(flow_fixtures())
        self.run_java(fixtures, [SRC / 'GitHubUpdates.java', SRC / 'GitHubUpdateClient.java',
                                 ROOT / 'tests/android/GitHubUpdateFlowTest.java'], 'GitHubUpdateFlowTest')


def flow_fixtures():
    return {
        'android/content/Context.java': r'''
package android.content;
import java.io.*;
import java.util.concurrent.ConcurrentHashMap;
import android.net.ConnectivityManager;
public class Context {
 public String packageName = "ru.ilya.lecturerecorder";
 public ConnectivityManager connectivity = new ConnectivityManager();
 private final ConcurrentHashMap<String,SharedPreferences> prefs = new ConcurrentHashMap<>();
 public Context getApplicationContext() { return this; }
 public Context getAssets() { return this; }
 public Context getPackageManager() { return this; }
 public Context getPackageInfo(String name, int flags) { return this; }
 public String versionName = "0.5.18";
 public String getPackageName() { return packageName; }
 public InputStream open(String name) {
  return new ByteArrayInputStream("{\"client_id\":\"test\",\"repository\":\"org/repo\"}".getBytes());
 }
 public SharedPreferences getSharedPreferences(String name, int mode) { return prefs.computeIfAbsent(name, key -> new SharedPreferences()); }
 public <T> T getSystemService(Class<T> type) { return type.cast(connectivity); }
}''',
        'android/content/SharedPreferences.java': '''
package android.content;
import java.util.concurrent.ConcurrentHashMap;
public class SharedPreferences {
 private final ConcurrentHashMap<String,Object> data = new ConcurrentHashMap<>();
 public long getLong(String key, long other) { return (long)data.getOrDefault(key, other); }
 public String getString(String key, String other) { return (String)data.getOrDefault(key, other); }
 public SharedPreferences edit() { return this; }
 public SharedPreferences putLong(String key, long value) { data.put(key, value); return this; }
 public SharedPreferences putString(String key, String value) { data.put(key, value); return this; }
 public SharedPreferences remove(String key) { data.remove(key); return this; }
 public void apply() {}
}''',
        'android/app/Activity.java': '''
package android.app;
public class Activity extends android.content.Context {
 public boolean isFinishing() { return false; }
 public boolean isDestroyed() { return false; }
 public void startActivity(android.content.Intent intent) {}
}''',
        'android/app/AlertDialog.java': '''
package android.app;
public class AlertDialog {
 public static int dialogs;
 public interface Listener { void click(Object dialog, int which); }
 public static class Builder {
  public Builder(Activity activity) {}
  public Builder setTitle(String value) { return this; }
  public Builder setMessage(String value) { return this; }
  public Builder setPositiveButton(String value, Listener listener) { return this; }
  public Builder setNeutralButton(String value, Listener listener) { return this; }
  public Builder setNegativeButton(String value, Listener listener) { return this; }
  public void show() { dialogs++; }
 }
}''',
        'android/content/ActivityNotFoundException.java': 'package android.content; public class ActivityNotFoundException extends RuntimeException {}',
        'android/content/Intent.java': 'package android.content; public class Intent {public static final String ACTION_VIEW="view"; public Intent(String action,android.net.Uri uri) {}}',
        'android/content/ClipData.java': 'package android.content; public class ClipData {public static ClipData newPlainText(String title,String text){return new ClipData();}}',
        'android/content/ClipboardManager.java': 'package android.content; public class ClipboardManager {public void setPrimaryClip(ClipData clip){}}',
        'android/net/Uri.java': 'package android.net; public class Uri {public static Uri parse(String uri){return new Uri();}}',
        'android/net/Network.java': 'package android.net; public class Network {}',
        'android/net/ConnectivityManager.java': '''
package android.net;
public class ConnectivityManager {
 public boolean online = true;
 public Network getActiveNetwork() { return online ? new Network() : null; }
 public NetworkCapabilities getNetworkCapabilities(Network network) { return new NetworkCapabilities(); }
}''',
        'android/net/NetworkCapabilities.java': 'package android.net; public class NetworkCapabilities {public static final int NET_CAPABILITY_VALIDATED=16; public boolean hasCapability(int value){return true;}}',
        'android/os/Looper.java': 'package android.os; public class Looper { public static Looper getMainLooper(){return new Looper();} }',
        'android/os/Handler.java': 'package android.os; public class Handler {public Handler(Looper looper) {} public void post(Runnable action){action.run();}}',
        'android/os/SystemClock.java': '''
package android.os;
public class SystemClock {
 public static long advance;
 public static long elapsedRealtime() {return System.nanoTime()/1000000 + advance;}
}''',
        'ru/ilya/lecturerecorder/GitHubUpdateCredentials.java': '''
package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.JSONObject;
class GitHubUpdateCredentials {
 static JSONObject stored;
 GitHubUpdateCredentials(Context context) {}
 boolean exists() {return stored != null;}
 JSONObject read() {return stored;}
 void clear() {stored = null;}
 void save(JSONObject value) {stored = new JSONObject("{\\"access_token\\":\\"" + value.getString("access_token") + "\\",\\"expires_at\\":" + Long.MAX_VALUE + "}");}
}''',
        'ru/ilya/lecturerecorder/AppUpdates.java': '''
package ru.ilya.lecturerecorder;
import android.content.Context;
import java.io.*;
import java.nio.file.*;
class AppUpdates {
 static File target;
 static boolean active;
 static int staged;
 static boolean active(){return active;}
 static File apk(Context context){return target;}
 static boolean ready(Context context){return target.isFile();}
 static void stage(Context context,File part,String checksum,String source) throws IOException {
  if (!"github".equals(source)) throw new IOException("source");
  Files.copy(part.toPath(),target.toPath(),StandardCopyOption.REPLACE_EXISTING);
  context.getSharedPreferences("updates",0).edit().putString("sha256",checksum).apply();
  staged++;
 }
}''',
    }


if __name__ == '__main__':
    unittest.main()
