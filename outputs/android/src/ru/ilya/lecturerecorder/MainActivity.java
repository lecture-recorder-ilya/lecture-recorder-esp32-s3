package ru.ilya.lecturerecorder;
import android.app.*;
import android.bluetooth.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.view.*;
import android.widget.*;
import java.util.*;

public class MainActivity extends Activity {
 private TextView state,duration,deviceChevron,deviceBattery;
 private LinearLayout deviceDetails,pairedDevice;
 private RecorderModelView deviceModel;
 private View addDevice;
 private Button reconnectDevice;
 private EspPairing devicePairing;
 private boolean deviceExpanded;
 private int deviceCharge=-1;
 private final List<ChoiceDropdown.Option> sources=Arrays.asList(
  new ChoiceDropdown.Option("phone","Микрофон телефона",""),
  new ChoiceDropdown.Option("ble","ESP · Bluetooth",""));
 private GradientDrawable linkDot;
 private CaptureService.Link displayedLink;
 private CaptureService.Link idleLink=CaptureService.Link.OFF;
 private Thread presenceCheck;
 private String presenceSource="",presenceError="";
 private long nextPresenceCheck;
 private boolean lastRecording;
 private boolean microphonePermissionDenied;
 private Button start,stop;
 private ChoiceDropdown transport;
 private final Handler timer=new Handler();
 private int selectedPage=0;
 private static final int AUDIO_PAGE=1;
 private final View[] pages=new View[3];
 private final Button[] tabs=new Button[3];
 private AudioTranscriptPage audioPage;
 private boolean resumed;
 private final int orange=Color.rgb(255,89,59),fg=Color.rgb(245,243,241),muted=Color.rgb(167,169,178),bg=Color.rgb(16,17,19),panel=Color.rgb(25,27,31),line=Color.rgb(43,45,51);
 private int dp(int n){return Math.round(getResources().getDisplayMetrics().density*n);}
 private GradientDrawable surface(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
 private TextView text(String value,int size){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(fg);t.setPadding(0,dp(5),0,dp(5));t.setLineSpacing(dp(3),1);return t;}
 private TextView note(String value){TextView t=text(value,13);t.setTextColor(muted);return t;}
 private TextView heading(String value,int size){TextView t=text(value,size);t.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));return t;}
 private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
 private LinearLayout card(LinearLayout parent){LinearLayout c=column();c.setPadding(dp(18),dp(18),dp(18),dp(18));GradientDrawable d=surface(panel,18);d.setStroke(dp(1),line);c.setBackground(d);LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,0,0,dp(16));parent.addView(c,lp);return c;}
 private Button button(String label,Runnable action){return button(label,action,false);}
 private Button button(String label,Runnable action,boolean primary){Button b=new Button(this);b.setText(label);b.setTextSize(15);b.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));b.setAllCaps(false);b.setTextColor(primary?Color.rgb(33,19,14):fg);b.setMinHeight(dp(50));b.setMinimumHeight(dp(50));b.setPadding(dp(12),dp(12),dp(12),dp(12));GradientDrawable d=surface(primary?orange:Color.rgb(36,38,44),12);if(!primary)d.setStroke(dp(1),line);b.setBackground(new android.graphics.drawable.RippleDrawable(android.content.res.ColorStateList.valueOf(primary?0x3321130e:0x22ffffff),d,null));LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2);lp.setMargins(0,dp(8),0,dp(4));b.setLayoutParams(lp);b.setOnClickListener(v->action.run());return b;}
 private LinearLayout page(FrameLayout host,int index,String title){ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setClipToPadding(false);scroll.setVerticalScrollBarEnabled(false);LinearLayout content=column();content.setPadding(dp(20),dp(22),dp(20),dp(24));LinearLayout titleRow=new LinearLayout(this);titleRow.setGravity(android.view.Gravity.CENTER_VERTICAL);View mark=new View(this);mark.setBackground(surface(orange,2));LinearLayout.LayoutParams mp=new LinearLayout.LayoutParams(dp(4),dp(24));mp.setMargins(0,0,dp(12),0);titleRow.addView(mark,mp);TextView h=heading(title,28);titleRow.addView(h);LinearLayout.LayoutParams titleLayout=new LinearLayout.LayoutParams(-1,-2);titleLayout.bottomMargin=dp(16);content.addView(titleRow,titleLayout);scroll.addView(content);pages[index]=scroll;host.addView(scroll,new FrameLayout.LayoutParams(-1,-1));return content;}
 private void showPage(int index){
  if(index!=0){transport.close();stopPresenceCheck();}
  selectedPage=index;
  for(int i=0;i<pages.length;i++){
   boolean active=i==index;
   pages[i].setVisibility(active?View.VISIBLE:View.GONE);
   tabs[i].setSelected(active);
   tabs[i].setTextColor(active?orange:muted);
   tabs[i].setBackground(surface(active?Color.rgb(48,33,30):Color.TRANSPARENT,12));
  }
  audioPage.setActive(resumed&&index==AUDIO_PAGE);
  if(index==0&&resumed)refreshConnection();
 }
 @Override public void onCreate(Bundle saved){
  super.onCreate(saved);if(saved!=null){pendingPhoto=saved.getString("pending_photo");selectedPage=saved.getInt("page",0);if(selectedPage==3)selectedPage=AUDIO_PAGE;deviceExpanded=saved.getBoolean("device_expanded");deviceCharge=saved.getInt("device_charge",-1);}try{CaptureService.provision(this);}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}
  getWindow().setStatusBarColor(bg);getWindow().setNavigationBarColor(bg);getWindow().getDecorView().setSystemUiVisibility(0);
  LinearLayout root=column();root.setBackgroundColor(bg);setContentView(root);
  root.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});root.requestApplyInsets();
  FrameLayout host=new FrameLayout(this);root.addView(host,new LinearLayout.LayoutParams(-1,0,1));
  LinearLayout record=page(host,0,"Новая запись");
  addConnectionPanel(record);
  if(saved!=null)deviceModel.setYaw(saved.getFloat("device_rotation",-.30f));
  LinearLayout hero=card(record);hero.addView(note("ДЛИТЕЛЬНОСТЬ ЗАПИСИ"));duration=text("00:00:00",42);duration.setTypeface(Typeface.create("monospace",Typeface.NORMAL));duration.setPadding(0,dp(12),0,dp(18));hero.addView(duration);
  hero.addView(note("Источник звука"));
  SharedPreferences sourceSettings=getSharedPreferences("settings",0);
  String source=sourceSettings.getString("transport","phone");
  ChoiceDropdown.Option selectedSource=sources.get(source.equals("ble")||source.equals("wifi")?1:0);
  if(!source.equals(selectedSource.value))sourceSettings.edit().putString("transport",selectedSource.value).apply();
  transport=new ChoiceDropdown(this,"Источник звука","Нет доступных источников",()->sources,
   option->{
    sourceSettings.edit().putString("transport",option.value).apply();
    stopPresenceCheck();
    presenceSource="";
    refreshConnection();
   });
  transport.setSelected(selectedSource);
  hero.addView(transport.button,new LinearLayout.LayoutParams(-1,-2));
  LinearLayout.LayoutParams sourceList=new LinearLayout.LayoutParams(-1,-2);
  sourceList.topMargin=dp(6);
  hero.addView(transport.list,sourceList);
  start=button("Начать запись",()->begin(),true);hero.addView(start);stop=button("Завершить и сохранить",()->startForegroundService(CaptureService.command(this,"STOP")));hero.addView(stop);
  LinearLayout photo=card(record);photo.addView(heading("Фото доски",18));photo.addView(button("Сфотографировать доску",()->takeBoardPhoto()));
  LinearLayout settingsPage=page(host,2,"Настройки");
  LinearLayout connection=card(settingsPage);
  connection.addView(heading("Микрофон ESP",18));
  firmwareButton=button("Проверить версию прошивки",this::checkFirmware);
  connection.addView(firmwareButton);
  firmwareStatus=note("");
  firmwareStatus.setVisibility(View.GONE);
  firmwareStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  connection.addView(firmwareStatus);
  LinearLayout updates=card(settingsPage);
  try { updates.addView(heading("Версия приложения · "+getPackageManager().getPackageInfo(getPackageName(),0).versionName,18)); }
  catch (android.content.pm.PackageManager.NameNotFoundException ignored) {}
  installUpdate=button("Установить обновление",()->AppUpdates.install(this),true);
  installUpdate.setVisibility(View.GONE);
  updates.addView(installUpdate);
  audioPage=new AudioTranscriptPage(this,saved==null?null:saved.getBundle("audio_page"),this::chooseAudio);
  pages[AUDIO_PAGE]=audioPage;
  host.addView(audioPage,new FrameLayout.LayoutParams(-1,-1));

  LinearLayout nav=new LinearLayout(this);
  nav.setPadding(dp(8),dp(10),dp(8),dp(10));
  GradientDrawable nd=surface(Color.rgb(21,22,26),0);
  nd.setStroke(dp(1),line);
  nav.setBackground(nd);
  String[] labels={"Запись","Аудио","Настройки"};
  for(int index=0;index<labels.length;index++){
   int pageIndex=index;
   Button tab=button(labels[index],()->showPage(pageIndex));
   tab.setTextSize(12);
   tab.setMaxLines(1);
   tab.setPadding(dp(2),dp(12),dp(2),dp(12));
   LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);
   lp.setMargins(dp(2),0,dp(2),0);
   nav.addView(tab,lp);
   tabs[index]=tab;
  }
  root.addView(nav,new LinearLayout.LayoutParams(-1,-2));
  showPage(Math.max(0,Math.min(pages.length-1,selectedPage)));
  if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},2);
 }
 private TextView firmwareStatus;private Button firmwareButton,installUpdate;
 private Thread firmwareQuery;
 private String pendingPhoto;
 private MacPairing pairing;
 private void transfer(){if(getSharedPreferences("settings",0).getString("sync_token","").isEmpty()){pairPhone();return;}if(Build.VERSION.SDK_INT>=31){String[] perms={"android.permission.BLUETOOTH_CONNECT","android.permission.BLUETOOTH_ADVERTISE"};for(String p:perms)if(checkSelfPermission(p)!=0){requestPermissions(perms,5);return;}}startForegroundService(CaptureService.command(this,"SYNC"));SyncServer.status="Ищу Mac · Wi-Fi / Bluetooth / USB";Toast.makeText(this,"Mac должен быть включён. Перенос начнётся автоматически.",1).show();}
 private void pairPhone(){if(CaptureService.recording){Toast.makeText(this,"Заверши запись перед сменой Mac",1).show();return;}if(pairing!=null)pairing.cancel();pairing=new MacPairing(this,()->{startForegroundService(CaptureService.command(this,"SYNC"));SyncServer.status="Mac подключён · ожидаю перенос";Toast.makeText(this,"Mac подключён. Записи и тексты будут переноситься автоматически.",1).show();});pairing.open();}
 private void checkFirmware(){
  if(CaptureService.recording||firmwareQuery!=null)return;
  String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
  for(String permission:permissions)if(checkSelfPermission(permission)!=0){requestPermissions(permissions,9);return;}
  firmwareStatus.setText("Проверяю версию прошивки…");
  firmwareStatus.setVisibility(View.VISIBLE);
  firmwareButton.setEnabled(false);
  Context app=getApplicationContext();
  firmwareQuery=new Thread(()->{
   String result;
   try{result=EspFirmwareVersion.bluetooth(app);}
   catch(InterruptedException error){Thread.currentThread().interrupt();return;}
   catch(java.io.IOException error){result=error.getMessage();}
   catch(Exception error){result="Не удалось проверить версию прошивки";}
   String message=result;
   runOnUiThread(()->{
    firmwareQuery=null;
    if(isDestroyed())return;
    firmwareStatus.setText(message);
    firmwareButton.setEnabled(!CaptureService.recording);
   });
  },"ESP firmware version");
  firmwareQuery.start();
 }
 private void begin(){
  if(firmwareQuery!=null)return;
  stopPresenceCheck();
  if(getSharedPreferences("settings",0).getString("transport","phone").equals("phone")){if(checkSelfPermission("android.permission.RECORD_AUDIO")!=0){requestPermissions(new String[]{"android.permission.RECORD_AUDIO"},8);return;}startForegroundService(CaptureService.command(this,"START_PHONE"));return;}
  if(getSharedPreferences("settings",0).getString("token","").isEmpty()){
   deviceExpanded=true;updateDevicePanel();openDevicePairing();return;
  }
  if(getSharedPreferences("settings",0).getString("transport","ble").equals("ble")){
   String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
   for(String p:permissions)if(checkSelfPermission(p)!=0){requestPermissions(permissions,3);return;}
   BluetoothAdapter a=getSystemService(BluetoothManager.class).getAdapter();if(a==null){Toast.makeText(this,"На телефоне нет Bluetooth",1).show();return;}if(!a.isEnabled()){startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),4);return;}
  }
  startForegroundService(CaptureService.command(this,"START"));
 }
 @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grant){super.onRequestPermissionsResult(code,permissions,grant);if(code==EspPairing.BLUETOOTH_PERMISSION){if(devicePairing!=null)devicePairing.permissionResult(grant);return;}if(code==9){for(int result:grant)if(result!=0)return;if(grant.length>0)checkFirmware();return;}if(code==8){microphonePermissionDenied=grant.length>0&&grant[0]!=0;if(grant.length>0&&grant[0]==0)begin();else refreshConnection();return;}if(code==5&&grant.length>0){for(int g:grant)if(g!=0){startForegroundService(CaptureService.command(this,"SYNC"));return;}transfer();}if(code==3&&grant.length>0){for(int g:grant)if(g!=0)return;begin();}}
 @Override protected void onActivityResult(int code,int result,Intent data){super.onActivityResult(code,result,data);if(code==7&&result==RESULT_OK&&data!=null&&data.getData()!=null){android.net.Uri uri=data.getData();try{getContentResolver().takePersistableUriPermission(uri,data.getFlags()&Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(Exception ignored){}AudioImport.start(this,uri);return;}if(code==4&&result==RESULT_OK)begin();if(code==6&&result==RESULT_OK){final String id=pendingPhoto;pendingPhoto=null;new Thread(()->{try{BoardPhotos.markReady(this,id);BoardPhotos.finish(this,id);runOnUiThread(()->{Toast.makeText(this,"Фото сохранено · будет перенесено и разобрано на Mac",1).show();transfer();});}catch(Exception e){runOnUiThread(()->Toast.makeText(this,e.getMessage(),1).show());}},"Save board photo").start();}else if(code==6){BoardPhotos.cancel(this,pendingPhoto);pendingPhoto=null;}}
 @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("pending_photo",pendingPhoto);out.putInt("page",selectedPage);out.putBundle("audio_page",audioPage.snapshot());out.putBoolean("device_expanded",deviceExpanded);out.putInt("device_charge",deviceCharge);out.putFloat("device_rotation",deviceModel.rotation());}
 private void takeBoardPhoto(){try{pendingPhoto=BoardPhotos.prepare(this);android.net.Uri uri=android.net.Uri.parse("content://"+getPackageName()+".photos/"+pendingPhoto+".jpg");Intent camera=new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);camera.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,uri);camera.setClipData(ClipData.newRawUri("Фото доски",uri));camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(camera,6);}catch(Exception e){Toast.makeText(this,"Не удалось открыть камеру: "+e.getMessage(),1).show();}}
 private void chooseAudio(){
  Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("audio/*").addCategory(Intent.CATEGORY_OPENABLE)
   .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
  startActivityForResult(pick,7);
 }
 private void addConnectionPanel(LinearLayout record){
  LinearLayout panel=card(record);
  panel.setPadding(dp(14),0,dp(14),0);
  LinearLayout row=new LinearLayout(this);
  row.setGravity(Gravity.CENTER_VERTICAL);
  row.setMinimumHeight(dp(54));
  row.setFocusable(true);
  row.setBackground(new android.graphics.drawable.RippleDrawable(
   android.content.res.ColorStateList.valueOf(0x22ffffff),null,surface(Color.WHITE,12)));
  row.setOnClickListener(view->{
   android.transition.AutoTransition expansion=new android.transition.AutoTransition();
   expansion.setDuration(180);
   android.transition.TransitionManager.beginDelayedTransition(panel,expansion);
   deviceExpanded=!deviceExpanded;
   updateDevicePanel();
  });
  View indicator=new View(this);
  indicator.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  linkDot=new GradientDrawable();
  linkDot.setShape(GradientDrawable.OVAL);
  indicator.setBackground(linkDot);
  LinearLayout.LayoutParams marker=new LinearLayout.LayoutParams(dp(10),dp(10));
  marker.setMarginEnd(dp(10));
  row.addView(indicator,marker);
  state=heading("",14);
  state.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  row.addView(state,new LinearLayout.LayoutParams(0,-2,1));
  deviceChevron=text("",18);
  deviceChevron.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  row.addView(deviceChevron);
  panel.addView(row,new LinearLayout.LayoutParams(-1,-2));

  deviceDetails=column();
  deviceDetails.setGravity(Gravity.CENTER_HORIZONTAL);
  deviceDetails.setPadding(0,dp(12),0,dp(18));
  pairedDevice=column();
  deviceModel=new RecorderModelView(this);
  deviceModel.setBackground(surface(0xff151619,14));
  deviceModel.setClipToOutline(true);
  pairedDevice.addView(deviceModel,new LinearLayout.LayoutParams(-1,dp(222)));
  deviceBattery=note("");
  deviceBattery.setGravity(Gravity.CENTER);
  LinearLayout.LayoutParams batteryRow=new LinearLayout.LayoutParams(-1,-2);
  batteryRow.topMargin=dp(6);
  pairedDevice.addView(deviceBattery,batteryRow);
  deviceDetails.addView(pairedDevice,new LinearLayout.LayoutParams(-1,-2));
  addDevice=addDeviceTile();
  deviceDetails.addView(addDevice,new LinearLayout.LayoutParams(-1,-2));
  reconnectDevice=button("Подключить\nзаново",this::openDevicePairing);
  reconnectDevice.setTextSize(13);
  reconnectDevice.setPadding(dp(8),dp(8),dp(8),dp(8));
  reconnectDevice.setSingleLine(false);
  reconnectDevice.setMaxLines(2);
  LinearLayout.LayoutParams reconnectSquare=new LinearLayout.LayoutParams(dp(94),dp(94));
  reconnectSquare.gravity=Gravity.CENTER_HORIZONTAL;
  reconnectSquare.topMargin=dp(8);
  deviceDetails.addView(reconnectDevice,reconnectSquare);
  panel.addView(deviceDetails,new LinearLayout.LayoutParams(-1,-2));
  showConnection(CaptureService.Link.OFF,"Микрофон выключен");
  updateDevicePanel();
 }
 private View addDeviceTile(){
  FrameLayout square=new FrameLayout(this){
   @Override protected void onMeasure(int width,int height){
    int side=View.MeasureSpec.getSize(width);
    if(getResources().getConfiguration().orientation==android.content.res.Configuration.ORIENTATION_LANDSCAPE){
     side=Math.min(side,dp(230));
    }
    int exact=View.MeasureSpec.makeMeasureSpec(side,View.MeasureSpec.EXACTLY);
    super.onMeasure(exact,exact);
   }
  };
  GradientDrawable tile=surface(0xff232529,14);
  tile.setStroke(dp(1),line);
  square.setBackground(new android.graphics.drawable.RippleDrawable(
   android.content.res.ColorStateList.valueOf(0x26ff593b),tile,null));
  square.setContentDescription("Добавить устройство");
  square.setFocusable(true);
  square.setOnClickListener(view->openDevicePairing());
  TextView title=heading("Добавить устройство",16);
  title.setGravity(Gravity.CENTER);
  title.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  FrameLayout.LayoutParams top=new FrameLayout.LayoutParams(-1,-2,Gravity.TOP);
  top.topMargin=dp(19);
  square.addView(title,top);
  TextView plus=text("+",62);
  plus.setTextColor(orange);
  plus.setTypeface(Typeface.create("sans-serif-light",Typeface.NORMAL));
  plus.setGravity(Gravity.CENTER);
  plus.setPadding(0,0,0,0);
  plus.setIncludeFontPadding(false);
  plus.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  square.addView(plus,new FrameLayout.LayoutParams(dp(96),dp(96),Gravity.CENTER));
  return square;
 }
 private void updateDevicePanel(){
  deviceDetails.setVisibility(deviceExpanded?View.VISIBLE:View.GONE);
  deviceChevron.setText(deviceExpanded?"⌃":"⌄");
  state.setContentDescription(state.getText()+". "+(deviceExpanded?"Свернуть":"Раскрыть")+" панель устройства");
  boolean paired=!getSharedPreferences("settings",0).getString("esp_paired_transport","").isEmpty();
  pairedDevice.setVisibility(paired?View.VISIBLE:View.GONE);
  addDevice.setVisibility(paired?View.GONE:View.VISIBLE);
  reconnectDevice.setVisibility(paired?View.VISIBLE:View.GONE);
  deviceBattery.setText(deviceCharge<0?"Заряд недоступен":"Заряд · "+deviceCharge+"%");
 }
 private void openDevicePairing(){
  if(CaptureService.recording||firmwareQuery!=null||devicePairing!=null)return;
  stopPresenceCheck();
  devicePairing=new EspPairing(this,charge->{
   deviceCharge=charge;
   transport.setSelected(sources.get(1));
   presenceSource="ble";
   presenceError="";
   idleLink=CaptureService.Link.CONNECTED;
   nextPresenceCheck=SystemClock.elapsedRealtime()+8000;
   paintConnection(idleLink,false,"");
   updateDevicePanel();
  },()->{
   devicePairing=null;
   if(resumed&&selectedPage==0)refreshConnection();
  });
  devicePairing.open();
 }
 private void showConnection(CaptureService.Link link,String message){
  if(displayedLink!=link){
   int color;
   switch(link){
    case CONNECTED:color=0xff57ce87;break;
    case CONNECTING:color=0xff629cff;break;
    case ERROR:color=0xffe8bc53;break;
    default:color=0xff767981;break;
   }
   linkDot.setColor(color);
   displayedLink=link;
  }
  if(!message.contentEquals(state.getText())){
   state.setText(message);
   state.setContentDescription(message+". "+(deviceExpanded?"Свернуть":"Раскрыть")+" панель устройства");
  }
 }
 private void refreshConnection(){
  String source=getSharedPreferences("settings",0).getString("transport","phone");
  boolean phone=source.equals("phone");
  if(CaptureService.recording){
   lastRecording=true;
   stopPresenceCheck();
   CaptureService.Link link=CaptureService.link;
   AudioManager audio=getSystemService(AudioManager.class);
   if(phone&&audio!=null&&audio.isMicrophoneMute())link=CaptureService.Link.OFF;
   paintConnection(link,phone,"");
   return;
  }
  if(lastRecording&&!CaptureService.status.isEmpty()){
   Toast.makeText(this,CaptureService.status,Toast.LENGTH_SHORT).show();
  }
  if(lastRecording||!source.equals(presenceSource)){
   lastRecording=false;
   stopPresenceCheck();
   presenceSource=source;
   idleLink=CaptureService.Link.OFF;
   presenceError="";
  }
  if(phone){
   if(microphonePermissionDenied&&checkSelfPermission("android.permission.RECORD_AUDIO")!=0){
    paintConnection(CaptureService.Link.ERROR,true,"Нет доступа к микрофону");
   }else if(CaptureService.link==CaptureService.Link.ERROR&&"phone".equals(CaptureService.linkSource)){
    paintConnection(CaptureService.Link.ERROR,true,CaptureService.status);
   }else{
    paintConnection(CaptureService.Link.OFF,true,"");
   }
   return;
  }
  if(resumed&&firmwareQuery==null&&devicePairing==null&&presenceCheck==null&&SystemClock.elapsedRealtime()>=nextPresenceCheck){
   if(nextPresenceCheck==0)idleLink=CaptureService.Link.CONNECTING;
   checkPresence();
  }
  paintConnection(idleLink,false,presenceError);
 }
 private void paintConnection(CaptureService.Link link,boolean phone,String detail){
  String message;
  switch(link){
   case CONNECTED:message=phone?"Микрофон подключён":"ESP-микрофон на связи";break;
   case CONNECTING:message=phone?"Подключаю микрофон…":"Подключаюсь к ESP…";break;
   case ERROR:message=detail.isEmpty()?"Ошибка подключения микрофона":detail;break;
   default:message=phone?"Микрофон выключен":"ESP-микрофон не обнаружен";break;
  }
  showConnection(link,message);
 }
 private void checkPresence(){
   boolean permission=Build.VERSION.SDK_INT>=31
    ?checkSelfPermission("android.permission.BLUETOOTH_SCAN")==0&&checkSelfPermission("android.permission.BLUETOOTH_CONNECT")==0
    :checkSelfPermission("android.permission.ACCESS_FINE_LOCATION")==0;
   if(!permission){
    idleLink=CaptureService.Link.ERROR;
    presenceError="Нет доступа к Bluetooth";
    nextPresenceCheck=SystemClock.elapsedRealtime()+8000;
    return;
   }
  Context app=getApplicationContext();
  presenceCheck=new Thread(()->{
   CaptureService.Link link;
   String detail="";
   try{EspFirmwareVersion.checkPresence(app);link=CaptureService.Link.CONNECTED;}
   catch(EspFirmwareVersion.NotFound error){link=CaptureService.Link.OFF;}
   catch(InterruptedException error){Thread.currentThread().interrupt();return;}
   catch(Exception error){link=CaptureService.Link.ERROR;detail=error instanceof java.io.IOException?error.getMessage():"";}
   CaptureService.Link result=link;
   String message=detail==null?"":detail;
   Thread completed=Thread.currentThread();
   runOnUiThread(()->{
    if(presenceCheck!=completed)return;
    presenceCheck=null;
    idleLink=result;
    presenceError=message;
    nextPresenceCheck=SystemClock.elapsedRealtime()+8000;
    if(resumed&&selectedPage==0&&!CaptureService.recording)paintConnection(result,false,message);
   });
  },"ESP presence");
  presenceCheck.start();
 }
 private void stopPresenceCheck(){
  if(presenceCheck!=null){presenceCheck.interrupt();presenceCheck=null;}
  nextPresenceCheck=0;
 }
 private void refresh(){
  boolean active=CaptureService.recording;
  if(selectedPage==0)refreshConnection();
  long seconds=active?CaptureService.samples/16000:0;duration.setText(String.format(Locale.US,"%02d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60));
  boolean pairingAvailable=!active&&firmwareQuery==null&&devicePairing==null;
  addDevice.setEnabled(pairingAvailable);
  reconnectDevice.setEnabled(pairingAvailable);
  firmwareButton.setEnabled(!active&&firmwareQuery==null);start.setEnabled(!active&&firmwareQuery==null);stop.setEnabled(active);transport.setEnabled(!active);start.setAlpha(active?.45f:1f);stop.setAlpha(active?1f:.45f);
  AppUpdates.check(this,false);
  installUpdate.setVisibility(AppUpdates.ready(this)?View.VISIBLE:View.GONE);installUpdate.setEnabled(!active);
  timer.postDelayed(()->refresh(),1000);
 }
 @Override public void onResume(){super.onResume();resumed=true;audioPage.setActive(selectedPage==AUDIO_PAGE);timer.removeCallbacksAndMessages(null);if(!getSharedPreferences("settings",0).getString("sync_token","").isEmpty())startForegroundService(CaptureService.command(this,"SYNC"));refresh();}
 @Override public void onPause(){resumed=false;stopPresenceCheck();transport.close();audioPage.setActive(false);timer.removeCallbacksAndMessages(null);super.onPause();}
 @Override public void onBackPressed(){
  if(selectedPage==AUDIO_PAGE&&audioPage.closeDropdown()||selectedPage==0&&transport.close())return;
  super.onBackPressed();
 }
 @Override public void onDestroy(){audioPage.dispose();if(devicePairing!=null)devicePairing.close();if(firmwareQuery!=null)firmwareQuery.interrupt();if(pairing!=null)pairing.cancel();super.onDestroy();}
}
