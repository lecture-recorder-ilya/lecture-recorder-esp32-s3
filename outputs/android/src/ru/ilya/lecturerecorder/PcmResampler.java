package ru.ilya.lecturerecorder;

import java.io.IOException;
import java.io.OutputStream;

final class PcmResampler {
 private final OutputStream output;
 private final double step;
 private double next=0,previous=0;
 private long frames=0,written=0;
 private double[] coefficients,history;private int historyPosition=0;
 PcmResampler(OutputStream output,int sampleRate){if(sampleRate<8000||sampleRate>384000)throw new IllegalArgumentException("Неподдерживаемая частота аудио");this.output=output;step=sampleRate/16000.0;if(sampleRate>16000){int taps=Math.min(255,Math.max(31,(int)Math.ceil(step*20)))|1;coefficients=new double[taps];history=new double[taps];double cutoff=.45/step,sum=0;int middle=taps/2;for(int i=0;i<taps;i++){int n=i-middle;double sinc=n==0?2*cutoff:Math.sin(2*Math.PI*cutoff*n)/(Math.PI*n);coefficients[i]=sinc*(.54-.46*Math.cos(2*Math.PI*i/(taps-1)));sum+=coefficients[i];}for(int i=0;i<taps;i++)coefficients[i]/=sum;}}
 private void write(double value)throws IOException{int sample=(int)Math.round(Math.max(-32768,Math.min(32767,value)));output.write(sample&255);output.write((sample>>8)&255);written++;}
 void sample(double value)throws IOException{
  if(coefficients!=null){history[historyPosition]=value;double filtered=0;for(int i=0;i<coefficients.length;i++)filtered+=coefficients[i]*history[(historyPosition-i+history.length)%history.length];historyPosition=(historyPosition+1)%history.length;value=filtered;}
  if(frames==0){write(value);next=step;}
  else while(next<=frames+1e-8){double fraction=next-(frames-1);write(previous+(value-previous)*fraction);next+=step;}
  previous=value;frames++;
  if(written>16000L*8*3600)throw new IOException("Поддерживаются записи длительностью до 8 часов");
 }
 void finish()throws IOException{long expected=Math.round(frames/step);while(written<expected)write(previous);}
 void clearSignalHistory() {
  previous = 0;
  if (history != null) java.util.Arrays.fill(history, 0);
 }
 long frames(){return written;}
}
