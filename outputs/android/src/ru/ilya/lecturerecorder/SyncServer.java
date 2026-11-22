package ru.ilya.lecturerecorder;
import android.content.Context;
import org.json.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

final class SyncServer {
 private final ServerSocket server;private final Context context;private DatagramSocket discovery;
 private volatile long lastUse=System.nanoTime();
 private final AtomicInteger clients=new AtomicInteger();
 static volatile String status="Ожидаю Mac · Wi-Fi / Bluetooth / USB";
 private final Map<String,Long> nonces=new HashMap<>();
 private final java.util.concurrent.Semaphore updateTransfer=new java.util.concurrent.Semaphore(1);
 SyncServer(Context c)throws IOException{context=c;server=new ServerSocket();server.setReuseAddress(true);server.bind(new InetSocketAddress(8780));new Thread(()->{while(!server.isClosed())try{Socket s=server.accept();new Thread(()->{try(Socket v=s){v.setSoTimeout(30000);handle(v.getInputStream(),v.getOutputStream(),v.getInetAddress().isLoopbackAddress());}catch(Exception ignored){}}).start();}catch(IOException ignored){}},"Mac sync").start();
  discovery=new DatagramSocket(null);discovery.setReuseAddress(true);discovery.bind(new InetSocketAddress(8783));new Thread(()->discover(),"Mac discovery").start();
 }
 String secret(){return context.getSharedPreferences("settings",0).getString("sync_token","");}
 boolean hasClients(){return clients.get()>0;}
 boolean idleFor(long now,long period){return !hasClients()&&now-lastUse>=period;}
 static String hash(byte[] b)throws Exception{byte[] h=MessageDigest.getInstance("SHA-256").digest(b);return hex(h);}
 static String hex(byte[] b){StringBuilder s=new StringBuilder();for(byte v:b)s.append(String.format(Locale.US,"%02x",v&255));return s.toString();}
 static String sign(String key,String value)throws Exception{Mac m=Mac.getInstance("HmacSHA256");m.init(new SecretKeySpec(key.getBytes(StandardCharsets.UTF_8),"HmacSHA256"));return hex(m.doFinal(value.getBytes(StandardCharsets.UTF_8)));}
 private void discover(){byte[] b=new byte[1024];while(!discovery.isClosed())try{DatagramPacket p=new DatagramPacket(b,b.length);discovery.receive(p);String v=new String(p.getData(),0,p.getLength(),StandardCharsets.US_ASCII);if(!v.matches("LECTURES1 [a-f0-9]{32}"))continue;String nonce=v.substring(10);String reply="LECTURES1 "+nonce+" 8780 "+sign(secret(),"DISCOVER\n"+nonce+"\n8780");byte[] r=reply.getBytes(StandardCharsets.US_ASCII);discovery.send(new DatagramPacket(r,r.length,p.getAddress(),p.getPort()));}catch(Exception ignored){}}
 void close(){try{server.close();}catch(Exception ignored){}if(discovery!=null)discovery.close();}
 private String line(InputStream in)throws IOException{ByteArrayOutputStream b=new ByteArrayOutputStream();int v;while((v=in.read())!=-1&&v!=10){if(b.size()>8192)throw new IOException("Header too large");if(v!=13)b.write(v);}return b.toString("UTF-8");}
 private void reply(OutputStream o,int status,byte[] body)throws IOException{o.write(("HTTP/1.1 "+status+" Response\r\nContent-Length: "+body.length+"\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));o.write(body);o.flush();}
 private boolean authorize(String method,String route,Map<String,String> h,byte[] body,boolean local)throws Exception{return authorizeDigest(method,route,h,hash(body),local);}
 private synchronized boolean authorizeDigest(String method,String route,Map<String,String> h,String digest,boolean local)throws Exception{
  String key=secret();if(key.isEmpty())return false;
  if(local&&MessageDigest.isEqual(("Bearer "+key).getBytes(StandardCharsets.UTF_8),h.getOrDefault("authorization","").getBytes(StandardCharsets.UTF_8)))return true;
  String t=h.getOrDefault("x-lecture-time",""),nonce=h.getOrDefault("x-lecture-nonce",""),supplied=h.getOrDefault("x-lecture-signature","");
  if(!nonce.matches("[a-f0-9]{32}")||!t.matches("[0-9]{10,13}"))return false;
  long now=System.currentTimeMillis()/1000;if(Math.abs(now-Long.parseLong(t))>300)return false;
  nonces.entrySet().removeIf(e->now-e.getValue()>300);if(nonces.containsKey(nonce))return false;
  String signed=method+"\n"+route+"\n"+t+"\n"+nonce+"\n"+h.getOrDefault("range","")+"\n"+digest;
  if(!MessageDigest.isEqual(sign(key,signed).getBytes(StandardCharsets.US_ASCII),supplied.getBytes(StandardCharsets.US_ASCII)))return false;
  nonces.put(nonce,now);return true;
 }
 void handle(InputStream in,OutputStream out,boolean local){clients.incrementAndGet();try{
  String[] first=line(in).split(" ");if(first.length!=3)throw new IOException();Map<String,String> h=new HashMap<>();String l;int total=0;while(!(l=line(in)).isEmpty()){total+=l.length();if(total>16384)throw new IOException();int k=l.indexOf(':');if(k>0)h.put(l.substring(0,k).toLowerCase(Locale.US),l.substring(k+1).trim());}
  if(first[0].equals("POST")&&first[1].equals("/app-update")){
   int length=Integer.parseInt(h.getOrDefault("content-length","0"));String expected=h.getOrDefault("x-lecture-body-sha256","");
   if(length<=0||length>80*1024*1024||!expected.matches("[a-f0-9]{64}")){reply(out,413,"{}".getBytes());return;}
   if(!authorizeDigest(first[0],first[1],h,expected,false)){reply(out,403,"{}".getBytes());return;}
   if(CaptureService.recording||!updateTransfer.tryAcquire()){reply(out,409,"{}".getBytes());return;}
   File temp=null;
   try{
    File folder=AppUpdates.apk(context).getParentFile();folder.mkdirs();temp=File.createTempFile("incoming-",".apk",folder);
    MessageDigest sha=MessageDigest.getInstance("SHA-256");
    try(FileOutputStream file=new FileOutputStream(temp)){byte[] b=new byte[65536];int left=length,n;while(left>0){n=in.read(b,0,Math.min(left,b.length));if(n<0)throw new EOFException();file.write(b,0,n);sha.update(b,0,n);left-=n;}file.getFD().sync();}
    if(!hex(sha.digest()).equals(expected))throw new IOException("Контрольная сумма APK не совпала");
    int code=AppUpdates.receive(context,temp,expected);reply(out,200,new JSONObject().put("ok",true).put("sha256",expected).put("code",code).toString().getBytes(StandardCharsets.UTF_8));
   }catch(Exception error){reply(out,422,new JSONObject().put("error",error.getMessage()==null?"APK отклонён":error.getMessage()).toString().getBytes(StandardCharsets.UTF_8));}
   finally{if(temp!=null)temp.delete();updateTransfer.release();}return;
  }
  int size=Integer.parseInt(h.getOrDefault("content-length","0"));int limit=first[0].equals("POST")&&first[1].equals("/notes")?2*1024*1024:2048;if(size<0||size>limit)throw new IOException();byte[] body=new byte[size];new DataInputStream(in).readFully(body);
  if(!authorize(first[0],first[1],h,body,local)){reply(out,403,"{}".getBytes());return;}
  if(first[0].equals("GET")&&first[1].equals("/app-update")){reply(out,200,AppUpdates.info(context).toString().getBytes(StandardCharsets.UTF_8));return;}
  if(first[0].equals("GET")&&first[1].equals("/notes-index")){reply(out,200,LectureNotes.index(context).toString().getBytes(StandardCharsets.UTF_8));return;}
  if(first[0].equals("POST")&&first[1].equals("/notes")){String sha=LectureNotes.save(context,body);reply(out,200,new JSONObject().put("ok",true).put("sha256",sha).toString().getBytes(StandardCharsets.UTF_8));return;}
  if(first[0].equals("GET")&&first[1].equals("/list")){JSONArray items=Store.list(context);status=items.length()==0?"Все записи перенесены на Mac":"Mac найден · переношу записи";reply(out,200,items.toString().getBytes(StandardCharsets.UTF_8));return;}
  if(first[0].equals("GET")&&first[1].startsWith("/file/")){File f=Store.transferFile(context,first[1].substring(6));if(f==null){reply(out,404,"{}".getBytes());return;}long offset=0;String range=h.getOrDefault("range","");if(!range.isEmpty()){if(!range.matches("bytes=[0-9]+-"))throw new IOException();offset=Long.parseLong(range.substring(6,range.length()-1));if(offset>=f.length()){reply(out,416,"{}".getBytes());return;}}
   status="Переношу запись на Mac…";out.write(("HTTP/1.1 "+(offset>0?"206 Partial Content":"200 OK")+"\r\nContent-Length: "+(f.length()-offset)+"\r\n"+(offset>0?"Content-Range: bytes "+offset+"-"+(f.length()-1)+"/"+f.length()+"\r\n":"")+"Connection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));try(RandomAccessFile source=new RandomAccessFile(f,"r")){source.seek(offset);byte[] b=new byte[65536];int n;while((n=source.read(b))>0)out.write(b,0,n);}out.flush();return;}
  if(first[0].equals("POST")&&first[1].equals("/ack")){JSONObject j=new JSONObject(new String(body,StandardCharsets.UTF_8));Store.acknowledge(context,j.getString("name"),j.getString("sha256"));status="Запись сохранена на Mac · очередь переноса очищена";reply(out,200,"{\"ok\":true}".getBytes());return;}
  reply(out,404,"{}".getBytes());
 }catch(Exception ignored){status="Связь прервалась · запись остаётся на телефоне";}finally{lastUse=System.nanoTime();clients.decrementAndGet();}}
}
