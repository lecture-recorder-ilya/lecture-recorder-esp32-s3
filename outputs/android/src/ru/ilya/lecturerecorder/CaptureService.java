package ru.ilya.lecturerecorder;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.net.nsd.*;
import android.net.wifi.WifiManager;
import android.os.*;
import org.json.*;
import java.io.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;
import java.util.concurrent.*;

public class CaptureService extends Service {
 static volatile boolean recording=false;static volatile String status="Готово к записи",current="";static volatile long samples=0;
 private volatile boolean stop=false;private volatile Socket socket;private Thread worker;private SyncServer server;private BleSync bleSync;private PowerManager.WakeLock syncWake;private PowerManager.WakeLock wake;private WifiManager.WifiLock wifi;private WifiManager.MulticastLock multicast;private NsdManager nsd;private NsdManager.DiscoveryListener discovery;private volatile String discovered="";private Handler timer=new Handler(Looper.getMainLooper());
 static void provision(Context c)throws Exception{File f=new File(c.getFilesDir(),"provision.json");if(!f.exists())return;JSONObject j=new JSONObject(Store.read(f));android.content.SharedPreferences.Editor e=c.getSharedPreferences("settings",0).edit();for(String k:new String[]{"ip","hostname","token","sync_token","ble_address"})if(j.has(k))e.putString(k,j.getString(k));if(!e.commit())throw new IOException("Настройки не сохранены");if(!f.delete())throw new IOException("Настройки не закрыты");}
 static Intent command(Context c,String action){return new Intent(c,CaptureService.class).setAction(action).putExtra("auth",c.getSharedPreferences("settings",0).getString("sync_token",""));}
 @Override public void onCreate(){super.onCreate();try{provision(this);Store.recover(this);}catch(Exception e){status="Восстановление: "+e.getMessage();}
  NotificationManager n=getSystemService(NotificationManager.class);n.createNotificationChannel(new NotificationChannel("record","Запись с ESP",NotificationManager.IMPORTANCE_LOW));
 }
 private void notifyState(){Intent open=new Intent(this,MainActivity.class);PendingIntent p=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);Notification.Builder n=new Notification.Builder(this,"record").setSmallIcon(ru.ilya.lecturerecorder.R.drawable.icon).setContentTitle(recording?"Идёт запись лекции":"Перенос записей на Mac").setContentText(recording?status:SyncServer.status).setContentIntent(p).setOngoing(true);
  if(recording)n.addAction(new Notification.Action.Builder(null,"Остановить и сохранить",PendingIntent.getService(this,1,command(this,"STOP"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build());
  startForeground(1,n.build(),ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE);
 }
 @Override public int onStartCommand(Intent intent,int flags,int id){String secret=getSharedPreferences("settings",0).getString("sync_token","");if(intent==null||secret.isEmpty()||!secret.equals(intent.getStringExtra("auth"))){if(!recording)stopSelf();return START_NOT_STICKY;}
  try{if(server==null)server=new SyncServer(this);}catch(Exception e){status="Перенос: "+e.getMessage();}
  String action=intent.getAction();if("START".equals(action)&&!recording){recording=true;stop=false;samples=0;status="Подключаюсь к ESP…";notifyState();worker=new Thread(()->capture(),"ESP capture");worker.start();}
  else if("STOP".equals(action)){stop=true;status="Сохраняю запись…";try{if(socket!=null){socket.getOutputStream().write('x');socket.close();}}catch(Exception ignored){}}
  try{if(bleSync==null&&checkSelfPermission("android.permission.BLUETOOTH_ADVERTISE")==0)bleSync=new BleSync(this,server);}catch(Exception ignored){}
  notifyState();timer.removeCallbacksAndMessages(null);timer.postDelayed(new Runnable(){public void run(){if(!recording&&!pending()&&server!=null&&server.clients==0&&System.currentTimeMillis()-server.lastUse>60000){stopSelf();return;}if(server!=null&&server.clients>0){if(syncWake==null)syncWake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"lectures:sync");if(!syncWake.isHeld())syncWake.acquire(120000);}else if(syncWake!=null&&syncWake.isHeld())syncWake.release();notifyState();timer.postDelayed(this,5000);}},5000);return START_NOT_STICKY;
 }
 private boolean pending(){File[] files=Store.root(this).listFiles(f->f.getName().matches("lecture-[0-9-]+\\.wav"));return files!=null&&files.length>0;}
 private void discover(){try{WifiManager w=(WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);multicast=w.createMulticastLock("ESP discovery");multicast.acquire();nsd=getSystemService(NsdManager.class);discovery=new NsdManager.DiscoveryListener(){public void onDiscoveryStarted(String t){}public void onDiscoveryStopped(String t){}public void onStartDiscoveryFailed(String t,int e){}public void onStopDiscoveryFailed(String t,int e){}public void onServiceLost(NsdServiceInfo i){}public void onServiceFound(NsdServiceInfo i){nsd.resolveService(i,new NsdManager.ResolveListener(){public void onResolveFailed(NsdServiceInfo v,int e){}public void onServiceResolved(NsdServiceInfo v){if(v.getHost()!=null&&v.getPort()==8766)discovered=v.getHost().getHostAddress();}});}};nsd.discoverServices("_esp-recorder._tcp.",NsdManager.PROTOCOL_DNS_SD,discovery);}catch(Exception ignored){}}
 private Socket connect()throws Exception{
  if(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")){BleStream stream=new BleStream(this,()->stop);socket=stream.socket();return socket;}
  String host=getSharedPreferences("settings",0).getString("ip","");String hostname=getSharedPreferences("settings",0).getString("hostname","");Exception error=new IOException("Не указан адрес ESP");LinkedHashSet<String> choices=new LinkedHashSet<>(Arrays.asList(discovered,host,hostname));
  for(String h:choices)if(!h.isEmpty()){Socket s=new Socket();try{s.connect(new InetSocketAddress(h,8766),3000);s.setSoTimeout(4000);s.setTcpNoDelay(true);socket=s;s.getOutputStream().write(("START "+getSharedPreferences("settings",0).getString("token","")+"\n").getBytes("UTF-8"));ByteArrayOutputStream line=new ByteArrayOutputStream();int b;while((b=s.getInputStream().read())!=-1&&b!=10&&line.size()<128)line.write(b);if(!line.toString("UTF-8").trim().equals("STREAM 16000"))throw new IOException("ESP не разрешила запись");return s;}catch(Exception e){error=e;s.close();}}
  throw error;
 }
 private void capture(){File part=null;JSONArray gaps=new JSONArray();long started=System.currentTimeMillis(),gapAt=-1;String error="";long lastSync=0,lastAudio=0;
  try{
   if(Store.root(this).getUsableSpace()<100*1024*1024)throw new IOException("На телефоне мало свободного места");
   wake=getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"lectures:record");wake.acquire();WifiManager w=(WifiManager)getApplicationContext().getSystemService(WIFI_SERVICE);wifi=w.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF,"lectures:wifi");if(getSharedPreferences("settings",0).getString("transport","ble").equals("wifi")){wifi.acquire();discover();}
   SimpleDateFormat fmt=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));current="lecture-"+fmt.format(new Date(started))+"-"+(started%1000*1000)+".wav";part=new File(Store.root(this),current.replace(".wav",".part"));if(part.exists()||new File(Store.root(this),current).exists())throw new IOException("Запись с этим временем уже существует");
   Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));
   try(RandomAccessFile out=new RandomAccessFile(part,"rw")){Store.header(out,0);out.seek(44);byte[] zeros=new byte[32000];
    while(!stop){try(Socket s=connect()){
     if(stop)break;
     if(gapAt>=0){long missing=(SystemClock.elapsedRealtime()-gapAt)*16;long from=samples;while(missing>0){if(Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");int frames=(int)Math.min(missing,16000);out.write(zeros,0,frames*2);samples+=frames;missing-=frames;}gaps.put(new JSONObject().put("start",from/16000.0).put("end",samples/16000.0).put("seconds",(samples-from)/16000.0));Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));gapAt=-1;}
     InputStream input=s.getInputStream();long connectionBase=samples;DataInputStream in=new DataInputStream(input);while(!stop){byte[] h=new byte[6];in.readFully(h);if(h[0]!='P'||h[1]!='C'||h[2]!='M'||h[3]!='1')throw new IOException("Некорректный поток ESP");int count=(h[4]&255)|((h[5]&255)<<8);if(count==0)throw new EOFException("ESP завершила поток");if(count>4096||count%2!=0)throw new IOException("Некорректный размер блока");byte[] b=new byte[count];in.readFully(b);if(stop)break;out.write(b);samples+=count/2;lastAudio=SystemClock.elapsedRealtime();if(input instanceof BleStream){JSONArray lost=((BleStream)input).takeGaps();for(int i=0;i<lost.length();i++){JSONObject gap=lost.getJSONObject(i);gap.put("start",connectionBase/16000.0+gap.getDouble("start"));gaps.put(gap);}}status=String.format(Locale.US,"Записываю · %d:%02d",samples/16000/60,samples/16000%60);if(SystemClock.elapsedRealtime()-lastSync>2000){out.getFD().sync();Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps));lastSync=SystemClock.elapsedRealtime();}if(out.length()>4_200_000_000L||Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");}
    }catch(StorageException e){throw e;}catch(Exception e){if(stop)break;if(samples>0&&gapAt<0)gapAt=lastAudio>0?lastAudio:SystemClock.elapsedRealtime();status="Связь потеряна — переподключаюсь…";for(int i=0;i<20&&!stop;i++)Thread.sleep(100);}}
    if(gapAt>=0)gaps.put(new JSONObject().put("start",samples/16000.0).put("seconds",(SystemClock.elapsedRealtime()-gapAt)/1000.0).put("unrecorded_tail",true));out.getFD().sync();
   }
  }catch(Exception e){error=e.getMessage();}finally{try{if(part!=null&&part.exists()){Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("gaps",gaps).put("error",error));Store.seal(part);}}catch(Exception e){error="Сохранение: "+e.getMessage();}
   try{if(discovery!=null)nsd.stopServiceDiscovery(discovery);}catch(Exception ignored){}if(multicast!=null&&multicast.isHeld())multicast.release();if(wifi!=null&&wifi.isHeld())wifi.release();if(wake!=null&&wake.isHeld())wake.release();socket=null;recording=false;status=error.isEmpty()?"Запись сохранена на телефоне":error;
  }
 }
 private static class StorageException extends IOException{StorageException(String s){super(s);}}
 @Override public android.os.IBinder onBind(Intent i){return null;}
 @Override public void onDestroy(){stop=true;try{if(socket!=null)socket.close();}catch(Exception ignored){}if(server!=null)server.close();if(bleSync!=null)bleSync.close();if(syncWake!=null&&syncWake.isHeld())syncWake.release();timer.removeCallbacksAndMessages(null);super.onDestroy();}
}
