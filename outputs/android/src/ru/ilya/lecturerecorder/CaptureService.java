package ru.ilya.lecturerecorder;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.nsd.*;
import android.net.wifi.WifiManager;
import android.os.*;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import org.json.*;
import java.io.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

public class CaptureService extends Service {
 enum Link { OFF, CONNECTING, CONNECTED, ERROR }
 static volatile Link link=Link.OFF;
 static volatile String linkSource="";
 static volatile boolean recording=false;static volatile String status="Готово к записи",current="";static volatile long samples=0;
 private boolean phoneMicrophone;
 private boolean destroyed;
 private int foregroundType=-1;
 private volatile boolean stop=false;private volatile Socket socket;private SyncServer server;private BleSync bleSync;private PowerManager.WakeLock syncWake;private WifiManager.WifiLock wifi;private WifiManager.MulticastLock multicast;private NsdManager nsd;private NsdManager.DiscoveryListener discovery;private volatile String discovered="";private Handler timer=new Handler(Looper.getMainLooper());
 static void provision(Context c)throws Exception{File f=new File(c.getFilesDir(),"provision.json");if(!f.exists())return;JSONObject j=new JSONObject(Store.read(f));android.content.SharedPreferences.Editor e=c.getSharedPreferences("settings",0).edit();for(String k:new String[]{"ip","hostname","token","sync_token","ble_address"})if(j.has(k))e.putString(k,j.getString(k));if(!e.commit())throw new IOException("Настройки не сохранены");if(!f.delete())throw new IOException("Настройки не закрыты");}
 static Intent command(Context c,String action){android.content.SharedPreferences prefs=c.getSharedPreferences("settings",0);String key=prefs.getString("service_key","");if(key.isEmpty()){key=UUID.randomUUID().toString();if(!prefs.edit().putString("service_key",key).commit())throw new IllegalStateException("Не удалось сохранить настройки записи");}return new Intent(c,CaptureService.class).setAction(action).putExtra("auth",key);}
 @Override public void onCreate(){super.onCreate();try{provision(this);Store.recover(this);}catch(Exception e){status="Восстановление: "+e.getMessage();}
  NotificationManager n=getSystemService(NotificationManager.class);n.createNotificationChannel(new NotificationChannel("record","Запись лекции",NotificationManager.IMPORTANCE_LOW));
 }
 private void notifyState(){Intent open=new Intent(this,MainActivity.class);PendingIntent p=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);Notification.Builder n=new Notification.Builder(this,"record").setSmallIcon(ru.ilya.lecturerecorder.R.drawable.icon).setContentTitle(recording?"Идёт запись лекции":"Перенос записей на Mac").setContentText(recording?status:SyncServer.status).setContentIntent(p).setOngoing(true);
  if(recording)n.addAction(new Notification.Action.Builder(null,"Остановить и сохранить",PendingIntent.getService(this,1,command(this,"STOP"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build());
  int type=Build.VERSION.SDK_INT>=30&&recording&&phoneMicrophone
   ?ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE:ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
  Notification notification=n.build();
  if(foregroundType!=type){
   if(Build.VERSION.SDK_INT>=29)startForeground(1,notification,type);else startForeground(1,notification);
   foregroundType=type;
  }else getSystemService(NotificationManager.class).notify(1,notification);
 }
 @Override public int onStartCommand(Intent intent,int flags,int id){String secret=getSharedPreferences("settings",0).getString("service_key","");if(intent==null||secret.isEmpty()||!secret.equals(intent.getStringExtra("auth"))){if(!recording)stopSelf();return START_NOT_STICKY;}
  boolean paired=!getSharedPreferences("settings",0).getString("sync_token","").isEmpty();
  try{if(paired&&server==null)server=new SyncServer(this);}catch(Exception e){status="Перенос: "+e.getMessage();}
  String action=intent.getAction();
  if(("START".equals(action)||"START_PHONE".equals(action))&&!recording){
   phoneMicrophone="START_PHONE".equals(action);
   linkSource=phoneMicrophone?"phone":getSharedPreferences("settings",0).getString("transport","wifi");
   if(phoneMicrophone&&checkSelfPermission("android.permission.RECORD_AUDIO")!=0){
    link=Link.ERROR;status="Разреши доступ к микрофону в настройках телефона";stopSelf();return START_NOT_STICKY;
   }
   link=Link.CONNECTING;recording=true;stop=false;samples=0;
   status=phoneMicrophone?"Включаю микрофон телефона…":"Подключаюсь к ESP…";
   try{notifyState();}catch(RuntimeException error){
    link=Link.ERROR;recording=false;status="Открой экран записи и попробуй ещё раз";stopSelf();return START_NOT_STICKY;
   }
   boolean phone=phoneMicrophone;
   new Thread(()->runCapture(phone),"Lecture capture").start();
  }
  else if("STOP".equals(action)){stop=true;status="Сохраняю запись…";try{if(socket!=null){socket.getOutputStream().write('x');socket.close();}}catch(Exception ignored){}}
  try{if(server!=null&&bleSync==null&&(Build.VERSION.SDK_INT<31||(checkSelfPermission("android.permission.BLUETOOTH_ADVERTISE")==0&&checkSelfPermission("android.permission.BLUETOOTH_CONNECT")==0)))bleSync=new BleSync(this,server);}catch(Exception ignored){}
  notifyState();timer.removeCallbacksAndMessages(null);timer.postDelayed(new Runnable(){public void run(){if(!recording&&!pending()&&server!=null&&server.clients==0&&System.currentTimeMillis()-server.lastUse>60000){stopSelf();return;}if(server!=null&&server.clients>0){if(syncWake==null)syncWake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"lectures:sync");if(!syncWake.isHeld())syncWake.acquire(120000);}else if(syncWake!=null&&syncWake.isHeld())syncWake.release();notifyState();timer.postDelayed(this,5000);}},5000);return START_NOT_STICKY;
 }
 private void runCapture(boolean phone){
  PowerManager.WakeLock awake=getSystemService(PowerManager.class).newWakeLock(
   PowerManager.PARTIAL_WAKE_LOCK,"lectures:capture");
  String failure;
  try{
   awake.acquire();
   failure=phone?capturePhone():capture();
  }catch(RuntimeException error){
   failure="Не удалось продолжить запись";
  }finally{
   if(awake.isHeld())awake.release();
  }
  boolean saved=failure.isEmpty();
  String result=saved?"Запись сохранена на телефоне":failure;
  timer.post(()->{
   link=saved?Link.OFF:Link.ERROR;recording=false;status=result;
   if(destroyed)return;
   if(getSharedPreferences("settings",0).getString("sync_token","").isEmpty())stopSelf();
   else notifyState();
  });
 }
 private boolean pending(){File[] files=Store.root(this).listFiles(f->Store.transferable(f.getName()));return files!=null&&files.length>0;}
 private String capturePhone(){File part=null;AudioRecord microphone=null;String error="";long started=System.currentTimeMillis();
  try{
   if(Store.root(this).getUsableSpace()<100*1024*1024)throw new IOException("На телефоне мало свободного места");
   int rate=0,buffer=0;
   for(int candidate:new int[]{16000,48000,44100}){int size=AudioRecord.getMinBufferSize(candidate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);if(size<=0)continue;AudioRecord trial=new AudioRecord(MediaRecorder.AudioSource.MIC,candidate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(size*2,candidate/2));if(trial.getState()==AudioRecord.STATE_INITIALIZED){microphone=trial;rate=candidate;buffer=Math.max(size,2048);break;}trial.release();}
   if(microphone==null)throw new IOException("Микрофон телефона недоступен");
   SimpleDateFormat fmt=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));current="lecture-"+fmt.format(new Date(started))+"-"+String.format(Locale.US,"%06d",started%1000*1000)+".wav";part=new File(Store.root(this),current.replace(".wav",".part"));
   if(part.exists()||new File(Store.root(this),current).exists())throw new IOException("Запись с этим временем уже существует");
   Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android_microphone").put("started_ms",started).put("gaps",new JSONArray()));
   try(RandomAccessFile out=new RandomAccessFile(part,"rw")){Store.header(out,0);out.seek(44);try(BufferedOutputStream output=new BufferedOutputStream(new OutputStream(){public void write(int b)throws IOException{out.write(b);}public void write(byte[] b,int offset,int length)throws IOException{out.write(b,offset,length);}},65536)){PcmResampler resampler=new PcmResampler(output,rate);short[] block=new short[buffer/2];microphone.startRecording();if(microphone.getRecordingState()!=AudioRecord.RECORDSTATE_RECORDING)throw new IOException("Не удалось запустить микрофон");link=Link.CONNECTED;long checkpoint=SystemClock.elapsedRealtime();
    while(!stop){int count=microphone.read(block,0,block.length,AudioRecord.READ_BLOCKING);if(count<0)throw new IOException("Микрофон прервал запись. Сохранён доступный звук");if(count==0)continue;for(int i=0;i<count;i++)resampler.sample(block[i]);samples=resampler.frames();status=String.format(Locale.US,"Записываю · %d:%02d",samples/16000/60,samples/16000%60);if(SystemClock.elapsedRealtime()-checkpoint>2000){output.flush();out.getFD().sync();checkpoint=SystemClock.elapsedRealtime();if(out.length()>4_200_000_000L||Store.root(this).getUsableSpace()<30*1024*1024)throw new IOException("Память заканчивается — запись сохранена");}}
    resampler.finish();output.flush();out.getFD().sync();samples=resampler.frames();}
   }
  }catch(Exception e){error=e.getMessage()==null?"Не удалось записать звук":e.getMessage();}finally{
   if(microphone!=null){try{microphone.stop();}catch(Exception ignored){}microphone.release();}
   try{if(part!=null&&part.exists()){Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android_microphone").put("started_ms",started).put("gaps",new JSONArray()).put("error",error));Store.seal(part);}}catch(Exception e){error="Сохранение: "+e.getMessage();}
  }
  return error;
 }
 private void discover(){try{WifiManager w=(WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);multicast=w.createMulticastLock("ESP discovery");multicast.acquire();nsd=getSystemService(NsdManager.class);discovery=new NsdManager.DiscoveryListener(){public void onDiscoveryStarted(String t){}public void onDiscoveryStopped(String t){}public void onStartDiscoveryFailed(String t,int e){}public void onStopDiscoveryFailed(String t,int e){}public void onServiceLost(NsdServiceInfo i){}public void onServiceFound(NsdServiceInfo i){nsd.resolveService(i,new NsdManager.ResolveListener(){public void onResolveFailed(NsdServiceInfo v,int e){}public void onServiceResolved(NsdServiceInfo v){if(v.getHost()!=null&&v.getPort()==8766)discovered=v.getHost().getHostAddress();}});}};nsd.discoverServices("_esp-recorder._tcp.",NsdManager.PROTOCOL_DNS_SD,discovery);}catch(Exception ignored){}}
 private Socket connect()throws Exception{
  if(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")){BleStream stream=new BleStream(this,()->stop);socket=stream.socket();return socket;}
  String host=getSharedPreferences("settings",0).getString("ip","");String hostname=getSharedPreferences("settings",0).getString("hostname","");Exception error=new IOException("Не указан адрес ESP");LinkedHashSet<String> choices=new LinkedHashSet<>(Arrays.asList(discovered,host,hostname));
  for(String h:choices)if(!h.isEmpty()){Socket s=new Socket();try{s.connect(new InetSocketAddress(h,8766),3000);s.setSoTimeout(4000);s.setTcpNoDelay(true);socket=s;s.getOutputStream().write(("START "+getSharedPreferences("settings",0).getString("token","")+"\n").getBytes("UTF-8"));ByteArrayOutputStream line=new ByteArrayOutputStream();int b;while((b=s.getInputStream().read())!=-1&&b!=10&&line.size()<128)line.write(b);if(!line.toString("UTF-8").trim().equals("STREAM 16000"))throw new IOException("ESP не разрешила запись");return s;}catch(Exception e){error=e;s.close();}}
  throw error;
 }
 private String capture(){File part=null;JSONArray gaps=new JSONArray();long started=System.currentTimeMillis(),gapAt=-1;String error="";long lastSync=0,lastAudio=0;
  try{
   if(Store.root(this).getUsableSpace()<100*1024*1024)throw new IOException("На телефоне мало свободного места");
   if(getSharedPreferences("settings",0).getString("transport","ble").equals("wifi")){
    WifiManager manager=(WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);
    wifi=manager.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF,"lectures:wifi");
    wifi.acquire();
    discover();
   }
   SimpleDateFormat fmt=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));current="lecture-"+fmt.format(new Date(started))+"-"+(started%1000*1000)+".wav";part=new File(Store.root(this),current.replace(".wav",".part"));if(part.exists()||new File(Store.root(this),current).exists())throw new IOException("Запись с этим временем уже существует");
   Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));
   try(RandomAccessFile out=new RandomAccessFile(part,"rw")){Store.header(out,0);out.seek(44);byte[] zeros=new byte[32000];
    while(!stop){link=Link.CONNECTING;try(Socket s=connect()){
     if(stop)break;
     if(gapAt>=0){long missing=(SystemClock.elapsedRealtime()-gapAt)*16;long from=samples;while(missing>0){if(Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");int frames=(int)Math.min(missing,16000);out.write(zeros,0,frames*2);samples+=frames;missing-=frames;}gaps.put(new JSONObject().put("start",from/16000.0).put("end",samples/16000.0).put("seconds",(samples-from)/16000.0));Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));gapAt=-1;}
     InputStream input=s.getInputStream();long connectionBase=samples;DataInputStream in=new DataInputStream(input);while(!stop){byte[] h=new byte[6];in.readFully(h);if(h[0]!='P'||h[1]!='C'||h[2]!='M'||h[3]!='1')throw new IOException("Некорректный поток ESP");int count=(h[4]&255)|((h[5]&255)<<8);if(count==0)throw new EOFException("ESP завершила поток");if(count>4096||count%2!=0)throw new IOException("Некорректный размер блока");byte[] b=new byte[count];in.readFully(b);if(stop)break;link=Link.CONNECTED;out.write(b);samples+=count/2;lastAudio=SystemClock.elapsedRealtime();if(input instanceof BleStream){JSONArray lost=((BleStream)input).takeGaps();for(int i=0;i<lost.length();i++){JSONObject gap=lost.getJSONObject(i);gap.put("start",connectionBase/16000.0+gap.getDouble("start"));gaps.put(gap);}}status=String.format(Locale.US,"Записываю · %d:%02d",samples/16000/60,samples/16000%60);if(SystemClock.elapsedRealtime()-lastSync>2000){out.getFD().sync();Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));lastSync=SystemClock.elapsedRealtime();}if(out.length()>4_200_000_000L||Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");}
    }catch(StorageException e){throw e;}catch(Exception e){if(stop)break;link=Link.ERROR;if(samples>0&&gapAt<0)gapAt=lastAudio>0?lastAudio:SystemClock.elapsedRealtime();status="Связь потеряна — переподключаюсь…";for(int i=0;i<20&&!stop;i++)Thread.sleep(100);}}
    if(gapAt>=0)gaps.put(new JSONObject().put("start",samples/16000.0).put("seconds",(SystemClock.elapsedRealtime()-gapAt)/1000.0).put("unrecorded_tail",true));out.getFD().sync();
   }
  }catch(Exception e){error=e.getMessage()==null?"Не удалось записать звук ESP":e.getMessage();}finally{try{if(part!=null&&part.exists()){Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps).put("error",error));Store.seal(part);}}catch(Exception e){error="Сохранение: "+e.getMessage();}
   try{if(discovery!=null)nsd.stopServiceDiscovery(discovery);}catch(Exception ignored){}if(multicast!=null&&multicast.isHeld())multicast.release();if(wifi!=null&&wifi.isHeld())wifi.release();socket=null;
  }
  return error;
 }
 private static class StorageException extends IOException{StorageException(String s){super(s);}}
 @Override public android.os.IBinder onBind(Intent i){return null;}
 @Override public void onDestroy(){destroyed=true;stop=true;try{if(socket!=null)socket.close();}catch(Exception ignored){}if(server!=null)server.close();if(bleSync!=null)bleSync.close();if(syncWake!=null&&syncWake.isHeld())syncWake.release();timer.removeCallbacksAndMessages(null);super.onDestroy();}
}
