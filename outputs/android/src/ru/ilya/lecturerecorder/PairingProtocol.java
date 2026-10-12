package ru.ilya.lecturerecorder;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.*;
import java.util.Locale;
import javax.net.ssl.*;

final class PairingProtocol {
 static String normalize(String value){return value.toUpperCase(Locale.ROOT).replaceAll("[\\s–-]","").replace('0','O').replace('1','I');}
 static String certificateCode(byte[] certificate)throws GeneralSecurityException{
  byte[] digest=MessageDigest.getInstance("SHA-256").digest(certificate);
  String alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";StringBuilder out=new StringBuilder();int bits=0,value=0;
  for(byte b:digest){value=(value<<8)|(b&255);bits+=8;while(bits>=5){bits-=5;out.append(alphabet.charAt((value>>>bits)&31));if(out.length()==12)return out.toString();}}
  throw new GeneralSecurityException("Некорректный сертификат Mac");
 }
 static String post(String host,int port,String enteredCode,String route,String body)throws Exception{
  final String code=normalize(enteredCode);
  if(!code.matches("[A-Z2-7]{12}"))throw new IOException("Введи 12 символов кода с экрана Mac");
  if(!host.matches("[A-Za-z0-9.-]{1,253}")||port<1||port>65535)throw new IOException("Проверь адрес Mac");
  if(!route.matches("/pair/(request|status|ack|cancel)"))throw new IOException("Некорректный запрос");
  byte[] bytes=body.getBytes(StandardCharsets.UTF_8);if(bytes.length>2048)throw new IOException("Слишком большой запрос");
  X509TrustManager trust=new X509TrustManager(){
   public X509Certificate[] getAcceptedIssuers(){return new X509Certificate[0];}
   public void checkClientTrusted(X509Certificate[] chain,String type)throws CertificateException{throw new CertificateException("Client certificate not supported");}
   public void checkServerTrusted(X509Certificate[] chain,String type)throws CertificateException{
    try{if(chain==null||chain.length!=1)throw new CertificateException("Неверный сертификат Mac");chain[0].checkValidity();chain[0].verify(chain[0].getPublicKey());String actual=certificateCode(chain[0].getEncoded());if(!MessageDigest.isEqual(code.getBytes(StandardCharsets.US_ASCII),actual.getBytes(StandardCharsets.US_ASCII)))throw new CertificateException("Код Mac не совпадает");}
    catch(GeneralSecurityException e){throw new CertificateException("Код Mac не совпадает или истёк",e);}
   }
  };
  SSLContext tls=SSLContext.getInstance("TLS");tls.init(null,new TrustManager[]{trust},new SecureRandom());
  HttpsURLConnection connection=(HttpsURLConnection)new URL("https",host,port,route).openConnection(Proxy.NO_PROXY);
  connection.setSSLSocketFactory(tls.getSocketFactory());connection.setHostnameVerifier((name,session)->true);
  connection.setConnectTimeout(8000);connection.setReadTimeout(8000);connection.setInstanceFollowRedirects(false);connection.setUseCaches(false);
  connection.setRequestMethod("POST");connection.setRequestProperty("Content-Type","application/json; charset=utf-8");connection.setDoOutput(true);connection.setFixedLengthStreamingMode(bytes.length);
  try{
   try(OutputStream out=connection.getOutputStream()){out.write(bytes);}
   int status=connection.getResponseCode();InputStream response=status==200?connection.getInputStream():connection.getErrorStream();
   if(response==null)throw new IOException("Mac не отвечает. Открой сопряжение заново.");
   if(connection.getContentLength()>16384)throw new IOException("Некорректный ответ Mac");
   ByteArrayOutputStream out=new ByteArrayOutputStream();
   try(InputStream in=response){byte[] block=new byte[2048];int n;while((n=in.read(block))!=-1){if(out.size()+n>16384)throw new IOException("Некорректный ответ Mac");out.write(block,0,n);}}
   String result=new String(out.toByteArray(),StandardCharsets.UTF_8);
   if(status!=200)throw new PairingResponseException(status,result);
   return result;
  }finally{connection.disconnect();}
 }
 static final class PairingResponseException extends IOException {
  final int status;final String body;
  PairingResponseException(int status,String body){super("Mac отклонил запрос");this.status=status;this.body=body;}
 }
}
