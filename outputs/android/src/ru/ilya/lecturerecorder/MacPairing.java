package ru.ilya.lecturerecorder;

import android.app.*;
import android.content.*;
import android.net.wifi.WifiManager;
import android.os.*;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.KeyEvent;
import android.view.View;
import android.widget.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import javax.net.ssl.SSLException;
import org.json.*;

final class MacPairing {
 private final Activity activity;private final Runnable connected;private final Handler ui=new Handler(Looper.getMainLooper());
 private final String nonce=UUID.randomUUID().toString().replace("-","");private final AtomicBoolean cancelled=new AtomicBoolean();private volatile boolean working=false;private volatile DatagramSocket discovery;
 private volatile String requestId="",host="",code="";private AlertDialog dialog;private TextView message;private EditText address,pin;private Button connect;
 private LinearLayout computers;
 private ChoiceDropdown computerChoice;
 private final List<ChoiceDropdown.Option> discovered=new ArrayList<>();
 MacPairing(Activity activity,Runnable connected){this.activity=activity;this.connected=connected;}
 private int dp(int value){return (int)(activity.getResources().getDisplayMetrics().density*value);}
 private TextView text(String value){TextView view=new TextView(activity);view.setText(value);view.setTextColor(StudioStyle.TEXT);view.setTextSize(16);view.setPadding(0,dp(8),0,dp(8));return view;}
 private void show(Runnable action){ui.post(()->{if(!cancelled.get()&&!activity.isFinishing()&&!activity.isDestroyed())action.run();});}
 void open(){
  LinearLayout content=new LinearLayout(activity);content.setOrientation(1);content.setPadding(dp(20),dp(8),dp(20),dp(8));
  content.addView(text("На Mac открой «Настройки → Телефон и Mac → Подключить телефон». Оба устройства должны быть в одной Wi-Fi сети."));
  message=text("Ищу Mac в сети…");content.addView(message);
  computers=new LinearLayout(activity);
  computers.setOrientation(LinearLayout.VERTICAL);
  computers.setVisibility(View.GONE);
  computerChoice=new ChoiceDropdown(activity,"Выбрать Mac","Нет доступных компьютеров",()->discovered,
   option->{
    address.setText(option.value);
    message.setText("Выбран «"+option.title+"». Введи код с его экрана.");
    pin.requestFocus();
   });
  computers.addView(computerChoice.button,new LinearLayout.LayoutParams(-1,-2));
  LinearLayout.LayoutParams computerList=new LinearLayout.LayoutParams(-1,-2);
  computerList.topMargin=dp(6);
  computers.addView(computerChoice.list,computerList);
  content.addView(computers);
  address=new EditText(activity);address.setSingleLine(true);address.setTextColor(StudioStyle.TEXT);address.setHintTextColor(StudioStyle.MUTED);address.setHint("Адрес Mac, если он не найден");address.setContentDescription("Адрес Mac");address.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);content.addView(address);
  address.addTextChangedListener(new TextWatcher(){
   @Override public void beforeTextChanged(CharSequence value,int start,int count,int after){}
   @Override public void onTextChanged(CharSequence value,int start,int previous,int count){
    showSelectedComputer(value.toString().trim());
   }
   @Override public void afterTextChanged(Editable value){}
  });
  pin=new EditText(activity);pin.setSingleLine(true);pin.setTextColor(StudioStyle.TEXT);pin.setHintTextColor(StudioStyle.MUTED);pin.setHint("Код Mac · 12 символов");pin.setContentDescription("Код Mac");pin.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS|InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);content.addView(pin);
  ScrollView scroll=new ScrollView(activity);scroll.addView(content);
  dialog=new AlertDialog.Builder(activity).setTitle("Подключить Mac").setView(scroll).setPositiveButton("Продолжить",null).setNegativeButton("Отмена",(d,w)->cancel()).create();
  dialog.setOnKeyListener((active,key,event)->key==KeyEvent.KEYCODE_BACK
   &&event.getAction()==KeyEvent.ACTION_UP&&computerChoice.close());
  dialog.setOnCancelListener(d->cancel());dialog.setOnDismissListener(d->{if(!cancelled.get())cancel();});dialog.show();connect=dialog.getButton(AlertDialog.BUTTON_POSITIVE);connect.setOnClickListener(v->begin());
  new Thread(()->discover(),"Find Mac").start();
 }
 private void discover(){
  WifiManager.MulticastLock multicast=null;Set<String> seen=new HashSet<>();
  try{
   WifiManager wifi=(WifiManager)activity.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
   if(wifi!=null){multicast=wifi.createMulticastLock("lectures:pairing");multicast.setReferenceCounted(false);multicast.acquire();}
   String nonce=UUID.randomUUID().toString().replace("-","");byte[] query=("LECTUREPAIR1 "+nonce).getBytes(StandardCharsets.US_ASCII);
   Set<InetAddress> destinations=new HashSet<>();destinations.add(InetAddress.getByName("255.255.255.255"));
   Enumeration<NetworkInterface> networks=NetworkInterface.getNetworkInterfaces();
   while(networks!=null&&networks.hasMoreElements())for(InterfaceAddress current:networks.nextElement().getInterfaceAddresses())if(current.getBroadcast()!=null)destinations.add(current.getBroadcast());
   try(DatagramSocket udp=new DatagramSocket()){
    discovery=udp;udp.setBroadcast(true);udp.setSoTimeout(350);byte[] buffer=new byte[1024];long until=SystemClock.elapsedRealtime()+6000,nextSend=0;
    while(!cancelled.get()&&!working&&SystemClock.elapsedRealtime()<until){
     if(SystemClock.elapsedRealtime()>=nextSend){for(InetAddress ip:destinations)try{udp.send(new DatagramPacket(query,query.length,ip,8785));}catch(IOException ignored){}nextSend=SystemClock.elapsedRealtime()+1500;}
     try{DatagramPacket packet=new DatagramPacket(buffer,buffer.length);udp.receive(packet);JSONObject reply=new JSONObject(new String(packet.getData(),0,packet.getLength(),StandardCharsets.UTF_8));
      if(!reply.optString("protocol").equals("LECTUREPAIR1")||!reply.optString("nonce").equals(nonce)||reply.optInt("port")!=8784||!(packet.getAddress() instanceof Inet4Address))continue;
      String ip=packet.getAddress().getHostAddress(),name=reply.optString("name","Mac");if(name.length()>80||!seen.add(ip))continue;
      show(()->{
       if(working)return;
       discovered.add(new ChoiceDropdown.Option(ip,name,ip));
       computers.setVisibility(View.VISIBLE);
       if(address.getText().toString().isEmpty())address.setText(ip);
       else showSelectedComputer(address.getText().toString().trim());
       computerChoice.refreshOptions();
       message.setText("Mac найден. Выбери компьютер и введи его код.");
      });
     }catch(SocketTimeoutException ignored){}catch(JSONException ignored){}
    }
   }
   if(seen.isEmpty())show(()->{if(!working)message.setText("Mac пока не найден. Открой сопряжение на Mac, проверь Wi-Fi или введи адрес с экрана Mac.");});
  }catch(Exception e){if(!cancelled.get()&&!working)show(()->message.setText("Не удалось найти Mac. Можно ввести его адрес вручную. Проверь доступ приложения к локальной сети."));}
  finally{discovery=null;if(multicast!=null&&multicast.isHeld())multicast.release();}
 }
 private void showSelectedComputer(String ip){
  for(ChoiceDropdown.Option computer:discovered){
   if(computer.value.equals(ip)){computerChoice.setSelected(computer);return;}
  }
  computerChoice.setSelected(null);
 }
 private JSONObject post(String route,JSONObject value)throws Exception{
  try{return new JSONObject(PairingProtocol.post(host,8784,code,route,value.toString()));}
  catch(PairingProtocol.PairingResponseException e){String error="Mac отклонил подключение";try{error=new JSONObject(e.body).optString("error",error);}catch(JSONException ignored){}throw new RemoteError(error);}
 }
 private void begin(){
  if(working)return;host=address.getText().toString().trim();code=PairingProtocol.normalize(pin.getText().toString());
  if(!code.matches("[A-Z2-7]{12}")){message.setText("Введи все 12 символов кода с экрана Mac.");return;}
  if(!host.matches("[A-Za-z0-9.-]{1,253}")){message.setText("Выбери найденный Mac или введи его адрес.");return;}
  working=true;computerChoice.close();computers.setVisibility(View.GONE);connect.setEnabled(false);address.setEnabled(false);pin.setEnabled(false);message.setText("Подключаюсь к Mac…");if(discovery!=null)discovery.close();
  new Thread(()->pair(),"Pair with Mac").start();
 }
 private void pair(){
  try{
   SharedPreferences prefs=activity.getSharedPreferences("settings",0);String device=prefs.getString("device_id","");
   if(!device.matches("[a-f0-9]{32}")){device=UUID.randomUUID().toString().replace("-","");if(!prefs.edit().putString("device_id",device).commit())throw new IOException("Не удалось сохранить настройки телефона");}
   JSONObject request=new JSONObject().put("name",Build.MODEL).put("device_id",device).put("nonce",nonce);
   JSONObject reply=post("/pair/request",request);requestId=reply.getString("request_id");String verification=reply.getString("verification");
   show(()->message.setText("Сравни цифры с Mac:\n\n"+verification+"\n\nЕсли они совпадают, нажми «Подключить» на Mac."));
   long deadline=SystemClock.elapsedRealtime()+300000;int failures=0;
   while(!cancelled.get()&&SystemClock.elapsedRealtime()<deadline){
    JSONObject result;
    try{result=post("/pair/status",new JSONObject().put("request_id",requestId));failures=0;}
    catch(RemoteError|SSLException e){throw e;}
    catch(IOException e){if(++failures>=8)throw e;show(()->message.setText("Связь с Mac прервалась. Повторяю…\n\nКод подтверждения: "+verification));Thread.sleep(1500);continue;}
    if(cancelled.get())return;
    if(result.optString("status").equals("approved")||result.optString("status").equals("complete")){
     String token=result.getString("sync_token"),mac=result.getString("mac_name");if(!token.matches("[A-Za-z0-9_-]{43}"))throw new IOException("Mac вернул некорректное подключение");
     SharedPreferences.Editor edit=prefs.edit().putString("sync_token",token).putString("paired_mac",mac).putString("paired_mac_address",host);
     JSONObject esp=result.optJSONObject("esp");if(esp!=null)for(String key:new String[]{"ip","hostname","token","ble_address"})if(esp.has(key))edit.putString(key,esp.getString(key));
     if(!edit.commit())throw new IOException("Не удалось сохранить подключение. Повтори сопряжение.");
     try{post("/pair/ack",new JSONObject().put("request_id",requestId));}catch(Exception ignored){}
     show(()->{connected.run();cancelled.set(true);dialog.dismiss();});return;
    }
    Thread.sleep(1000);
   }
   if(!cancelled.get())throw new IOException("Код истёк. Открой сопряжение на Mac заново.");
  }catch(Exception e){
   String detail=e instanceof SSLException?"Код Mac не совпадает или истёк. Проверь код и дату на телефоне.":e instanceof RemoteError?e.getMessage():"Не удалось подключиться. Проверь общую Wi-Fi сеть и повтори.";
   show(()->{message.setText(detail);working=false;computers.setVisibility(discovered.isEmpty()?View.GONE:View.VISIBLE);connect.setEnabled(true);address.setEnabled(true);pin.setEnabled(true);});
  }
 }
 void cancel(){
  if(cancelled.getAndSet(true))return;if(computerChoice!=null)computerChoice.close();if(discovery!=null)discovery.close();String id=requestId;
  if(!id.isEmpty())new Thread(()->{try{post("/pair/cancel",new JSONObject().put("request_id",id));}catch(Exception ignored){}},"Cancel Mac pairing").start();
  if(dialog!=null&&dialog.isShowing())dialog.dismiss();
 }
 private static final class RemoteError extends IOException {RemoteError(String message){super(message);}}
}
