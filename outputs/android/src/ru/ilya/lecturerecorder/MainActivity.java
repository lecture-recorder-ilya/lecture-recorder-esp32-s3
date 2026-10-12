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
import org.json.*;

public class MainActivity extends Activity {
 private LinearLayout list;
 private TextView state,syncState,duration,libraryCount,playingLabel;
 private Button start,stop,stopListening;
 private Spinner transport;
 private final Handler timer=new Handler();
 private MediaPlayer player;
 private String previous=null;
 private int selectedPage=0;
 private final ScrollView[] pages=new ScrollView[3];
 private final Button[] tabs=new Button[3];
 private final int orange=Color.rgb(255,89,59),fg=Color.rgb(245,243,241),muted=Color.rgb(167,169,178),bg=Color.rgb(16,17,19),panel=Color.rgb(25,27,31),line=Color.rgb(48,50,56);
 private int dp(int n){return Math.round(getResources().getDisplayMetrics().density*n);}
 private GradientDrawable surface(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
 private TextView text(String value,int size){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(fg);t.setPadding(0,dp(5),0,dp(5));t.setLineSpacing(dp(3),1);return t;}
 private TextView note(String value){TextView t=text(value,13);t.setTextColor(muted);return t;}
 private TextView heading(String value,int size){TextView t=text(value,size);t.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));return t;}
 private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
 private LinearLayout card(LinearLayout parent){LinearLayout c=column();c.setPadding(dp(18),dp(18),dp(18),dp(18));GradientDrawable d=surface(panel,20);d.setStroke(dp(1),line);c.setBackground(d);LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,0,0,dp(16));parent.addView(c,lp);return c;}
 private Button button(String label,Runnable action){return button(label,action,false);}
 private Button button(String label,Runnable action,boolean primary){Button b=new Button(this);b.setText(label);b.setTextSize(15);b.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));b.setAllCaps(false);b.setTextColor(primary?Color.rgb(33,19,14):fg);b.setMinHeight(dp(50));b.setMinimumHeight(dp(50));b.setPadding(dp(12),dp(12),dp(12),dp(12));GradientDrawable d=surface(primary?orange:Color.rgb(36,38,44),13);if(!primary)d.setStroke(dp(1),Color.rgb(55,57,65));b.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(primary?0x3321130e:0x22ffffff),d,null));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,dp(8),0,dp(4));b.setLayoutParams(lp);b.setOnClickListener(v->action.run());return b;}
 private LinearLayout page(FrameLayout host,int index,String title,String subtitle){ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setClipToPadding(false);scroll.setVerticalScrollBarEnabled(false);LinearLayout content=column();content.setPadding(dp(20),dp(22),dp(20),dp(24));TextView h=heading(title,30);content.addView(h);TextView hint=note(subtitle);LinearLayout.LayoutParams hp=new LinearLayout.LayoutParams(-1,-2);hp.setMargins(0,0,0,dp(24));content.addView(hint,hp);scroll.addView(content);pages[index]=scroll;host.addView(scroll,new FrameLayout.LayoutParams(-1,-1));return content;}
 private void showPage(int index){selectedPage=index;for(int i=0;i<3;i++){pages[i].setVisibility(i==index?View.VISIBLE:View.GONE);tabs[i].setSelected(i==index);tabs[i].setTextColor(i==index?orange:muted);tabs[i].setBackground(surface(i==index?Color.rgb(48,33,30):Color.TRANSPARENT,12));}}
 @Override public void onCreate(Bundle saved){
  super.onCreate(saved);if(saved!=null){pendingPhoto=saved.getString("pending_photo");selectedPage=saved.getInt("page",0);}try{CaptureService.provision(this);}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}
  getWindow().setStatusBarColor(bg);getWindow().setNavigationBarColor(bg);getWindow().getDecorView().setSystemUiVisibility(0);
  LinearLayout root=column();root.setBackgroundColor(bg);setContentView(root);
  root.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});root.requestApplyInsets();
  FrameLayout host=new FrameLayout(this);root.addView(host,new LinearLayout.LayoutParams(-1,0,1));
  LinearLayout record=page(host,0,"Новая запись","Сохрани лекцию. Вернись к главному.");
  LinearLayout hero=card(record);state=heading("Готово к записи",14);state.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);hero.addView(state);hero.addView(note("ДЛИТЕЛЬНОСТЬ ЗАПИСИ"));duration=text("00:00:00",42);duration.setTypeface(Typeface.create("monospace",Typeface.NORMAL));duration.setPadding(0,dp(12),0,dp(18));hero.addView(duration);
  hero.addView(note("Соединение с микрофоном"));transport=new Spinner(this);transport.setContentDescription("Соединение с микрофоном");ArrayAdapter<String> adapter=new ArrayAdapter<String>(this,android.R.layout.simple_spinner_item,new String[]{"Bluetooth · без Wi-Fi","Wi-Fi · точка доступа"}){
   private View style(View view){TextView t=(TextView)view;t.setTextColor(fg);t.setTextSize(14);t.setPadding(dp(12),dp(14),dp(12),dp(14));t.setBackgroundColor(Color.rgb(20,22,26));return t;}
   @Override public View getView(int pos,View old,ViewGroup parent){return style(super.getView(pos,old,parent));}
   @Override public View getDropDownView(int pos,View old,ViewGroup parent){return style(super.getDropDownView(pos,old,parent));}
  };adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);transport.setAdapter(adapter);transport.setSelection(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")?0:1);transport.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){public void onNothingSelected(AdapterView<?> parent){}public void onItemSelected(AdapterView<?> parent,View view,int pos,long id){getSharedPreferences("settings",0).edit().putString("transport",pos==0?"ble":"wifi").apply();}});hero.addView(transport,new LinearLayout.LayoutParams(-1,-2));
  start=button("Начать запись",()->begin(),true);hero.addView(start);stop=button("Завершить и сохранить",()->startForegroundService(CaptureService.command(this,"STOP")));hero.addView(stop);hero.addView(note("Экран можно заблокировать. Оставь включённую ESP рядом с телефоном."));
  LinearLayout photo=card(record);photo.addView(heading("Фото доски",18));photo.addView(note("Формула, график или слайд — сохрани снимок вместе с лекцией. Mac найдёт место в тексте после переноса."));photo.addView(button("Сфотографировать доску",()->takeBoardPhoto()));
  record.addView(note("Запись сохраняется на телефоне. При потере связи приложение пробует подключиться снова; пропущенный звук заменяется тишиной."));
  LinearLayout library=page(host,1,"На телефоне","Записи, фото и тексты твоих лекций.");
  LinearLayout sync=card(library);sync.addView(heading("Перенос на Mac",18));syncState=note(SyncServer.status);syncState.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);sync.addView(syncState);sync.addView(button("Перенести сейчас",()->transfer(),true));sync.addView(note("Перенос включается автоматически, когда Mac доступен по общей Wi-Fi сети, Bluetooth или USB. Файлы удаляются с телефона только после проверки копии на Mac."));
  LinearLayout notesCard=card(library);notesCard.addView(heading("Тексты лекций",18));notesCard.addView(note("Расшифровки приходят с Mac и остаются на телефоне после переноса аудио."));notesList=column();notesCard.addView(notesList);
  LinearLayout playback=card(library);playback.addView(heading("Прослушивание",18));playingLabel=note("Выбери запись ниже, чтобы послушать её.");playback.addView(playingLabel);stopListening=button("Отключить прослушивание",()->stopPlayback());stopListening.setEnabled(false);stopListening.setAlpha(.45f);playback.addView(stopListening);
  libraryCount=heading("Сохранённые записи",18);library.addView(libraryCount);list=column();library.addView(list);
  LinearLayout settingsPage=page(host,2,"Настройки","Подключение и работа приложения.");
  LinearLayout macCard=card(settingsPage);macCard.addView(heading("Телефон и Mac",18));pairedMac=note("Mac ещё не подключён");macCard.addView(pairedMac);pairMac=button("Подключить Mac",()->pairPhone());macCard.addView(pairMac);macCard.addView(button("Отключить Mac",()->disconnectMac()));macCard.addView(note("Для первого подключения открой на Mac «Настройки → Телефон и Mac». Устройства должны быть в одной Wi-Fi сети."));
  LinearLayout updates=card(settingsPage);updates.addView(heading("Обновления",18));updateState=note(AppUpdates.status);updates.addView(updateState);updates.addView(button("Проверить новую версию",()->AppUpdates.check(this,true)));installUpdate=button("Установить обновление",()->AppUpdates.install(this),true);installUpdate.setVisibility(View.GONE);updates.addView(installUpdate);
  LinearLayout connection=card(settingsPage);connection.addView(heading("Микрофон ESP",18));connection.addView(note("Способ соединения выбирается на экране записи. Для Wi-Fi телефон и ESP должны быть в одной сети: можно включить точку доступа телефона."));connection.addView(button("Адрес ESP для Wi-Fi",()->espAddress()));
  LinearLayout storage=card(settingsPage);storage.addView(heading("Где лежат записи",18));storage.addView(note("До переноса — на телефоне, после подтверждённого переноса — на Mac. Расшифровка, конспект и разбор фото выполняются на Mac."));storage.addView(note("Во время переноса текущая запись продолжается. Чтобы отключить ESP, сначала заверши запись и дождись сохранения."));
  LinearLayout nav=new LinearLayout(this);nav.setPadding(dp(12),dp(10),dp(12),dp(10));GradientDrawable nd=surface(Color.rgb(21,22,26),0);nd.setStroke(dp(1),line);nav.setBackground(nd);String[] labels={"Запись","Файлы","Настройки"};for(int i=0;i<3;i++){final int index=i;Button tab=button(labels[i],()->showPage(index));tab.setTextSize(13);tab.setPadding(dp(4),dp(12),dp(4),dp(12));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);lp.setMargins(dp(3),0,dp(3),0);nav.addView(tab,lp);tabs[i]=tab;}root.addView(nav,new LinearLayout.LayoutParams(-1,-2));showPage(Math.max(0,Math.min(2,selectedPage)));
  if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},2);
 }
 private LinearLayout notesList;private String notesSignature=null,noteStamp="";private File openedNote;private TextView openedText,updateState;private ScrollView noteScroll;private Button installUpdate;
 private String pendingPhoto;
 private TextView pairedMac;private Button pairMac;private MacPairing pairing;
 private boolean transferring=false;
 private void transfer(){if(getSharedPreferences("settings",0).getString("sync_token","").isEmpty()){pairPhone();return;}transferring=true;if(Build.VERSION.SDK_INT>=31){String[] perms={"android.permission.BLUETOOTH_CONNECT","android.permission.BLUETOOTH_ADVERTISE"};for(String p:perms)if(checkSelfPermission(p)!=0){requestPermissions(perms,5);return;}}startForegroundService(CaptureService.command(this,"SYNC"));SyncServer.status="Ищу Mac · Wi-Fi / Bluetooth / USB";Toast.makeText(this,"Mac должен быть включён. Перенос начнётся автоматически.",1).show();}
 private void pairPhone(){if(CaptureService.recording){Toast.makeText(this,"Заверши запись перед сменой Mac",1).show();return;}if(pairing!=null)pairing.cancel();pairing=new MacPairing(this,()->{startForegroundService(CaptureService.command(this,"SYNC"));SyncServer.status="Mac подключён · ожидаю перенос";Toast.makeText(this,"Mac подключён. Записи и тексты будут переноситься автоматически.",1).show();});pairing.open();}
 private void disconnectMac(){if(CaptureService.recording){Toast.makeText(this,"Заверши запись перед отключением Mac",1).show();return;}new AlertDialog.Builder(this).setTitle("Отключить Mac?").setMessage("Записи и тексты останутся на телефоне. Для переноса потребуется новое сопряжение.").setPositiveButton("Отключить",(d,w)->{if(pairing!=null)pairing.cancel();stopService(new Intent(this,CaptureService.class));getSharedPreferences("settings",0).edit().remove("sync_token").remove("paired_mac").remove("paired_mac_address").commit();SyncServer.status="Подключи Mac для переноса записей";}).setNegativeButton("Отмена",null).show();}
 private void begin(){
  if(getSharedPreferences("settings",0).getString("sync_token","").isEmpty()){pairPhone();return;}
  if(getSharedPreferences("settings",0).getString("token","").isEmpty()){Toast.makeText(this,"Mac уже подключён. Для записи сначала подключи ESP к Mac и настрой микрофон",1).show();return;}
  if(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")){
   String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
   for(String p:permissions)if(checkSelfPermission(p)!=0){requestPermissions(permissions,3);return;}
   BluetoothAdapter a=getSystemService(BluetoothManager.class).getAdapter();if(a==null){Toast.makeText(this,"На телефоне нет Bluetooth",1).show();return;}if(!a.isEnabled()){startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),4);return;}
  }
  startForegroundService(CaptureService.command(this,"START"));
 }
 @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grant){super.onRequestPermissionsResult(code,permissions,grant);if(code==5&&grant.length>0){for(int g:grant)if(g!=0){startForegroundService(CaptureService.command(this,"SYNC"));return;}transfer();}if(code==3&&grant.length>0){for(int g:grant)if(g!=0)return;begin();}}
 @Override protected void onActivityResult(int code,int result,Intent data){super.onActivityResult(code,result,data);if(code==4&&result==RESULT_OK)begin();if(code==6&&result==RESULT_OK){final String id=pendingPhoto;pendingPhoto=null;new Thread(()->{try{BoardPhotos.markReady(this,id);BoardPhotos.finish(this,id);runOnUiThread(()->{Toast.makeText(this,"Фото сохранено · будет перенесено и разобрано на Mac",1).show();transfer();});}catch(Exception e){runOnUiThread(()->Toast.makeText(this,e.getMessage(),1).show());}},"Save board photo").start();}else if(code==6){BoardPhotos.cancel(this,pendingPhoto);pendingPhoto=null;}}
 @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("pending_photo",pendingPhoto);out.putInt("page",selectedPage);}
 private void takeBoardPhoto(){try{pendingPhoto=BoardPhotos.prepare(this);android.net.Uri uri=android.net.Uri.parse("content://ru.ilya.lecturerecorder.photos/"+pendingPhoto+".jpg");Intent camera=new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);camera.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,uri);camera.setClipData(ClipData.newRawUri("Фото доски",uri));camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(camera,6);}catch(Exception e){Toast.makeText(this,"Не удалось открыть камеру: "+e.getMessage(),1).show();}}
 private void espAddress(){EditText ip=new EditText(this);ip.setTextColor(fg);ip.setTextSize(16);ip.setSingleLine(true);ip.setPadding(dp(24),dp(16),dp(24),dp(16));ip.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);ip.setText(getSharedPreferences("settings",0).getString("ip",""));ip.setHint("Адрес ESP");new AlertDialog.Builder(this).setTitle("Адрес ESP").setView(ip).setMessage("ESP может подключаться к точке доступа телефона. Адрес также определяется автоматически по локальной сети.").setPositiveButton("Сохранить",(d,w)->getSharedPreferences("settings",0).edit().putString("ip",ip.getText().toString().trim()).apply()).setNegativeButton("Отмена",null).show();}
 private String recordingTitle(File file){String name=file.getName().replace("lecture-","").replace(".wav","");try{java.text.SimpleDateFormat parser=new java.text.SimpleDateFormat("yyyy-MM-dd-HH-mm-ss",Locale.US);parser.setLenient(false);Date date=parser.parse(name.substring(0,19));return new java.text.SimpleDateFormat("d MMMM · HH:mm",new Locale("ru")).format(date);}catch(Exception e){return name;}}
 private void refresh(){
  boolean active=CaptureService.recording;String message=CaptureService.status;
  String mac=getSharedPreferences("settings",0).getString("paired_mac","");boolean hasMac=!getSharedPreferences("settings",0).getString("sync_token","").isEmpty();pairedMac.setText(hasMac?(mac.isEmpty()?"Mac настроен":"Подключён к «"+mac+"»"):"Mac ещё не подключён");pairMac.setText(hasMac?"Подключить другой Mac":"Подключить Mac");pairMac.setEnabled(!active);pairMac.setAlpha(active?.45f:1f);
  state.setText(message.startsWith("Записываю ·")?"● Идёт запись":message);state.setTextColor(active?orange:fg);
  long seconds=active?CaptureService.samples/16000:0;duration.setText(String.format(Locale.US,"%02d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60));
  syncState.setText(SyncServer.status);start.setEnabled(!active);stop.setEnabled(active);transport.setEnabled(!active);start.setAlpha(active?.45f:1f);stop.setAlpha(active?1f:.45f);
  File[] files=Store.root(this).listFiles(f->f.getName().endsWith(".wav"));if(files==null)files=new File[0];Arrays.sort(files,Comparator.comparing(File::getName).reversed());
  File[] images=Store.root(this).listFiles(f->f.getName().startsWith("board-")&&f.getName().endsWith(".jpg"));StringBuilder signature=new StringBuilder();if(images!=null)for(File f:images)signature.append(f.getName()).append(f.length());for(File f:files)signature.append(f.getName()).append(f.length());
  if(!signature.toString().equals(previous)){previous=signature.toString();list.removeAllViews();libraryCount.setText("Сохранённые записи"+(files.length>0?" · "+files.length:""));
   if(images!=null&&images.length>0){LinearLayout photos=card(list);photos.addView(heading("Фото доски · "+images.length,16));photos.addView(note("Сохранены на телефоне и ожидают переноса."));}
   if(files.length==0){LinearLayout empty=card(list);empty.addView(heading("Пока нет записей",16));empty.addView(note("На телефоне нет готовых записей. Новая появится здесь после завершения; перенесённые ищи в библиотеке на Mac."));}
   for(File file:files){LinearLayout row=card(list);row.addView(heading(recordingTitle(file),17));long sec=Math.max(0,file.length()-44)/32000;row.addView(note(String.format(new Locale("ru"),"%d:%02d · %.1f МБ · ожидает переноса",sec/60,sec%60,file.length()/1000000.0)));row.addView(button("Послушать запись",()->play(file)));}
  }
  refreshNotes();AppUpdates.check(this,false);updateState.setText(AppUpdates.status);installUpdate.setVisibility(AppUpdates.ready(this)?View.VISIBLE:View.GONE);installUpdate.setEnabled(!active);
  timer.postDelayed(()->refresh(),1000);
 }
 private void refreshNotes(){try{File[] files=LectureNotes.files(this);StringBuilder stamp=new StringBuilder();for(File f:files)stamp.append(f.getName()).append(f.lastModified()).append(f.length());if(!stamp.toString().equals(notesSignature)){notesSignature=stamp.toString();notesList.removeAllViews();if(files.length==0)notesList.addView(text("Тексты появятся после подключения к Mac",15));for(File f:files){JSONObject value=new JSONObject(Store.read(f));notesList.addView(button(LectureNotes.title(value),()->openNote(f)));}}if(openedNote!=null&&openedText!=null){String revision=openedNote.lastModified()+":"+openedNote.length();if(!revision.equals(noteStamp)){int y=noteScroll.getScrollY();openedText.setText(LectureNotes.text(new JSONObject(Store.read(openedNote))));noteStamp=revision;ScrollView scroll=noteScroll;scroll.post(()->scroll.scrollTo(0,y));}}}catch(Exception e){CaptureService.status="Текст: "+e.getMessage();}}
 private void openNote(File file){try{openedNote=file;openedText=text(LectureNotes.text(new JSONObject(Store.read(file))),17);openedText.setTextIsSelectable(true);noteScroll=new ScrollView(this);noteScroll.setPadding(dp(16),0,dp(16),0);noteScroll.addView(openedText);noteStamp=file.lastModified()+":"+file.length();AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Текст лекции").setView(noteScroll).setPositiveButton("Закрыть",null).create();dialog.setOnDismissListener(d->{openedNote=null;openedText=null;noteScroll=null;});dialog.show();}catch(Exception e){Toast.makeText(this,e.getMessage(),1).show();}}
 private void stopPlayback(){if(playingLabel!=null)playingLabel.setText("Выбери запись ниже, чтобы послушать её.");if(player!=null){try{player.stop();}catch(Exception ignored){}player.release();player=null;}if(stopListening!=null){stopListening.setEnabled(false);stopListening.setAlpha(.45f);}}
 private void play(File f){try{stopPlayback();player=new MediaPlayer();player.setDataSource(f.getPath());player.setOnCompletionListener(p->stopPlayback());player.prepare();player.start();playingLabel.setText("Сейчас играет · "+recordingTitle(f));stopListening.setEnabled(true);stopListening.setAlpha(1f);}catch(Exception e){stopPlayback();Toast.makeText(this,"Не удалось воспроизвести",1).show();}}
 @Override public void onResume(){super.onResume();timer.removeCallbacksAndMessages(null);if(!getSharedPreferences("settings",0).getString("sync_token","").isEmpty())startForegroundService(CaptureService.command(this,"SYNC"));refresh();}
 @Override public void onPause(){timer.removeCallbacksAndMessages(null);super.onPause();}
 @Override public void onDestroy(){if(pairing!=null)pairing.cancel();stopPlayback();super.onDestroy();}
}
