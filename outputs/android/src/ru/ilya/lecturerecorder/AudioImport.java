package ru.ilya.lecturerecorder;

import android.content.Context;
import android.media.AudioFormat;
import android.media.MediaCodec;
import android.media.MediaExtractor;
import android.media.MediaFormat;
import android.net.Uri;
import android.provider.OpenableColumns;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.text.SimpleDateFormat;
import java.util.*;
import org.json.JSONObject;

final class AudioImport {
 static volatile boolean busy=false;
 static volatile String status="";
 static String name(Context c,Uri uri){String result="Запись пары";try(android.database.Cursor cursor=c.getContentResolver().query(uri,new String[]{OpenableColumns.DISPLAY_NAME},null,null,null)){if(cursor!=null&&cursor.moveToFirst())result=cursor.getString(0);}catch(Exception ignored){}return result;}
 static synchronized void start(Context context,Uri uri){
  if(busy)return;busy=true;status="Подготавливаю аудио…";Context app=context.getApplicationContext();
  new Thread(()->{File importing=null;try{
   String title=name(app,uri);long now=System.currentTimeMillis();String stamp=new SimpleDateFormat("yyyy-MM-dd-HH-mm-ss-SSS",Locale.US).format(new Date(now));String base="lecture-"+stamp+"-"+String.format(Locale.US,"%06d",new java.security.SecureRandom().nextInt(1000000));
   importing=new File(Store.root(app),base+".importing");decode(app,uri,importing);
   if(importing.length()<=44)throw new IOException("Разборчивое аудио в файле не найдено");
   File part=new File(Store.root(app),base+".part");if(!importing.renameTo(part))throw new IOException("Не удалось сохранить подготовленную запись");
   JSONObject meta=new JSONObject().put("imported",true).put("original_name",title).put("title",title.replaceFirst("\\.[^.]+$","")).put("started_ms",now);
   Store.write(new File(part.getPath()+".json"),meta);Store.seal(part);
   status="Запись импортирована";
   if(!app.getSharedPreferences("settings",0).getString("sync_token","").isEmpty())app.startForegroundService(CaptureService.command(app,"SYNC"));
  }catch(Exception e){status="Не удалось открыть запись: "+(e.getMessage()==null?"попробуй WAV, MP3 или M4A":e.getMessage());if(importing!=null)importing.delete();}finally{busy=false;}},"Импорт записи пары").start();
 }
 private static void decode(Context c,Uri uri,File target)throws Exception{
  MediaExtractor extractor=new MediaExtractor();MediaCodec codec=null;
  try{
   extractor.setDataSource(c,uri,null);int track=-1;MediaFormat format=null;
   for(int i=0;i<extractor.getTrackCount();i++){MediaFormat f=extractor.getTrackFormat(i);if(f.getString(MediaFormat.KEY_MIME).startsWith("audio/")){track=i;format=f;break;}}
   if(track<0)throw new IOException("В файле нет звуковой дорожки");
   if(format.containsKey(MediaFormat.KEY_DURATION)&&format.getLong(MediaFormat.KEY_DURATION)>8L*3600*1000000)throw new IOException("Выбери запись длительностью до 8 часов");
   extractor.selectTrack(track);String mime=format.getString(MediaFormat.KEY_MIME);boolean raw=mime.equals("audio/raw");
   if(!raw){codec=MediaCodec.createDecoderByType(mime);format.setInteger(MediaFormat.KEY_PCM_ENCODING,AudioFormat.ENCODING_PCM_16BIT);codec.configure(format,null,null,0);codec.start();}
   int sampleRate=format.getInteger(MediaFormat.KEY_SAMPLE_RATE),channels=format.getInteger(MediaFormat.KEY_CHANNEL_COUNT),encoding=format.containsKey(MediaFormat.KEY_PCM_ENCODING)?format.getInteger(MediaFormat.KEY_PCM_ENCODING):AudioFormat.ENCODING_PCM_16BIT;
   StereoPcmMix stereo = raw && channels == 2 && encoding == AudioFormat.ENCODING_PCM_16BIT
           ? new StereoPcmMix() : null;
   long dataOffset;
   try (RandomAccessFile header = new RandomAccessFile(target, "rw")) {
    Store.header(header, 0);
    dataOffset = header.getFilePointer();
   }
   try(OutputStream output=new BufferedOutputStream(new FileOutputStream(target,true),65536)){
    PcmResampler resampler=new PcmResampler(output,sampleRate);boolean ended=false,sent=false;long last=System.currentTimeMillis(),duration=format.containsKey(MediaFormat.KEY_DURATION)?format.getLong(MediaFormat.KEY_DURATION):0;
    MediaCodec.BufferInfo info=new MediaCodec.BufferInfo();ByteBuffer rawBuffer=ByteBuffer.allocate(1024*1024);
    while(!ended){
     if (raw) {
      rawBuffer.clear();
      int size = extractor.readSampleData(rawBuffer, 0);
      if (size < 0) { ended = true; continue; }
      rawBuffer.position(0);
      rawBuffer.limit(size);
      if (stereo == null) consume(rawBuffer, channels, encoding, resampler);
      else stereo.consume(rawBuffer, resampler);
      extractor.advance();
      last = System.currentTimeMillis();
     }
     else{
      if(!sent){int index=codec.dequeueInputBuffer(10000);if(index>=0){ByteBuffer input=codec.getInputBuffer(index);int size=extractor.readSampleData(input,0);if(size<0){codec.queueInputBuffer(index,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM);sent=true;}else{codec.queueInputBuffer(index,0,size,Math.max(0,extractor.getSampleTime()),0);extractor.advance();last=System.currentTimeMillis();}}}
      int index=codec.dequeueOutputBuffer(info,10000);
      if(index==MediaCodec.INFO_OUTPUT_FORMAT_CHANGED){MediaFormat decoded=codec.getOutputFormat();int rate=decoded.getInteger(MediaFormat.KEY_SAMPLE_RATE);if(rate!=sampleRate){if(resampler.frames()>0)throw new IOException("Частота аудио изменилась внутри файла");sampleRate=rate;resampler=new PcmResampler(output,rate);}channels=decoded.getInteger(MediaFormat.KEY_CHANNEL_COUNT);encoding=decoded.containsKey(MediaFormat.KEY_PCM_ENCODING)?decoded.getInteger(MediaFormat.KEY_PCM_ENCODING):AudioFormat.ENCODING_PCM_16BIT;}
      if(index>=0){ByteBuffer buffer=codec.getOutputBuffer(index);if(info.size>0&&(info.flags&MediaCodec.BUFFER_FLAG_CODEC_CONFIG)==0){buffer.position(info.offset);buffer.limit(info.offset+info.size);consume(buffer,channels,encoding,resampler);}ended=(info.flags&MediaCodec.BUFFER_FLAG_END_OF_STREAM)!=0;codec.releaseOutputBuffer(index,false);last=System.currentTimeMillis();}
     }
     if(duration>0)status="Подготавливаю запись · "+Math.min(99,Math.max(0,extractor.getSampleTime())*100/duration)+"%";
     if(System.currentTimeMillis()-last>60000)throw new IOException("Декодер перестал отвечать. Попробуй экспортировать запись в WAV");
    }
    resampler.finish();
   }
   if (stereo != null) stereo.finish(target, dataOffset);
  }finally{extractor.release();if(codec!=null){try{codec.stop();}catch(Exception ignored){}codec.release();}}
 }
 private static void consume(ByteBuffer buffer,int channels,int encoding,PcmResampler resampler)throws IOException{
  if(channels<1||channels>8)throw new IOException("Неподдерживаемое число каналов");buffer.order(ByteOrder.LITTLE_ENDIAN);
  int width=encoding==AudioFormat.ENCODING_PCM_FLOAT?4:encoding==AudioFormat.ENCODING_PCM_16BIT?2:encoding==AudioFormat.ENCODING_PCM_8BIT?1:0;
  if(width==0||buffer.remaining()%(width*channels)!=0)throw new IOException("Неподдерживаемый формат звука");
  while(buffer.remaining()>=width*channels){double sum=0;for(int channel=0;channel<channels;channel++){if(width==4){float value=buffer.getFloat();if(Float.isNaN(value)||Float.isInfinite(value))value=0;sum+=Math.max(-1,Math.min(1,value))*32767;}else if(width==2)sum+=buffer.getShort();else sum+=((buffer.get()&255)-128)*256;}resampler.sample(sum/channels);}
 }
}
