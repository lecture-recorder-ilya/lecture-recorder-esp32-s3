from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
jdk=Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else Path(subprocess.check_output(['/usr/libexec/java_home','-v','17'],text=True).strip())
source='''package ru.ilya.lecturerecorder;
import java.io.*;
public class ResamplerTest {
 static byte[] sine(int rate,int hz)throws Exception{ByteArrayOutputStream bytes=new ByteArrayOutputStream();PcmResampler r=new PcmResampler(bytes,rate);for(int i=0;i<rate;i++)r.sample(12000*Math.sin(2*Math.PI*hz*i/rate));r.finish();if(r.frames()!=16000)throw new AssertionError("Число отсчётов: "+r.frames());return bytes.toByteArray();}
 static double rms(byte[] bytes){double energy=0;int n=0;for(int i=200;i<bytes.length;i+=2){short s=(short)((bytes[i]&255)|((bytes[i+1]&255)<<8));energy+=(double)s*s;n++;}return Math.sqrt(energy/n);}
 public static void main(String[] args)throws Exception{
  for(int rate:new int[]{8000,16000,22050,44100,48000,96000})sine(rate,1000);
  double pass=rms(sine(48000,1000)),stop=rms(sine(48000,12000));
  if(pass<8000||pass>9000)throw new AssertionError("Амплитуда полезного сигнала: "+pass);
  if(stop>pass*.03)throw new AssertionError("Алиасинг: "+stop/pass);
  ByteArrayOutputStream b=new ByteArrayOutputStream();PcmResampler r=new PcmResampler(b,16000);for(int i=0;i<1000;i++)r.sample(50000);r.finish();if(b.size()!=2000)throw new AssertionError("Длина");for(int i=0;i<b.size();i+=2)if((b.toByteArray()[i]&255)!=255||(b.toByteArray()[i+1]&255)!=127)throw new AssertionError("Ограничение PCM16");
  System.out.println("Проверены 6 частот, длительность, амплитуда, подавление алиасинга и ограничение PCM16. ratio="+stop/pass);
 }
}'''
with tempfile.TemporaryDirectory() as temp:
 p=Path(temp)/'ResamplerTest.java';p.write_text(source)
 subprocess.run([str(jdk/'bin/javac'),'-encoding','UTF-8','-d',temp,str(root/'outputs/android/src/ru/ilya/lecturerecorder/PcmResampler.java'),str(p)],check=True)
 subprocess.run([str(jdk/'bin/java'),'-cp',temp,'ru.ilya.lecturerecorder.ResamplerTest'],check=True)
