package ru.ilya.lecturerecorder;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.nsd.*;
import android.net.wifi.WifiManager;
import android.os.*;
import android.media.AudioFormat;
import android.media.AudioManager;
import android.media.AudioRecord;
import android.media.AudioRecordingConfiguration;
import android.media.AudioRouting;
import android.media.AudioTimestamp;
import org.json.*;
import java.io.*;
import java.net.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.*;
import java.util.concurrent.*;

public class CaptureService extends Service {
 enum Link { OFF, CONNECTING, CONNECTED, ERROR }
 static volatile Link link=Link.OFF;
 static volatile String linkSource="";
 static volatile String inputLabel="";
 static volatile boolean recording=false;static volatile String status="Готово к записи",current="";static volatile long samples=0;
 static volatile int peak=0;
 static volatile boolean localInputSilenced;
 private static volatile long lastAudioAt;
 static boolean receivingAudio() {
  long last = lastAudioAt;
  return recording && link == Link.CONNECTED && last > 0 && SystemClock.elapsedRealtime() - last <= 2000;
 }
 private static final long SYNC_IDLE_NANOS=TimeUnit.SECONDS.toNanos(60);
 private static int visibleScreens;
 private static long lastScreenStopped=System.nanoTime();
 private volatile boolean phoneMicrophone;
 private boolean autoWithClipMic;
 private long lastStatusSecond;
 private String lastStatusInput;
 private volatile AudioRecord currentMicrophone;
 private boolean destroyed;
 private int foregroundType=-1;
 private volatile boolean stop=false;private volatile Socket socket;private SyncServer server;private BleSync bleSync;private PowerManager.WakeLock syncWake;private WifiManager.WifiLock wifi;private WifiManager.MulticastLock multicast;private NsdManager nsd;private NsdManager.DiscoveryListener discovery;private volatile String discovered="";private Handler timer=new Handler(Looper.getMainLooper());
 static void provision(Context c)throws Exception{File f=new File(c.getFilesDir(),"provision.json");if(!f.exists())return;JSONObject j=new JSONObject(Store.read(f));android.content.SharedPreferences.Editor e=c.getSharedPreferences("settings",0).edit();for(String k:new String[]{"ip","hostname","token","sync_token","ble_address"})if(j.has(k))e.putString(k,j.getString(k));if(!e.commit())throw new IOException("Настройки не сохранены");if(!f.delete())throw new IOException("Настройки не закрыты");}
 static Intent command(Context c,String action){android.content.SharedPreferences prefs=c.getSharedPreferences("settings",0);String key=prefs.getString("service_key","");if(key.isEmpty()){key=UUID.randomUUID().toString();if(!prefs.edit().putString("service_key",key).commit())throw new IllegalStateException("Не удалось сохранить настройки записи");}return new Intent(c,CaptureService.class).setAction(action).putExtra("auth",key);}
 static void screenStarted(){visibleScreens++;}
 static void screenStopped(){if(--visibleScreens==0)lastScreenStopped=System.nanoTime();}
 static boolean paired(Context context){
  return !context.getSharedPreferences("settings",0).getString("sync_token","").isEmpty();
 }
 static void resumeSync(Activity activity){
  if(paired(activity))activity.startForegroundService(command(activity,"SYNC"));
 }
 @Override public void onCreate(){super.onCreate();try{provision(this);Store.recover(this);}catch(Exception e){status="Восстановление: "+e.getMessage();}
  NotificationManager n=getSystemService(NotificationManager.class);n.createNotificationChannel(new NotificationChannel("record","Запись лекции",NotificationManager.IMPORTANCE_LOW));
 }
 private void notifyState(){Intent open=new Intent(this,MainActivity.class);PendingIntent p=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);Notification.Builder n=new Notification.Builder(this,"record").setSmallIcon(ru.ilya.lecturerecorder.R.drawable.icon).setContentTitle(recording?"Идёт запись лекции":"Связь с Mac").setContentText(recording?status:SyncServer.status).setContentIntent(p).setOnlyAlertOnce(true).setOngoing(true);
  if(recording)n.addAction(new Notification.Action.Builder(null,"Завершить запись",PendingIntent.getService(this,1,command(this,"STOP"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build());
  int type=Build.VERSION.SDK_INT>=30&&recording&&phoneMicrophone
   ?ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE:ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
  if(Build.VERSION.SDK_INT>=30&&recording&&autoWithClipMic)type|=ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
  Notification notification=n.build();
  if(foregroundType!=type){
   if(Build.VERSION.SDK_INT>=29)startForeground(1,notification,type);else startForeground(1,notification);
   foregroundType=type;
  }else getSystemService(NotificationManager.class).notify(1,notification);
 }
 @Override public int onStartCommand(Intent intent,int flags,int id){String secret=getSharedPreferences("settings",0).getString("service_key","");if(intent==null||secret.isEmpty()||!secret.equals(intent.getStringExtra("auth"))){if(!recording)stopSelf();return START_NOT_STICKY;}
  try{if(paired(this)&&server==null)server=new SyncServer(this);}catch(Exception e){status="Перенос: "+e.getMessage();}
  String action=intent.getAction();
  if (("START".equals(action) || "START_PHONE".equals(action) || "START_AUTO".equals(action)) && !recording) {
   boolean automatic = "START_AUTO".equals(action);
   phoneMicrophone = automatic || "START_PHONE".equals(action);
   autoWithClipMic = automatic && BleStream.hasTrustedDevice(this);
   boolean manualWifi = "wifi".equals(getSharedPreferences("settings", 0).getString("transport", "ble"));
   String source = automatic ? "auto" : phoneMicrophone ? "phone" : manualWifi ? "wifi" : "ble";
   if (phoneMicrophone && checkSelfPermission("android.permission.RECORD_AUDIO") != 0) {
    link = Link.ERROR; status = "Разреши доступ к микрофону в настройках телефона"; stopSelf(); return START_NOT_STICKY;
   }
   linkSource = source; inputLabel = ""; link = Link.CONNECTING;
   stop = false; current = ""; samples = 0; peak = 0; lastAudioAt = 0; recording = true;
   PhraseReplay.cancelActive();
   lastStatusSecond = -1; lastStatusInput = "";
   status = phoneMicrophone ? "Включаю микрофон…" : "Подключаюсь к диктофону…";
   try { notifyState(); } catch (RuntimeException error) {
    link = Link.ERROR; recording = false; status = "Открой экран записи и попробуй ещё раз"; stopSelf(); return START_NOT_STICKY;
   }
   new Thread(() -> runCapture(source), "Lecture capture").start();
  } else if ("STOP".equals(action)) {
   status = "Сохраняю запись…";
   stopCapture();
  }
  try{if(server!=null&&bleSync==null&&(Build.VERSION.SDK_INT<31||(checkSelfPermission("android.permission.BLUETOOTH_ADVERTISE")==0&&checkSelfPermission("android.permission.BLUETOOTH_CONNECT")==0)))bleSync=new BleSync(this,server);}catch(Exception ignored){}
  notifyState();
  timer.removeCallbacksAndMessages(null);
  timer.postDelayed(this::maintainSync,5000);
  return START_NOT_STICKY;
 }
 private void maintainSync(){
  long now=System.nanoTime();
  if(!recording&&visibleScreens==0&&now-lastScreenStopped>=SYNC_IDLE_NANOS
    &&!pending()&&(server==null||server.idleFor(now,SYNC_IDLE_NANOS))){
   stopSelf();
   return;
  }
  if(server!=null&&server.hasClients()){
   if(syncWake==null)syncWake=getSystemService(PowerManager.class)
     .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"lectures:sync");
   if(!syncWake.isHeld())syncWake.acquire(120000);
  }else if(syncWake!=null&&syncWake.isHeld()){
   syncWake.release();
  }
  notifyState();
  timer.postDelayed(this::maintainSync,5000);
 }
 private void runCapture(String source){
  PowerManager.WakeLock awake=getSystemService(PowerManager.class).newWakeLock(
   PowerManager.PARTIAL_WAKE_LOCK,"lectures:capture");
  String failure;
  try{
   awake.acquire();
   failure=captureRecording(source);
  }catch(RuntimeException error){
   failure="Не удалось продолжить запись";
  }finally{
   if(awake.isHeld())awake.release();
  }
  boolean saved=failure.isEmpty();
  String result=saved?(samples>0?"Запись завершена. Выбери пару":"Запись была пустой"):failure;
  timer.post(()->{
   link=saved?Link.OFF:Link.ERROR;recording=false;status=result;
   if(destroyed)return;
   if(getSharedPreferences("settings",0).getString("sync_token","").isEmpty())stopSelf();
   else notifyState();
  });
 }
 private boolean pending(){File[] files=Store.root(this).listFiles(f->Store.transferable(f.getName()));return files!=null&&files.length>0;}
 private String captureRecording(String source) {
  boolean local = "phone".equals(source) || "auto".equals(source);
  try (CaptureTake take = new CaptureTake(this, local ? "android_microphone" : "android");
       ClipMicProbe probe = autoWithClipMic ? new ClipMicProbe(this, () -> stop) : null) {
   current = take.name;
   try {
    if (local) {
     BleStream clipMic;
     try {
      clipMic = captureLocal(take, probe);
     } catch (IOException unavailable) {
      if (probe == null || stop || samples > 0) throw unavailable;
      clipMic = probe.await(() -> stop);
      if (clipMic == null && !stop) throw unavailable;
     }
     if (clipMic != null) {
      try (Socket prepared = clipMic.socket()) {
       if (!stop) {
        phoneMicrophone = false;
        timer.post(() -> { if (recording && !destroyed) notifyState(); });
        captureExternal(take, "ble", prepared, true);
       }
      }
     }
    } else {
     captureExternal(take, source, null, false);
    }
   } catch (Exception failure) {
    String message = failure.getMessage() == null ? "Не удалось продолжить запись" : failure.getMessage();
    take.setError(message);
    return message;
   }
   return "";
  } catch (Exception failure) {
   return failure.getMessage() == null ? "Не удалось сохранить запись" : failure.getMessage();
  }
 }

 private BleStream captureLocal(CaptureTake take, ClipMicProbe probe) throws Exception {
  long lastInput = 0;
  for (int attempt = 0; !stop; attempt++) {
   BleStream prepared = probe == null ? null : probe.take();
   if (prepared != null) return prepared;
   try {
    return readMicrophone(take, probe, lastInput);
   } catch (DeadMicrophone disconnected) {
    if (attempt >= 1) throw new IOException("Микрофон отключён. Сохранён доступный звук");
    lastInput = disconnected.lastInput;
    link = Link.CONNECTING;
    status = "Переключаю микрофон…";
   }
  }
  return null;
 }

 private BleStream readMicrophone(CaptureTake take, ClipMicProbe probe, long gapStart) throws Exception {
  AudioRecord microphone = null;
  try (RecordingInput route = new RecordingInput(this)) {
   int rate = 0, buffer = 0;
   for (int candidate : new int[]{16000, 48000, 44100, 8000}) {
    int size = AudioRecord.getMinBufferSize(candidate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
    if (size <= 0) continue;
    AudioRecord trial;
    try {
     trial = new AudioRecord(route.audioSource(), candidate, AudioFormat.CHANNEL_IN_MONO,
             AudioFormat.ENCODING_PCM_16BIT, Math.max(size * 2, candidate / 2));
    } catch (IllegalArgumentException unsupported) { continue; }
    if (trial.getState() == AudioRecord.STATE_INITIALIZED) {
     microphone = trial; rate = candidate; buffer = Math.max(size, 2048); break;
    }
    trial.release();
   }
   if (microphone == null) throw new IOException("Микрофон телефона недоступен");
   route.prefer(microphone);
   AtomicBoolean routeChanged = new AtomicBoolean(true);
   AudioRouting.OnRoutingChangedListener listener = ignored -> routeChanged.set(true);
   microphone.addOnRoutingChangedListener(listener, timer);
   try (BufferedOutputStream pcm = new BufferedOutputStream(new OutputStream() {
    public void write(int value) throws IOException { take.audio.write(value); }
    public void write(byte[] data, int offset, int length) throws IOException { take.audio.write(data, offset, length); }
   }, 65536)) {
    PcmResampler resampler = new PcmResampler(pcm, rate);
    short[] block = new short[buffer / 2];
    currentMicrophone = microphone;
    if (stop) return null;
    microphone.startRecording();
    if (microphone.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) throw new IOException("Не удалось запустить микрофон");
    long base = samples, clockOrigin = 0, lastInput = SystemClock.elapsedRealtime(), lastRouteCheck = 0;
    BleStream prepared = null;
    while (!stop) {
     int count = microphone.read(block, 0, block.length, AudioRecord.READ_BLOCKING);
     if (stop && count <= 0) break;
     if (count == AudioRecord.ERROR_DEAD_OBJECT) throw new DeadMicrophone(lastInput);
     if (count < 0) throw new IOException("Микрофон прервал запись. Сохранён доступный звук");
     if (count == 0) continue;
     lastInput = SystemClock.elapsedRealtime();
     if (clockOrigin == 0) {
      clockOrigin = System.nanoTime() - count * 1_000_000_000L / rate;
      if (gapStart > 0) {
       appendGap(take, Math.max(0, (lastInput - gapStart) * 16 - count * 16000L / rate));
       base = samples;
      }
     }
     if (routeChanged.getAndSet(false) || lastInput - lastRouteCheck >= 1000) {
      boolean silenced = false;
      if (Build.VERSION.SDK_INT >= 29) {
       AudioRecordingConfiguration config = microphone.getActiveRecordingConfiguration();
       silenced = config != null && config.isClientSilenced();
      }
      AudioManager manager = getSystemService(AudioManager.class);
      localInputSilenced = silenced || (manager != null && manager.isMicrophoneMute());
      take.inputMuted(localInputSilenced, samples);
      markInput(take, "phone", RecordingInput.actualLabel(microphone));
      lastRouteCheck = lastInput;
     }
     int blockPeak = 0;
     for (int index = 0; index < count; index++) {
      resampler.sample(block[index]);
      blockPeak = Math.max(blockPeak, Math.abs((int)block[index]));
     }
     pcm.flush();
     peak = blockPeak; samples = base + resampler.frames();
     lastAudioAt = lastInput;
     updateRecordingStatus();
     if (take.shouldCheckpoint()) { pcm.flush(); take.checkpoint(); }
     if (!stop && probe != null && (prepared = probe.take()) != null) break;
    }
    resampler.finish(); pcm.flush(); samples = base + resampler.frames();
    if (prepared != null) {
     try {
      AudioTimestamp stamp = new AudioTimestamp();
      if (microphone.getTimestamp(stamp, AudioTimestamp.TIMEBASE_MONOTONIC) == AudioRecord.SUCCESS
              && stamp.nanoTime > 0 && stamp.framePosition >= 0) {
       long origin = stamp.nanoTime - stamp.framePosition * 1_000_000_000L / rate;
       if (Math.abs(origin - clockOrigin) < 2_000_000_000L) clockOrigin = origin;
      }
     } catch (RuntimeException unsupported) {}
     long localFrames = Math.max(0, (prepared.firstAudioNanos() - clockOrigin) * 16000 / 1_000_000_000L);
     take.localPrefixFrames = Math.min(samples, base + localFrames);
    }
    return prepared;
   } finally {
    try { take.inputMuted(false, samples); } finally { microphone.removeOnRoutingChangedListener(listener); }
   }
  } finally {
   localInputSilenced = false;
   currentMicrophone = null;
   if (microphone != null) {
    try { microphone.stop(); } catch (RuntimeException ignored) {}
    microphone.release();
   }
  }
 }

 private void markInput(CaptureTake take, String source, String label) throws Exception {
  take.route(source, label, samples);
  linkSource = source;
  inputLabel = label;
  link = Link.CONNECTED;
 }

 private void updateRecordingStatus() {
  long seconds = samples / 16000;
  if (stop || (seconds == lastStatusSecond && inputLabel.equals(lastStatusInput))) return;
  lastStatusSecond = seconds;
  lastStatusInput = inputLabel;
  status = String.format(Locale.US, "%s · %d:%02d", inputLabel, seconds / 60, seconds % 60);
 }

 private static final class DeadMicrophone extends IOException {
  final long lastInput;
  DeadMicrophone(long lastInput) { this.lastInput = lastInput; }
 }

 private void appendGap(CaptureTake take, long missing) throws Exception {
  if (missing == 0) return;
  long from = samples;
  byte[] silence = new byte[32000];
  while (missing > 0) {
   take.checkCapacity();
   int frames = (int)Math.min(missing, 16000);
   take.audio.write(silence, 0, frames * 2);
   samples += frames;
   missing -= frames;
  }
  take.gaps.put(new JSONObject().put("start", from / 16000.0).put("end", samples / 16000.0)
          .put("seconds", (samples - from) / 16000.0));
  take.saveMetadata();
 }
 private void discover(){try{WifiManager w=(WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);multicast=w.createMulticastLock("ESP discovery");multicast.acquire();nsd=getSystemService(NsdManager.class);discovery=new NsdManager.DiscoveryListener(){public void onDiscoveryStarted(String t){}public void onDiscoveryStopped(String t){}public void onStartDiscoveryFailed(String t,int e){}public void onStopDiscoveryFailed(String t,int e){}public void onServiceLost(NsdServiceInfo i){}public void onServiceFound(NsdServiceInfo i){nsd.resolveService(i,new NsdManager.ResolveListener(){public void onResolveFailed(NsdServiceInfo v,int e){}public void onServiceResolved(NsdServiceInfo v){if(v.getHost()!=null&&v.getPort()==8766)discovered=v.getHost().getHostAddress();}});}};nsd.discoverServices("_esp-recorder._tcp.",NsdManager.PROTOCOL_DNS_SD,discovery);}catch(Exception ignored){}}
 private Socket connect(String transport, boolean trustedOnly) throws Exception {
  if ("ble".equals(transport)) {
   BleStream stream = new BleStream(this, () -> stop, SystemClock.elapsedRealtime() + 20000, trustedOnly);
   return stream.socket();
  }
  String host=getSharedPreferences("settings",0).getString("ip","");String hostname=getSharedPreferences("settings",0).getString("hostname","");Exception error=new IOException("Не указан адрес ESP");LinkedHashSet<String> choices=new LinkedHashSet<>(Arrays.asList(discovered,host,hostname));
  for(String h:choices)if(!h.isEmpty()){Socket s=new Socket();try{s.connect(new InetSocketAddress(h,8766),3000);s.setSoTimeout(4000);s.setTcpNoDelay(true);s.getOutputStream().write(("START "+getSharedPreferences("settings",0).getString("token","")+"\n").getBytes("UTF-8"));ByteArrayOutputStream line=new ByteArrayOutputStream();int b;while((b=s.getInputStream().read())!=-1&&b!=10&&line.size()<128)line.write(b);if(!line.toString("UTF-8").trim().equals("STREAM 16000"))throw new IOException("ESP не разрешила запись");return s;}catch(Exception e){error=e;s.close();}}
  throw error;
 }
 private void captureExternal(CaptureTake take, String transport, Socket prepared, boolean trustedOnly) throws Exception {
  boolean wirelessLan = "wifi".equals(transport);
  if (wirelessLan) {
   WifiManager manager = (WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);
   wifi = manager.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "lectures:wifi");
   wifi.acquire();
   discover();
  }
  String label = wirelessLan ? "Диктофон · Wi-Fi" : "Диктофон · Bluetooth";
  long gapAt = -1, lastAudio = 0;
  try {
   while (!stop) {
    link = Link.CONNECTING;
    Socket available = prepared;
    prepared = null;
    if (available == null) {
     try { available = connect(transport, trustedOnly); }
     catch (Exception disconnected) { if (stop) break; }
    }
    if (available != null) try (Socket stream = available) {
     socket = stream;
     if (stop) break;
     InputStream input = stream.getInputStream();
     DataInputStream data = new DataInputStream(input);
     long connectionBase = -1;
     while (!stop) {
      byte[] pcm;
      try { pcm = readPcm(data); }
      catch (IOException lost) { break; }
      if (stop) break;
      long now = SystemClock.elapsedRealtime();
      if (take.localPrefixFrames >= 0) {
       take.trim(take.localPrefixFrames);
       samples = take.localPrefixFrames;
       take.localPrefixFrames = -1;
      }
      if (gapAt >= 0) { appendGap(take, Math.max(0, (now-gapAt)*16 - pcm.length/2)); gapAt = -1; }
      if (connectionBase < 0) connectionBase = samples;
      markInput(take, transport, label);
      take.audio.write(pcm);
      int blockPeak = 0;
      for (int i=0; i<pcm.length; i+=2) {
       int sample=(short)((pcm[i]&255)|(pcm[i+1]<<8));
       blockPeak=Math.max(blockPeak,Math.abs(sample));
      }
      peak = blockPeak; samples += pcm.length / 2; lastAudio = now;
      lastAudioAt = now;
      if (input instanceof BleStream) {
       JSONArray lost = ((BleStream)input).takeGaps();
       for (int index=0; index<lost.length(); index++) {
        JSONObject gap = lost.getJSONObject(index);
        gap.put("start", connectionBase / 16000.0 + gap.getDouble("start"));
        take.gaps.put(gap);
       }
      }
      updateRecordingStatus();
      if (take.shouldCheckpoint()) take.checkpoint();
     }
    } finally { socket = null; }
    if (stop) break;
    if (gapAt < 0 && lastAudio > 0) gapAt = lastAudio;
    link = Link.ERROR; status = "Связь с диктофоном потеряна · переподключаюсь…";
    for (int i=0; i<20 && !stop; i++) Thread.sleep(100);
   }
  } finally {
   if (gapAt >= 0) take.gaps.put(new JSONObject().put("start", samples / 16000.0)
           .put("seconds", (SystemClock.elapsedRealtime() - gapAt) / 1000.0).put("unrecorded_tail", true));
   if (discovery != null) { try { nsd.stopServiceDiscovery(discovery); } catch (RuntimeException ignored) {} discovery = null; }
   if (multicast != null && multicast.isHeld()) multicast.release();
   if (wifi != null && wifi.isHeld()) wifi.release();
   socket = null;
  }
 }

 private static byte[] readPcm(DataInputStream input) throws IOException {
  byte[] header = new byte[6];
  input.readFully(header);
  if (header[0]!='P' || header[1]!='C' || header[2]!='M' || header[3]!='1') throw new IOException("Диктофон передал некорректный аудиопоток");
  int count = (header[4]&255) | ((header[5]&255)<<8);
  if (count == 0 || count > 4096 || count % 2 != 0) throw new IOException("Некорректный размер блока");
  byte[] pcm = new byte[count];
  input.readFully(pcm);
  return pcm;
 }

 private void stopCapture() {
  stop = true;
  AudioRecord mic = currentMicrophone;
  if (mic != null) { try { mic.stop(); } catch (RuntimeException ignored) {} }
  Socket active = socket;
  if (active != null) new Thread(() -> {
   try { active.getOutputStream().write('x'); } catch (Exception ignored) {}
   try { active.close(); } catch (IOException ignored) {}
  }, "Stop capture").start();
 }
 @Override public android.os.IBinder onBind(Intent i){return null;}
 @Override public void onDestroy(){destroyed=true;stopCapture();if(server!=null)server.close();if(bleSync!=null)bleSync.close();if(syncWake!=null&&syncWake.isHeld())syncWake.release();timer.removeCallbacksAndMessages(null);super.onDestroy();}
}
