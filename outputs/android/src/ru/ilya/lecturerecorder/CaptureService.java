package ru.ilya.lecturerecorder;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import org.json.*;
import java.io.*;
import java.net.*;
import java.text.SimpleDateFormat;
import java.util.*;

public class CaptureService extends Service {
 enum Link { OFF, CONNECTING, CONNECTED, ERROR }
 static volatile Link link=Link.OFF;
 static volatile String linkSource="";
 static volatile boolean recording=false;static volatile String status="Готово к записи",current="";static volatile long samples=0;
 static volatile int peak=0;
 private boolean phoneMicrophone;
 private boolean destroyed;
 private int foregroundType=-1;
 private volatile boolean stop;
 private volatile Socket socket;
 private final Handler timer=new Handler(Looper.getMainLooper());
 static Intent command(Context c,String action){android.content.SharedPreferences prefs=c.getSharedPreferences("settings",0);String key=prefs.getString("service_key","");if(key.isEmpty()){key=UUID.randomUUID().toString();if(!prefs.edit().putString("service_key",key).commit())throw new IllegalStateException("Не удалось сохранить настройки записи");}return new Intent(c,CaptureService.class).setAction(action).putExtra("auth",key);}
 @Override public void onCreate(){super.onCreate();try{Store.recover(this);}catch(Exception e){status="Восстановление: "+e.getMessage();}
  NotificationManager n=getSystemService(NotificationManager.class);n.createNotificationChannel(new NotificationChannel("record","Запись лекции",NotificationManager.IMPORTANCE_LOW));
 }
 private void notifyState(){Intent open=new Intent(this,MainActivity.class);PendingIntent p=PendingIntent.getActivity(this,0,open,PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT);Notification.Builder n=new Notification.Builder(this,"record").setSmallIcon(ru.ilya.lecturerecorder.R.drawable.icon).setContentTitle("Идёт запись лекции").setContentText(status).setContentIntent(p).setOnlyAlertOnce(true).setOngoing(true);
  if(recording)n.addAction(new Notification.Action.Builder(null,"Завершить запись",PendingIntent.getService(this,1,command(this,"STOP"),PendingIntent.FLAG_IMMUTABLE|PendingIntent.FLAG_UPDATE_CURRENT)).build());
  int type=Build.VERSION.SDK_INT>=30&&recording&&phoneMicrophone
   ?ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE:ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE;
  Notification notification=n.build();
  if(foregroundType!=type){
   if(Build.VERSION.SDK_INT>=29)startForeground(1,notification,type);else startForeground(1,notification);
   foregroundType=type;
  }else getSystemService(NotificationManager.class).notify(1,notification);
 }
 @Override public int onStartCommand(Intent intent,int flags,int id){String secret=getSharedPreferences("settings",0).getString("service_key","");if(intent==null||secret.isEmpty()||!secret.equals(intent.getStringExtra("auth"))){if(!recording)stopSelf();return START_NOT_STICKY;}
  String action=intent.getAction();
  if(("START".equals(action)||"START_PHONE".equals(action))&&!recording){
   phoneMicrophone="START_PHONE".equals(action);
   linkSource=phoneMicrophone?"phone":"ble";
   if(phoneMicrophone&&checkSelfPermission("android.permission.RECORD_AUDIO")!=0){
    link=Link.ERROR;status="Разреши доступ к микрофону в настройках телефона";stopSelf();return START_NOT_STICKY;
   }
   link=Link.CONNECTING;recording=true;stop=false;current="";samples=0;peak=0;
   status=phoneMicrophone?"Включаю микрофон телефона…":"Подключаюсь к ESP…";
   try{notifyState();}catch(RuntimeException error){
    link=Link.ERROR;recording=false;status="Открой экран записи и попробуй ещё раз";stopSelf();return START_NOT_STICKY;
   }
   boolean phone=phoneMicrophone;
   new Thread(()->runCapture(phone),"Lecture capture").start();
  }
  else if("STOP".equals(action)){stop=true;status="Сохраняю запись…";try{if(socket!=null){socket.getOutputStream().write('x');socket.close();}}catch(Exception ignored){}}
  if(recording){
   timer.removeCallbacksAndMessages(null);
   timer.postDelayed(this::refreshNotification,5000);
  }else stopSelf();
  return START_NOT_STICKY;
 }
 private void refreshNotification(){
  if(!recording)return;
  notifyState();
  timer.postDelayed(this::refreshNotification,5000);
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
  String result=saved?(samples>0?"Запись завершена. Выбери пару":"Запись была пустой"):failure;
  timer.post(()->{
   link=saved?Link.OFF:Link.ERROR;recording=false;status=result;
   if(destroyed)return;
   stopForeground(STOP_FOREGROUND_REMOVE);
   foregroundType=-1;
   stopSelf();
  });
 }
 private String capturePhone(){File part=null;AudioRecord microphone=null;String error="";long started=System.currentTimeMillis();
  try{
   if(Store.root(this).getUsableSpace()<100*1024*1024)throw new IOException("На телефоне мало свободного места");
   int rate=0,buffer=0;
   for(int candidate:new int[]{16000,48000,44100}){int size=AudioRecord.getMinBufferSize(candidate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT);if(size<=0)continue;AudioRecord trial=new AudioRecord(MediaRecorder.AudioSource.MIC,candidate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT,Math.max(size*2,candidate/2));if(trial.getState()==AudioRecord.STATE_INITIALIZED){microphone=trial;rate=candidate;buffer=Math.max(size,2048);break;}trial.release();}
   if(microphone==null)throw new IOException("Микрофон телефона недоступен");
   SimpleDateFormat fmt=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));current="lecture-"+fmt.format(new Date(started))+"-"+String.format(Locale.US,"%06d",started%1000*1000)+".wav";part=new File(Store.root(this),current.replace(".wav",".part"));
   if(part.exists()||new File(Store.root(this),current).exists())throw new IOException("Запись с этим временем уже существует");
   Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android_microphone").put("started_ms",started).put("awaiting_lesson",true).put("gaps",new JSONArray()));
   try(RandomAccessFile out=new RandomAccessFile(part,"rw")){Store.header(out,0);out.seek(44);try(BufferedOutputStream output=new BufferedOutputStream(new OutputStream(){public void write(int b)throws IOException{out.write(b);}public void write(byte[] b,int offset,int length)throws IOException{out.write(b,offset,length);}},65536)){PcmResampler resampler=new PcmResampler(output,rate);short[] block=new short[buffer/2];microphone.startRecording();if(microphone.getRecordingState()!=AudioRecord.RECORDSTATE_RECORDING)throw new IOException("Не удалось запустить микрофон");link=Link.CONNECTED;long checkpoint=SystemClock.elapsedRealtime();
    while(!stop){int count=microphone.read(block,0,block.length,AudioRecord.READ_BLOCKING);if(count<0)throw new IOException("Микрофон прервал запись. Сохранён доступный звук");if(count==0)continue;int blockPeak=0;
     for(int i=0;i<count;i++){
      short sample=block[i];
      resampler.sample(sample);
      blockPeak=Math.max(blockPeak,Math.abs((int)sample));
     }
     peak=blockPeak;samples=resampler.frames();status=String.format(Locale.US,"Записываю · %d:%02d",samples/16000/60,samples/16000%60);if(SystemClock.elapsedRealtime()-checkpoint>2000){output.flush();out.getFD().sync();checkpoint=SystemClock.elapsedRealtime();if(out.length()>4_200_000_000L||Store.root(this).getUsableSpace()<30*1024*1024)throw new IOException("Память заканчивается — запись сохранена");}}
    resampler.finish();output.flush();out.getFD().sync();samples=resampler.frames();}
   }
  }catch(Exception e){error=e.getMessage()==null?"Не удалось записать звук":e.getMessage();}finally{
   if(microphone!=null){try{microphone.stop();}catch(Exception ignored){}microphone.release();}
   try{if(part!=null&&part.exists()&&part.length()<=44){part.delete();new File(part.getPath()+".json").delete();}if(part!=null&&part.exists()){Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android_microphone").put("started_ms",started).put("awaiting_lesson",true).put("gaps",new JSONArray()).put("error",error));Store.seal(part);}}catch(Exception e){error="Сохранение: "+e.getMessage();}
  }
  return error;
 }
 private Socket connect()throws Exception{
  BleStream stream=new BleStream(this,()->stop);
  socket=stream.socket();
  return socket;
 }
 private String capture(){File part=null;JSONArray gaps=new JSONArray();long started=System.currentTimeMillis(),gapAt=-1;String error="";long lastSync=0,lastAudio=0;
  try{
   if(Store.root(this).getUsableSpace()<100*1024*1024)throw new IOException("На телефоне мало свободного места");
   SimpleDateFormat fmt=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);fmt.setTimeZone(TimeZone.getTimeZone("Europe/Moscow"));current="lecture-"+fmt.format(new Date(started))+"-"+(started%1000*1000)+".wav";part=new File(Store.root(this),current.replace(".wav",".part"));if(part.exists()||new File(Store.root(this),current).exists())throw new IOException("Запись с этим временем уже существует");
   Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("awaiting_lesson",true).put("gaps",gaps));
   try(RandomAccessFile out=new RandomAccessFile(part,"rw")){Store.header(out,0);out.seek(44);byte[] zeros=new byte[32000];
    while(!stop){link=Link.CONNECTING;try(Socket s=connect()){
     if(stop)break;
     if(gapAt>=0){long missing=(SystemClock.elapsedRealtime()-gapAt)*16;long from=samples;while(missing>0){if(Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");int frames=(int)Math.min(missing,16000);out.write(zeros,0,frames*2);samples+=frames;missing-=frames;}gaps.put(new JSONObject().put("start",from/16000.0).put("end",samples/16000.0).put("seconds",(samples-from)/16000.0));Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("awaiting_lesson",true).put("gaps",gaps));gapAt=-1;}
     InputStream input=s.getInputStream();long connectionBase=samples;DataInputStream in=new DataInputStream(input);while(!stop){byte[] h=new byte[6];in.readFully(h);if(h[0]!='P'||h[1]!='C'||h[2]!='M'||h[3]!='1')throw new IOException("Некорректный поток ESP");int count=(h[4]&255)|((h[5]&255)<<8);if(count==0)throw new EOFException("ESP завершила поток");if(count>4096||count%2!=0)throw new IOException("Некорректный размер блока");byte[] b=new byte[count];in.readFully(b);if(stop)break;link=Link.CONNECTED;out.write(b);
      int blockPeak=0;
      for(int i=0;i<count;i+=2){
       int sample=(short)((b[i]&255)|(b[i+1]<<8));
       blockPeak=Math.max(blockPeak,Math.abs(sample));
      }
      peak=blockPeak;samples+=count/2;lastAudio=SystemClock.elapsedRealtime();if(input instanceof BleStream){JSONArray lost=((BleStream)input).takeGaps();for(int i=0;i<lost.length();i++){JSONObject gap=lost.getJSONObject(i);gap.put("start",connectionBase/16000.0+gap.getDouble("start"));gaps.put(gap);}}status=String.format(Locale.US,"Записываю · %d:%02d",samples/16000/60,samples/16000%60);if(SystemClock.elapsedRealtime()-lastSync>2000){out.getFD().sync();Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("awaiting_lesson",true).put("gaps",gaps));lastSync=SystemClock.elapsedRealtime();}if(out.length()>4_200_000_000L||Store.root(this).getUsableSpace()<30*1024*1024)throw new StorageException("Память заканчивается — запись сохранена");}
    }catch(StorageException e){throw e;}catch(Exception e){if(stop)break;link=Link.ERROR;if(samples>0&&gapAt<0)gapAt=lastAudio>0?lastAudio:SystemClock.elapsedRealtime();status="Связь потеряна — переподключаюсь…";for(int i=0;i<20&&!stop;i++)Thread.sleep(100);}}
    if(gapAt>=0)gaps.put(new JSONObject().put("start",samples/16000.0).put("seconds",(SystemClock.elapsedRealtime()-gapAt)/1000.0).put("unrecorded_tail",true));out.getFD().sync();
   }
  }catch(Exception e){error=e.getMessage()==null?"Не удалось записать звук ESP":e.getMessage();}finally{try{if(part!=null&&part.exists()&&part.length()<=44){part.delete();new File(part.getPath()+".json").delete();}if(part!=null&&part.exists()){Store.write(new File(part.getPath()+".json"),new JSONObject().put("source","android").put("started_ms",started).put("awaiting_lesson",true).put("gaps",gaps).put("error",error));Store.seal(part);}}catch(Exception e){error="Сохранение: "+e.getMessage();}
   socket=null;
  }
  return error;
 }
 private static class StorageException extends IOException{StorageException(String s){super(s);}}
 @Override public android.os.IBinder onBind(Intent i){return null;}
 @Override public void onDestroy(){destroyed=true;stop=true;try{if(socket!=null)socket.close();}catch(Exception ignored){}timer.removeCallbacksAndMessages(null);super.onDestroy();}
}
