package ru.ilya.lecturerecorder;
import android.app.*;
import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.bluetooth.*;
import android.os.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.media.AudioManager;
import android.view.*;
import android.view.animation.PathInterpolator;
import android.widget.*;
import java.util.*;

public class MainActivity extends Activity {
 private TextView state,duration,deviceBattery;
 private RecordingMeter meter;
 private FrameLayout deviceReveal;
 private LinearLayout deviceToggle;
 private TextView deviceChevron;
 private ValueAnimator deviceExpansion;
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
 private Button recordAction;
 private boolean stoppingRecording;
 private Button recentRecording;
 private Button pendingLesson;
 private TextView recordState;
 private String lastSavedRecording="";
 private RecordingLessonFlow lessonFlow;
 private TextView mireaProfileStatus;
 private LinearLayout recordCard;
 private boolean recordingActionShown;
 private ChoiceDropdown transport;
 private final Handler timer=new Handler();
 private int selectedPage=0;
 private boolean pageShown;
 private static final int AUDIO_PAGE=1;
 private static final int SETTINGS_PAGE=2;
 private final View[] pages=new View[3];
 private final Button[] tabs=new Button[3];
 private View navSelection;
 private AudioTranscriptPage audioPage;
 private Object systemBackCallback;
 private boolean resumed;
 private static final int accent=StudioStyle.ACCENT,fg=StudioStyle.TEXT,muted=StudioStyle.MUTED,bg=StudioStyle.BACKGROUND,line=StudioStyle.LINE;
 private int dp(int n){return Math.round(getResources().getDisplayMetrics().density*n);}
 private GradientDrawable surface(int color,int radius){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));return d;}
 private TextView text(String value,int size){TextView t=new TextView(this);t.setText(value);t.setTextSize(size);t.setTextColor(fg);t.setPadding(0,dp(5),0,dp(5));t.setLineSpacing(dp(3),1);return t;}
 private TextView note(String value){TextView t=text(value,13);t.setTextColor(muted);return t;}
 private TextView heading(String value,int size){TextView t=text(value,size);t.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));return t;}
 private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
 private LinearLayout card(LinearLayout parent){
  LinearLayout card=column();
  card.setPadding(dp(16),dp(16),dp(16),dp(16));
  card.setBackground(StudioStyle.card(this,22));
  LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);
  layout.bottomMargin=dp(12);
  parent.addView(card,layout);
  return card;
 }
 private Button button(String label,Runnable action){return button(label,action,false);}
 private Button button(String label,Runnable action,boolean primary){
  Button button=new Button(this);
  button.setText(label);
  button.setTextSize(15);
  button.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
  button.setAllCaps(false);
  button.setTextColor(primary?StudioStyle.INK:fg);
  button.setMinHeight(dp(48));
  button.setMinimumHeight(dp(48));
  button.setPadding(dp(12),dp(12),dp(12),dp(12));
  button.setBackground(StudioStyle.control(this,primary?accent:StudioStyle.CONTROL,14));
  LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);
  layout.topMargin=dp(8);
  button.setLayoutParams(layout);
  button.setOnClickListener(view->action.run());
  return button;
 }
 private LinearLayout page(FrameLayout host,int index,String title){
  ScrollView scroll=new ScrollView(this);
  scroll.setFillViewport(true);
  scroll.setClipToPadding(false);
  scroll.setVerticalScrollBarEnabled(false);
  LinearLayout content=column();
  content.setPadding(dp(18),dp(16),dp(18),dp(16));
  TextView heading=heading(title,28);
  heading.setTypeface(Typeface.create("sans-serif",Typeface.BOLD));
  if(Build.VERSION.SDK_INT>=28)heading.setAccessibilityHeading(true);
  heading.setLetterSpacing(-.025f);
  LinearLayout.LayoutParams titleLayout=new LinearLayout.LayoutParams(-1,-2);
  titleLayout.bottomMargin=dp(10);
  content.addView(heading,titleLayout);
  scroll.addView(content);
  pages[index]=scroll;
  host.addView(scroll,new FrameLayout.LayoutParams(-1,-1));
  return content;
 }
 private void showPage(int index){
  if(index!=0){transport.close();stopPresenceCheck();}
  boolean entering=!pageShown||selectedPage!=index;
  int direction=Integer.compare(index,selectedPage);
  if(getResources().getConfiguration().getLayoutDirection()==View.LAYOUT_DIRECTION_RTL)direction=-direction;
  selectedPage=index;
  for(int i=0;i<pages.length;i++){
   boolean active=i==index;
   if(!active&&pages[i].getVisibility()==View.VISIBLE)StudioStyle.settle(pages[i]);
   pages[i].setVisibility(active?View.VISIBLE:View.GONE);
   tabs[i].setSelected(active);
   int color=active?accent:muted;
   tabs[i].setTextColor(color);
   StudioStyle.tabIcon(tabs[i],i,color);
  }
  positionNavSelection(pageShown&&entering);
  meter.setRecording(index==0&&CaptureService.recording);
  audioPage.setActive(resumed&&index==AUDIO_PAGE);
  if(index==0&&resumed)refreshConnection();
  if(index==SETTINGS_PAGE)refreshSyncSettings(CaptureService.recording);
  if(entering){
   if(pageShown)StudioStyle.enterPage(pages[index],direction);
   else StudioStyle.enter(pages[index],true);
  }
  pageShown=true;
 }
 private void positionNavSelection(boolean animate){
  Button active=tabs[selectedPage];
  if(active.getWidth()==0)return;
  android.view.ViewGroup.LayoutParams size=navSelection.getLayoutParams();
  if(size.width!=active.getWidth()||size.height!=active.getHeight()){
   size.width=active.getWidth();
   size.height=active.getHeight();
   navSelection.setLayoutParams(size);
  }
  navSelection.setTranslationY(active.getTop());
  StudioStyle.moveSelection(navSelection,active.getLeft(),animate);
 }
 @Override public void onCreate(Bundle saved){
  super.onCreate(saved);if(saved!=null){pendingPhoto=saved.getString("pending_photo");selectedPage=saved.getInt("page",0);if(selectedPage==3)selectedPage=AUDIO_PAGE;deviceExpanded=saved.getBoolean("device_expanded");deviceCharge=saved.getInt("device_charge",-1);}try{CaptureService.provision(this);if(!CaptureService.recording)Store.recover(this);}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}
  getWindow().setStatusBarColor(bg);getWindow().setNavigationBarColor(bg);getWindow().getDecorView().setSystemUiVisibility(0);
  lastSavedRecording=getPreferences(MODE_PRIVATE).getString("last_saved_recording","");
  if(saved!=null)stoppingRecording=saved.getBoolean("stopping_recording");
  lessonFlow=new RecordingLessonFlow(this,this::showSavedRecording,()->{
   refreshPendingLesson(CaptureService.recording);
  });
  LinearLayout root=column();root.setBackgroundColor(bg);setContentView(root);
  root.setOnApplyWindowInsetsListener((view,insets)->{view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());return insets.consumeSystemWindowInsets();});root.requestApplyInsets();
  FrameLayout host=new FrameLayout(this);root.addView(host,new LinearLayout.LayoutParams(-1,0,1));
  LinearLayout record=page(host,0,"Новая запись");
  LinearLayout hero=card(record);
  recordCard=hero;
  hero.setBackground(StudioStyle.recorderCard(this,false));

  recordState=note("Готово к записи");
  recordState.setTextColor(accent);
  recordState.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
  recordState.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  hero.addView(recordState);
  duration=text("00:00:00",52);
  duration.setTypeface(Typeface.create("sans-serif-condensed",Typeface.NORMAL));
  duration.setFontFeatureSettings("tnum");
  duration.setLetterSpacing(-.015f);
  duration.setIncludeFontPadding(false);
  duration.setSingleLine(true);
  duration.setAutoSizeTextTypeUniformWithConfiguration(26,52,1,android.util.TypedValue.COMPLEX_UNIT_SP);
  duration.setPadding(0,dp(4),0,dp(10));
  hero.addView(duration,new LinearLayout.LayoutParams(-1,dp(74)));

  recordAction=button("Начать запись",()->{
   if(stoppingRecording||recordingActionShown!=CaptureService.recording)return;
   if(!recordingActionShown){begin();return;}
   try{
    startForegroundService(CaptureService.command(this,"STOP"));
    stoppingRecording=true;
    showStoppingRecording();
   }catch(RuntimeException error){
    recordState.setText("Не удалось остановить запись. Повтори попытку.");
   }
  },true);
  recordAction.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);
  recordAction.setPadding(dp(16),dp(12),dp(16),dp(12));
  recordAction.setMinHeight(dp(54));
  recordAction.setMinimumHeight(dp(54));
  StudioStyle.recordIcon(recordAction,false);
  TextView meterLabel=note("Уровень сигнала");
  meterLabel.setPadding(0,dp(4),0,dp(6));
  hero.addView(meterLabel);
  meter=new RecordingMeter(this);
  hero.addView(meter,new LinearLayout.LayoutParams(-1,dp(46)));
  hero.addView(recordAction);
  pendingLesson=button("Выбрать пару для записи",lessonFlow::openPending);
  pendingLesson.setVisibility(View.GONE);
  hero.addView(pendingLesson);
  recentRecording=button("Открыть последнюю запись",this::openSavedRecording);
  recentRecording.setVisibility(View.GONE);
  hero.addView(recentRecording);

  addRecordingShortcuts(record);
  LinearLayout microphone=card(record);
  microphone.addView(heading("Источник звука",16));
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
  microphone.addView(transport.button,new LinearLayout.LayoutParams(-1,-2));
  LinearLayout.LayoutParams sourceList=new LinearLayout.LayoutParams(-1,-2);
  sourceList.topMargin=dp(6);
  microphone.addView(transport.list,sourceList);
  addConnectionPanel(microphone);
  if(saved!=null)deviceModel.setYaw(saved.getFloat("device_rotation",-.30f));
  LinearLayout settingsPage=page(host,SETTINGS_PAGE,"Настройки");
  LinearLayout profile=card(settingsPage);
  profile.addView(heading("Учёба в МИРЭА",18));
  mireaProfileStatus=note(lessonFlow.profileLabel());
  profile.addView(mireaProfileStatus);
  profile.addView(button("Группа и курс",()->{if(!CaptureService.recording)lessonFlow.profile(true);}));
  LinearLayout mac=card(settingsPage);
  mac.addView(heading("Телефон и Mac",18));
  macStatus=note("");
  macStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  mac.addView(macStatus);
  connectMac=button("Подключить Mac",this::pairPhone);
  mac.addView(connectMac);
  LinearLayout updates=card(settingsPage);
  updates.addView(heading("Обновления",18));
  try { updates.addView(note("Установлена версия "+getPackageManager().getPackageInfo(getPackageName(),0).versionName)); }
  catch (android.content.pm.PackageManager.NameNotFoundException ignored) {}
  updateStatus=note("");
  updateStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  updates.addView(updateStatus);
  installUpdate=button("Установить обновление",()->AppUpdates.install(this),true);
  installUpdate.setVisibility(View.GONE);
  updates.addView(installUpdate);
  LinearLayout connection=card(settingsPage);
  connection.addView(heading("Микрофон ESP",18));
  firmwareButton=button("Проверить версию прошивки",this::checkFirmware);
  connection.addView(firmwareButton);
  firmwareStatus=note("");
  firmwareStatus.setVisibility(View.GONE);
  firmwareStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  connection.addView(firmwareStatus);
  audioPage=new AudioTranscriptPage(this,saved==null?null:saved.getBundle("audio_page"),this::chooseAudio);
  pages[AUDIO_PAGE]=audioPage;
  host.addView(audioPage,new FrameLayout.LayoutParams(-1,-1));

  FrameLayout nav=new FrameLayout(this);
  nav.setBackground(StudioStyle.card(this,22));
  navSelection=new View(this);
  navSelection.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  navSelection.setBackground(StudioStyle.surface(this,StudioStyle.ACTIVE,16));
  nav.addView(navSelection,new FrameLayout.LayoutParams(0,0,Gravity.LEFT|Gravity.TOP));
  LinearLayout navTabs=new LinearLayout(this);
  navTabs.setPadding(dp(5),dp(5),dp(5),dp(5));
  nav.addView(navTabs,new FrameLayout.LayoutParams(-1,-2));
  String[] labels={"Запись","Аудио","Настройки"};
  for(int index=0;index<labels.length;index++){
   int pageIndex=index;
   Button tab=button(labels[index],()->showPage(pageIndex));
   tab.setTextSize(12);
   tab.setMaxLines(1);
   tab.setPadding(dp(2),dp(5),dp(2),dp(5));
   LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,-2,1);
   lp.setMargins(dp(2),0,dp(2),0);
   tab.setBackground(StudioStyle.control(this,Color.TRANSPARENT,16));
   navTabs.addView(tab,lp);
   tabs[index]=tab;
  }
  navTabs.addOnLayoutChangeListener((view,left,top,right,bottom,oldLeft,oldTop,oldRight,oldBottom)->{
   if(right-left!=oldRight-oldLeft||bottom-top!=oldBottom-oldTop)positionNavSelection(false);
  });
  LinearLayout.LayoutParams navigation=new LinearLayout.LayoutParams(-1,-2);
  navigation.setMargins(dp(12),0,dp(12),dp(8));
  root.addView(nav,navigation);
  if(saved!=null)pageShown=true;
  showPage(Math.max(0,Math.min(pages.length-1,selectedPage)));
  if(saved==null)StudioStyle.enter(nav,true);
  if(Build.VERSION.SDK_INT>=33){
   android.window.OnBackInvokedCallback callback=()->{
    if(!handleBack()&&(!isTaskRoot()||!moveTaskToBack(false)))finish();
   };
   getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,callback);
   systemBackCallback=callback;
  }
  if(Build.VERSION.SDK_INT>=33&&checkSelfPermission("android.permission.POST_NOTIFICATIONS")!=0)requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"},2);
 }
 private TextView firmwareStatus,macStatus,updateStatus;
 private Button firmwareButton,connectMac,installUpdate;
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
  android.content.SharedPreferences settings=getSharedPreferences("settings",0);
  boolean bonded=EspDeviceConnection.BONDED.equals(settings.getString(EspDeviceConnection.PAIRING_MODE,""));
  if(!bonded&&settings.getString("token","").isEmpty()){
   setDeviceExpanded(true);openDevicePairing();return;
  }
  if(settings.getString("transport","ble").equals("ble")){
   String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
   for(String p:permissions)if(checkSelfPermission(p)!=0){requestPermissions(permissions,3);return;}
   BluetoothAdapter a=getSystemService(BluetoothManager.class).getAdapter();if(a==null){Toast.makeText(this,"На телефоне нет Bluetooth",1).show();return;}if(!a.isEnabled()){startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),4);return;}
   String address=settings.getString("ble_address","");
   if(bonded&&(!BluetoothAdapter.checkBluetoothAddress(address)||a.getRemoteDevice(address).getBondState()!=BluetoothDevice.BOND_BONDED)){
    setDeviceExpanded(true);openDevicePairing();return;
   }
  }
  startForegroundService(CaptureService.command(this,"START"));
 }
 @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grant){super.onRequestPermissionsResult(code,permissions,grant);if(code==EspPairing.BLUETOOTH_PERMISSION){if(devicePairing!=null)devicePairing.permissionResult(grant);return;}if(code==9){for(int result:grant)if(result!=0)return;if(grant.length>0)checkFirmware();return;}if(code==8){microphonePermissionDenied=grant.length>0&&grant[0]!=0;if(grant.length>0&&grant[0]==0)begin();else refreshConnection();return;}if(code==5&&grant.length>0){for(int g:grant)if(g!=0){startForegroundService(CaptureService.command(this,"SYNC"));return;}transfer();}if(code==3&&grant.length>0){for(int g:grant)if(g!=0)return;begin();}}
 @Override protected void onActivityResult(int code,int result,Intent data){super.onActivityResult(code,result,data);if(code==EspPairing.ENABLE_BLUETOOTH){if(devicePairing!=null)devicePairing.bluetoothEnableResult(result);return;}if(code==7&&result==RESULT_OK&&data!=null&&data.getData()!=null){android.net.Uri uri=data.getData();try{getContentResolver().takePersistableUriPermission(uri,data.getFlags()&Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(Exception ignored){}AudioImport.start(this,uri);return;}if(code==4&&result==RESULT_OK)begin();if(code==6&&result==RESULT_OK){final String id=pendingPhoto;pendingPhoto=null;new Thread(()->{try{BoardPhotos.markReady(this,id);BoardPhotos.finish(this,id);runOnUiThread(()->{Toast.makeText(this,"Фото сохранено · будет перенесено и разобрано на Mac",1).show();transfer();});}catch(Exception e){runOnUiThread(()->Toast.makeText(this,e.getMessage(),1).show());}},"Save board photo").start();}else if(code==6){BoardPhotos.cancel(this,pendingPhoto);pendingPhoto=null;}}
 @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("pending_photo",pendingPhoto);out.putInt("page",selectedPage);out.putBundle("audio_page",audioPage.snapshot());out.putBoolean("device_expanded",deviceExpanded);out.putInt("device_charge",deviceCharge);out.putFloat("device_rotation",deviceModel.rotation());out.putBoolean("stopping_recording",stoppingRecording);}
 private void showSavedRecording(String file){
  lastSavedRecording=file;
  getPreferences(MODE_PRIVATE).edit().putString("last_saved_recording",file).apply();
  if(!CaptureService.recording)recordState.setText("Запись сохранена");
  refreshSavedRecording(CaptureService.recording);
  refreshPendingLesson(CaptureService.recording);
 }
 private void refreshPendingLesson(boolean recording){
  int visibility=!recording&&lessonFlow.hasPending()?View.VISIBLE:View.GONE;
  if(visibility==pendingLesson.getVisibility())return;
  pendingLesson.setVisibility(visibility);
  if(visibility==View.VISIBLE&&selectedPage==0)StudioStyle.enter(pendingLesson,false);
 }
 private void refreshSavedRecording(boolean recording){
  int visibility=!recording&&LectureNotes.valid(lastSavedRecording)&&
    (Store.audio(this,lastSavedRecording).isFile()||LectureNotes.file(this,lastSavedRecording,true).isFile()||
     LectureNotes.file(this,lastSavedRecording,false).isFile())?View.VISIBLE:View.GONE;
  if(visibility==recentRecording.getVisibility())return;
  recentRecording.setVisibility(visibility);
  if(visibility==View.VISIBLE&&selectedPage==0)StudioStyle.enter(recentRecording,false);
 }
 private void openSavedRecording(){
  audioPage.openRecording(lastSavedRecording);
  showPage(AUDIO_PAGE);
 }
 private void takeBoardPhoto(){try{pendingPhoto=BoardPhotos.prepare(this);android.net.Uri uri=android.net.Uri.parse("content://"+getPackageName()+".photos/"+pendingPhoto+".jpg");Intent camera=new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);camera.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,uri);camera.setClipData(ClipData.newRawUri("Фото доски",uri));camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(camera,6);}catch(Exception e){Toast.makeText(this,"Не удалось открыть камеру: "+e.getMessage(),1).show();}}
 private void chooseAudio(){
  Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("audio/*").addCategory(Intent.CATEGORY_OPENABLE)
   .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
  startActivityForResult(pick,7);
 }
 private void addRecordingShortcuts(LinearLayout record){
  LinearLayout shortcuts=column();
  boolean horizontal=getResources().getConfiguration().screenWidthDp>=360
    &&getResources().getConfiguration().fontScale<=1.25f;
  if(horizontal)shortcuts.setOrientation(LinearLayout.HORIZONTAL);
  LinearLayout.LayoutParams placement=new LinearLayout.LayoutParams(-1,-2);
  placement.bottomMargin=dp(12);
  record.addView(shortcuts,placement);
  Button importAudio=button("Импорт аудио",this::chooseAudio);
  Button photo=button("Фото доски",this::takeBoardPhoto);
  LinearLayout.LayoutParams first=new LinearLayout.LayoutParams(horizontal?0:-1,-2,horizontal?1:0);
  LinearLayout.LayoutParams second=new LinearLayout.LayoutParams(horizontal?0:-1,-2,horizontal?1:0);
  if(horizontal)first.setMarginEnd(dp(10));else second.topMargin=dp(8);
  shortcuts.addView(importAudio,first);
  shortcuts.addView(photo,second);
 }
 private void addConnectionPanel(LinearLayout panel){
  LinearLayout signal=new LinearLayout(this);
  signal.setGravity(Gravity.CENTER_VERTICAL);
  signal.setMinimumHeight(dp(36));
  View indicator=new View(this);
  indicator.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  linkDot=new GradientDrawable();
  linkDot.setShape(GradientDrawable.OVAL);
  indicator.setBackground(linkDot);
  LinearLayout.LayoutParams marker=new LinearLayout.LayoutParams(dp(10),dp(10));
  marker.setMarginEnd(dp(10));
  signal.addView(indicator,marker);
  state=note("");
  state.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  signal.addView(state,new LinearLayout.LayoutParams(0,-2,1));
  panel.addView(signal,new LinearLayout.LayoutParams(-1,-2));

  LinearLayout row=new LinearLayout(this);
  deviceToggle=row;
  row.setGravity(Gravity.CENTER_VERTICAL);
  row.setMinimumHeight(dp(48));
  row.setFocusable(true);
  row.setBackground(new android.graphics.drawable.RippleDrawable(
   android.content.res.ColorStateList.valueOf(0x22ffffff),null,surface(Color.WHITE,12)));
  row.setOnClickListener(view->toggleDevicePanel());
  row.addView(heading("Устройство ESP",14),new LinearLayout.LayoutParams(0,-2,1));
  deviceChevron=note("⌄");
  deviceChevron.setGravity(Gravity.CENTER);
  deviceChevron.setRotation(deviceExpanded?180f:0f);
  deviceChevron.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  row.addView(deviceChevron,new LinearLayout.LayoutParams(dp(28),dp(32)));
  panel.addView(row,new LinearLayout.LayoutParams(-1,-2));

  deviceDetails=column();
  deviceDetails.setGravity(Gravity.CENTER_HORIZONTAL);
  deviceDetails.setPadding(0,dp(6),0,dp(8));
  pairedDevice=column();
  deviceModel=new RecorderModelView(this);
  deviceModel.setBackground(surface(StudioStyle.BACKGROUND,16));
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
  deviceReveal=new FrameLayout(this);
  deviceReveal.setClipChildren(true);
  deviceReveal.addView(deviceDetails,new FrameLayout.LayoutParams(-1,-2));
  panel.addView(deviceReveal,new LinearLayout.LayoutParams(-1,-2));
  showConnection(CaptureService.Link.OFF,"Микрофон выключен");
  updateDevicePanel();
  deviceReveal.setVisibility(deviceExpanded?View.VISIBLE:View.GONE);
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
  GradientDrawable tile=surface(StudioStyle.CONTROL,18);
  tile.setStroke(dp(1),line);
  square.setBackground(new android.graphics.drawable.RippleDrawable(
   android.content.res.ColorStateList.valueOf(0x26c5b5ff),tile,null));
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
  plus.setTextColor(accent);
  plus.setTypeface(Typeface.create("sans-serif-light",Typeface.NORMAL));
  plus.setGravity(Gravity.CENTER);
  plus.setPadding(0,0,0,0);
  plus.setIncludeFontPadding(false);
  plus.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  square.addView(plus,new FrameLayout.LayoutParams(dp(96),dp(96),Gravity.CENTER));
  return square;
 }
 private void updateDevicePanel(){
  deviceToggle.setContentDescription(panelAction());
  boolean paired=!getSharedPreferences("settings",0).getString("esp_paired_transport","").isEmpty();
  pairedDevice.setVisibility(paired?View.VISIBLE:View.GONE);
  addDevice.setVisibility(paired?View.GONE:View.VISIBLE);
  reconnectDevice.setVisibility(paired?View.VISIBLE:View.GONE);
  deviceBattery.setText(deviceCharge<0?"Заряд недоступен":"Заряд · "+deviceCharge+"%");
 }
 private String panelAction(){
  return (deviceExpanded?"Свернуть":"Раскрыть")+" настройки устройства ESP";
 }
 private void toggleDevicePanel(){
  setDeviceExpanded(!deviceExpanded);
 }
 private void setDeviceExpanded(boolean expanded){
  if(deviceExpanded==expanded)return;
  deviceExpanded=expanded;
  updateDevicePanel();
  deviceChevron.animate().cancel();
  float rotation=expanded?180f:0f;
  if(ValueAnimator.areAnimatorsEnabled())deviceChevron.animate().rotation(rotation).setDuration(180).start();
  else deviceChevron.setRotation(rotation);

  if(deviceExpansion!=null){
   ValueAnimator previous=deviceExpansion;
   deviceExpansion=null;
   previous.cancel();
  }
  int from=deviceReveal.getVisibility()==View.VISIBLE?deviceReveal.getHeight():0;
  int width=deviceReveal.getWidth();
  if(width<=0){
   View panel=(View)deviceReveal.getParent();
   width=panel.getWidth()-panel.getPaddingLeft()-panel.getPaddingRight();
  }
  if(width<=0||!ValueAnimator.areAnimatorsEnabled()){
   ViewGroup.LayoutParams layout=deviceReveal.getLayoutParams();
   layout.height=ViewGroup.LayoutParams.WRAP_CONTENT;
   deviceReveal.setLayoutParams(layout);
   deviceReveal.setVisibility(expanded?View.VISIBLE:View.GONE);
   return;
  }
  int target=0;
  if(expanded){
   deviceDetails.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),
    View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED));
   target=deviceDetails.getMeasuredHeight();
  }
  ViewGroup.LayoutParams layout=deviceReveal.getLayoutParams();
  layout.height=from;
  deviceReveal.setLayoutParams(layout);
  deviceReveal.setVisibility(View.VISIBLE);
  ValueAnimator animation=ValueAnimator.ofInt(from,target);
  deviceExpansion=animation;
  animation.setDuration(250);
  animation.setInterpolator(new PathInterpolator(.22f,0f,.2f,1f));
  animation.addUpdateListener(frame->{
   layout.height=(Integer)frame.getAnimatedValue();
   deviceReveal.requestLayout();
  });
  animation.addListener(new AnimatorListenerAdapter(){
   @Override public void onAnimationEnd(Animator ended){
    if(deviceExpansion!=animation)return;
    deviceExpansion=null;
    layout.height=ViewGroup.LayoutParams.WRAP_CONTENT;
    deviceReveal.setLayoutParams(layout);
    deviceReveal.setVisibility(deviceExpanded?View.VISIBLE:View.GONE);
   }
  });
  animation.start();
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
    case CONNECTED:color=StudioStyle.GOOD;break;
    case CONNECTING:color=accent;break;
    case ERROR:color=StudioStyle.WARNING;break;
    default:color=muted;break;
   }
   linkDot.setColor(color);
   displayedLink=link;
  }
  if(!message.contentEquals(state.getText())){
   state.setText(message);
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
 private void showStoppingRecording(){
  recordState.setText("Сохраняю аудио…");
  recordAction.setText("Сохраняю…");
  recordAction.setEnabled(false);
 }
 private void refresh(){
  boolean active=CaptureService.recording;
  if(!active)stoppingRecording=false;
  else if("Сохраняю запись…".equals(CaptureService.status))stoppingRecording=true;
  if(selectedPage==0)refreshConnection();
  long seconds=active?CaptureService.samples/16000:0;duration.setText(String.format(Locale.US,"%02d:%02d:%02d",seconds/3600,seconds/60%60,seconds%60));
  boolean pairingAvailable=!active&&firmwareQuery==null&&devicePairing==null;
  addDevice.setEnabled(pairingAvailable);
  reconnectDevice.setEnabled(pairingAvailable);
  firmwareButton.setEnabled(!active&&firmwareQuery==null);
  if(active!=recordingActionShown){
   recordingActionShown=active;
   recordState.setText(active?"Идёт запись":"Готово к записи");
   recordState.setTextColor(active?StudioStyle.RECORDING:accent);
   recordAction.setText(active?"Завершить запись":"Начать запись");
   recordAction.setBackground(StudioStyle.control(this,active?StudioStyle.RECORDING:accent,14));
   StudioStyle.recordIcon(recordAction,active);
   recordCard.setBackground(StudioStyle.recorderCard(this,active));
   if(selectedPage==0){
    StudioStyle.changeAction(recordAction);
    StudioStyle.enter(recordState,false);
   }
  }
  refreshSavedRecording(active);
  if(stoppingRecording){
   if(recordAction.isEnabled())showStoppingRecording();
  }else recordAction.setEnabled(active||firmwareQuery==null);
  transport.setEnabled(!active);
  meter.setRecording(active&&selectedPage==0);
  if(selectedPage==SETTINGS_PAGE)refreshSyncSettings(active);
  mireaProfileStatus.setText(lessonFlow.profileLabel());
  lessonFlow.refresh(active);
  refreshPendingLesson(active);
  timer.postDelayed(()->refresh(),1000);
 }
 private void refreshSyncSettings(boolean recording){
  boolean paired=CaptureService.paired(this);
  String macName=getSharedPreferences("settings",0).getString("paired_mac","").trim();
  String connection="Mac ещё не сопряжён";
  String action="Подключить Mac";
  if(paired){
   connection=macName.isEmpty()?"Mac сопряжён":"Сопряжён с «"+macName+"»";
   action="Сменить Mac";
  }
  if(!connection.contentEquals(macStatus.getText()))macStatus.setText(connection);
  if(!action.contentEquals(connectMac.getText()))connectMac.setText(action);
  connectMac.setEnabled(!recording);
  boolean available=AppUpdates.ready(this);
  String message=AppUpdates.message(this,available);
  if(!message.contentEquals(updateStatus.getText()))updateStatus.setText(message);
  installUpdate.setVisibility(available?View.VISIBLE:View.GONE);
  installUpdate.setEnabled(!recording);
 }
 @Override protected void onStart(){super.onStart();CaptureService.screenStarted();}
 @Override public void onResume(){super.onResume();resumed=true;lessonFlow.onResume();audioPage.setActive(selectedPage==AUDIO_PAGE);timer.removeCallbacksAndMessages(null);CaptureService.resumeSync(this);refresh();}
 @Override public void onPause(){resumed=false;stopPresenceCheck();transport.close();audioPage.setActive(false);timer.removeCallbacksAndMessages(null);super.onPause();}
 @Override protected void onStop(){CaptureService.screenStopped();super.onStop();}
 private boolean handleBack(){
  if(selectedPage==AUDIO_PAGE)return audioPage.closeDropdown();
  return selectedPage==0&&transport.close();
 }
 @Override public void onBackPressed(){
  if(!handleBack())super.onBackPressed();
 }
 @Override public void onDestroy(){
  if(Build.VERSION.SDK_INT>=33&&systemBackCallback!=null)
   getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback((android.window.OnBackInvokedCallback)systemBackCallback);
  lessonFlow.dispose();
  audioPage.dispose();
  if(deviceExpansion!=null)deviceExpansion.cancel();
  if(devicePairing!=null)devicePairing.close();
  if(firmwareQuery!=null)firmwareQuery.interrupt();
  if(pairing!=null)pairing.cancel();
  super.onDestroy();
 }
}
