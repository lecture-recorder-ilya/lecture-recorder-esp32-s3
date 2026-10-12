package ru.ilya.lecturerecorder;
import android.app.*;
import android.bluetooth.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.MediaPlayer;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.util.*;

public class MainActivity extends Activity {
 private LinearLayout list;private TextView state,syncState;private Button start,stop,stopListening;private Handler timer=new Handler();private MediaPlayer player;private String previous="";private final int orange=Color.rgb(255,89,59),fg=Color.rgb(238,238,238);
 private int dp(int n){return (int)(getResources().getDisplayMetrics().density*n);}
 private TextView text(String s,int size){TextView t=new TextView(this);t.setText(s);t.setTextSize(size);t.setTextColor(fg);t.setPadding(0,dp(9),0,dp(9));return t;}
 private Button button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setTextColor(Color.BLACK);b.setAllCaps(false);GradientDrawable d=new GradientDrawable();d.setColor(orange);d.setCornerRadius(dp(14));b.setBackground(d);LinearLayout.LayoutParams p=new LinearLayout.LayoutParams(-1,dp(56));p.setMargins(0,dp(8),0,dp(8));b.setLayoutParams(p);b.setOnClickListener(v->action.run());return b;}
 @Override public void onCreate(Bundle b){super.onCreate(b);try{CaptureService.provision(this);}catch(Exception e){Toast.makeText(this,e.getMessage(),1).show();}getWindow().setStatusBarColor(Color.rgb(18,18,18));getWindow().setNavigationBarColor(Color.rgb(18,18,18));
  ScrollView scroll=new ScrollView(this);scroll.setBackgroundColor(Color.rgb(18,18,18));LinearLayout content=new LinearLayout(this);content.setOrientation(1);content.setPadding(dp(22),dp(36),dp(22),dp(30));scroll.addView(content);setContentView(scroll);
  TextView title=text("Запись лекций",30);title.setTypeface(null,Typeface.BOLD);content.addView(title);content.addView(text("ESP → телефон → Mac",15));state=text("Готово к записи",20);content.addView(state);
  Spinner transport=new Spinner(this);transport.setAdapter(new ArrayAdapter<String>(this,android.R.layout.simple_spinner_dropdown_item,new String[]{"Bluetooth · без Wi-Fi","Wi-Fi · точка доступа"}));transport.setSelection(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")?0:1);transport.setOnItemSelectedListener(new android.widget.AdapterView.OnItemSelectedListener(){public void onNothingSelected(android.widget.AdapterView<?> p){}public void onItemSelected(android.widget.AdapterView<?> p,android.view.View v,int pos,long id){getSharedPreferences("settings",0).edit().putString("transport",pos==0?"ble":"wifi").apply();}});content.addView(transport);
  start=button("Начать запись",()->begin());content.addView(start);
  stop=button("Остановить и сохранить",()->startForegroundService(CaptureService.command(this,"STOP")));content.addView(stop);
  content.addView(text("Во время записи можно заблокировать экран. ESP должна быть включена и находиться рядом с телефоном.",15));
  content.addView(button("Настройки подключения",()->settings()));content.addView(text("Записи на телефоне",23));stopListening=button("Выключить прослушивание",()->stopPlayback());stopListening.setEnabled(false);stopListening.setAlpha(.4f);content.addView(stopListening);content.addView(button("Перенести на Mac",()->transfer()));syncState=text(SyncServer.status,15);content.addView(syncState);content.addView(text("Готовые записи переносятся автоматически, когда Mac рядом: по общей Wi-Fi сети, Bluetooth или USB. После проверки копии на Mac телефон очищается. Текущая запись продолжается.",15));list=new LinearLayout(this);list.setOrientation(1);content.addView(list);
  if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},2);
 }
 private boolean transferring=false;
 private void transfer(){transferring=true;if(Build.VERSION.SDK_INT>=31){String[] perms={"android.permission.BLUETOOTH_CONNECT","android.permission.BLUETOOTH_ADVERTISE"};for(String p:perms)if(checkSelfPermission(p)!=0){requestPermissions(perms,5);return;}}startForegroundService(CaptureService.command(this,"SYNC"));SyncServer.status="Ищу Mac · Wi-Fi / Bluetooth / USB";Toast.makeText(this,"Mac должен быть включён. Перенос начнётся автоматически.",1).show();}
 private void begin(){
  if(getSharedPreferences("settings",0).getString("token","").isEmpty()){Toast.makeText(this,"Сначала настрой подключение ESP на Mac",1).show();return;}
  if(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")){
   String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
   for(String p:permissions)if(checkSelfPermission(p)!=0){requestPermissions(permissions,3);return;}
   BluetoothAdapter a=getSystemService(BluetoothManager.class).getAdapter();if(a==null){Toast.makeText(this,"На телефоне нет Bluetooth",1).show();return;}if(!a.isEnabled()){startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),4);return;}
  }
  startForegroundService(CaptureService.command(this,"START"));
 }
 @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grant){super.onRequestPermissionsResult(code,permissions,grant);if(code==5&&grant.length>0){for(int g:grant)if(g!=0){startForegroundService(CaptureService.command(this,"SYNC"));return;}transfer();}if(code==3&&grant.length>0){for(int g:grant)if(g!=0)return;begin();}}
 @Override protected void onActivityResult(int code,int result,Intent data){super.onActivityResult(code,result,data);if(code==4&&result==RESULT_OK)begin();}
 private void settings(){EditText ip=new EditText(this);ip.setTextColor(fg);ip.setText(getSharedPreferences("settings",0).getString("ip",""));ip.setHint("Адрес ESP");new AlertDialog.Builder(this).setTitle("Адрес ESP").setView(ip).setMessage("ESP может подключаться к точке доступа телефона. Адрес также определяется автоматически по локальной сети.").setPositiveButton("Сохранить",(d,w)->getSharedPreferences("settings",0).edit().putString("ip",ip.getText().toString().trim()).apply()).setNegativeButton("Отмена",null).show();}
 private void refresh(){state.setText(CaptureService.status);if(syncState!=null)syncState.setText(SyncServer.status);start.setEnabled(!CaptureService.recording);stop.setEnabled(CaptureService.recording);start.setAlpha(CaptureService.recording?.4f:1f);stop.setAlpha(CaptureService.recording?1f:.4f);File[] fs=Store.root(this).listFiles(f->f.getName().endsWith(".wav"));if(fs==null)fs=new File[0];Arrays.sort(fs);StringBuilder signature=new StringBuilder();for(File f:fs)signature.append(f.getName()).append(f.length());if(!signature.toString().equals(previous)){previous=signature.toString();list.removeAllViews();if(fs.length==0)list.addView(text("Нет записей, ожидающих переноса",15));for(File f:fs){long seconds=Math.max(0,f.length()-44)/32000;list.addView(text(f.getName().replace("lecture-","").replace(".wav","")+String.format(Locale.US,"\n%d:%02d · %.1f МБ",seconds/60,seconds%60,f.length()/1000000.0),15));list.addView(button("Послушать",()->play(f)));}}timer.postDelayed(()->refresh(),1000);}
 private void stopPlayback(){if(player!=null){try{player.stop();}catch(Exception ignored){}player.release();player=null;}if(stopListening!=null){stopListening.setEnabled(false);stopListening.setAlpha(.4f);}}
 private void play(File f){try{stopPlayback();player=new MediaPlayer();player.setDataSource(f.getPath());player.setOnCompletionListener(p->stopPlayback());player.prepare();player.start();stopListening.setEnabled(true);stopListening.setAlpha(1f);}catch(Exception e){stopPlayback();Toast.makeText(this,"Не удалось воспроизвести",1).show();}}
 @Override public void onResume(){super.onResume();timer.removeCallbacksAndMessages(null);if(!getSharedPreferences("settings",0).getString("sync_token","").isEmpty())startForegroundService(CaptureService.command(this,"SYNC"));refresh();}
 @Override public void onPause(){timer.removeCallbacksAndMessages(null);super.onPause();}
 @Override public void onDestroy(){stopPlayback();super.onDestroy();}
}
