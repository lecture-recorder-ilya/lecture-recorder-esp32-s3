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
 private static final String SOURCE_MODE="capture_source";
 private final List<ChoiceDropdown.Option> sources=new ArrayList<>(Arrays.asList(
  new ChoiceDropdown.Option("auto","Автоматически","ClipMic рядом, гарнитура или телефон"),
  new ChoiceDropdown.Option("phone","Телефон или гарнитура","Системный аудиовход"),
  new ChoiceDropdown.Option("ble","Только ClipMic","Bluetooth")));
 private GradientDrawable linkDot;
 private CaptureService.Link displayedLink;
 private CaptureService.Link idleLink=CaptureService.Link.OFF;
 private Thread presenceCheck;
 private String presenceSource="",presenceError="";
 private long nextPresenceCheck;
 private boolean lastRecording;
 private static final String MICROPHONE_PERMISSION=android.Manifest.permission.RECORD_AUDIO;
 private static final String MICROPHONE_ASKED="microphone_permission_asked";
 private Button recordAction, recordImport;
 private boolean stoppingRecording;
 private long startPendingUntil, captureTapUntil;
 private Button recentRecording;
 private Button pendingLesson;
 private TextView recordTitle,recordState,receiptDetails;
 private LinearLayout signal;
 private FrameLayout navigationBar;
 private String receiptFile="",receiptSource="",receiptTime="",captureProblem="";
 private boolean receiptPending;
 private CaptureMode paintedMode;
 private enum CaptureMode { READY, STARTING, LIVE, STOPPING, SAVED }
 private String lastSavedRecording="";
 private RecordingLessonFlow lessonFlow;
 private TextView mireaProfileStatus;
 private boolean recordingActionShown;
 private ChoiceDropdown transport;
 private final Handler timer=new Handler();
 private final Runnable refreshTask=this::refresh;
 private long nextLibraryRefresh;
 private int selectedPage=0;
 private boolean pageShown;
 private static final int AUDIO_PAGE=1;
 private static final int SETTINGS_PAGE=2;
 private static final int LIBRARY_PAGE=3;
 private boolean landscape;
 private final View[] pages=new View[4];
 private final Button[] tabs=new Button[4];
 private View navSelection;
 private AudioTranscriptPage audioPage;
 private RecordingLibraryPage libraryPage;
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
  card.setBackground(StudioStyle.card(this,StudioStyle.CARD_RADIUS));
  LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);
  layout.bottomMargin=dp(12);
  parent.addView(card,layout);
  return card;
 }
 private Button button(String label,Runnable action){return button(label,action,false);}
 private Button button(String label,Runnable action,boolean primary){
  Button button=StudioStyle.action(this,label,action,primary);
  LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);
  layout.topMargin=dp(8);
  button.setLayoutParams(layout);
  return button;
 }
 private LinearLayout page(FrameLayout host,int index,String title){
  ScrollView scroll=new ScrollView(this);
  scroll.setFillViewport(true);
  scroll.setClipToPadding(false);
  scroll.setVerticalScrollBarEnabled(false);
  LinearLayout content=column();
  int inset=dp(StudioStyle.PAGE_INSET);
  content.setPadding(inset,dp(12),inset,dp(12));
  if(title!=null){
   TextView heading=StudioStyle.title(this,title);
   LinearLayout.LayoutParams titleLayout=new LinearLayout.LayoutParams(-1,-2);
   titleLayout.bottomMargin=dp(14);
   content.addView(heading,titleLayout);
  }
  scroll.addView(content);
  pages[index]=scroll;
  host.addView(scroll,new FrameLayout.LayoutParams(-1,-1));
  return content;
 }
 private void showPage(int index){
  if(index!=0){transport.close();stopPresenceCheck();}
  boolean entering=!pageShown||selectedPage!=index;
  int direction=0;
  if(pageShown&&entering&&selectedPage>=0&&selectedPage<tabs.length){
   Button from=tabs[navPage(selectedPage)],to=tabs[navPage(index)];
   direction=landscape?to.getTop()-from.getTop():to.getLeft()-from.getLeft();
  }
  if(entering&&index==0)lessonFlow.onResume();
  selectedPage=index;
  for(int i=0;i<pages.length;i++){
   boolean active=i==index;
   if(!active&&pages[i].getVisibility()==View.VISIBLE)StudioStyle.settle(pages[i]);
   pages[i].setVisibility(active?View.VISIBLE:View.GONE);
   if(tabs[i]==null)continue;
   boolean tabSelected=i==navPage(index);
   tabs[i].setSelected(tabSelected);
   int color=tabSelected?accent:muted;
   tabs[i].setTextColor(color);
   StudioStyle.tabIcon(tabs[i],i==LIBRARY_PAGE?5:i,color);
  }
  navigationBar.setVisibility(index==AUDIO_PAGE?View.GONE:View.VISIBLE);
  positionNavSelection(pageShown&&entering);
  meter.setRecording(index==0&&CaptureService.recording);
  audioPage.setActive(resumed&&index==AUDIO_PAGE);
  if(index==0&&resumed&&(CaptureService.recording||receiptFile.isEmpty()))refreshConnection();
  if(index==SETTINGS_PAGE)refreshSyncSettings(CaptureService.recording);
  if(index==LIBRARY_PAGE)refreshLibrary();
  if(entering&&pageShown)StudioStyle.enterPage(pages[index],direction,landscape);
  pageShown=true;
 }
 private int navPage(int page){return page==AUDIO_PAGE?LIBRARY_PAGE:page;}
 private void positionNavSelection(boolean animate){
  Button active=tabs[navPage(selectedPage)];
  if(active.getWidth()==0)return;
  android.view.ViewGroup.LayoutParams size=navSelection.getLayoutParams();
  if(size.width!=active.getWidth()||size.height!=active.getHeight()){
   size.width=active.getWidth();
   size.height=active.getHeight();
   navSelection.setLayoutParams(size);
  }
  StudioStyle.moveSelection(navSelection,active.getLeft(),active.getTop(),animate);
 }
 @Override public void onCreate(Bundle saved){
  super.onCreate(saved);
  if(saved!=null&&saved.getString("export_kind")!=null){
   exportFile=saved.getString("export_file");
   exportKind=RecordingExport.Kind.valueOf(saved.getString("export_kind"));
  }
  if(saved!=null){pendingPhoto=saved.getString("pending_photo");selectedPage=saved.getInt("page",0);deviceExpanded=saved.getBoolean("device_expanded");deviceCharge=saved.getInt("device_charge",-1);}try{CaptureService.provision(this);if(!CaptureService.recording)Store.recover(this);}catch(Exception e){Toast.makeText(this,e.getMessage(),Toast.LENGTH_LONG).show();}
  lastSavedRecording=getPreferences(MODE_PRIVATE).getString("last_saved_recording","");
  if(saved!=null){
   stoppingRecording=saved.getBoolean("stopping_recording");
   recordingActionShown=saved.getBoolean("capture_observed",stoppingRecording);
  }
  landscape=getResources().getConfiguration().orientation==android.content.res.Configuration.ORIENTATION_LANDSCAPE;
  lessonFlow=new RecordingLessonFlow(this,this::showSavedRecording,()->{
   renderRecorder(CaptureService.recording);
   if(selectedPage==LIBRARY_PAGE)refreshLibrary();
  },this::showDiscardedRecording);
  LinearLayout root=column();
  if(landscape)root.setOrientation(LinearLayout.HORIZONTAL);root.setBackgroundColor(bg);setContentView(root);
  StudioStyle.fitWindow(getWindow(),root,0,0,0);
  root.requestApplyInsets();
  FrameLayout host=new FrameLayout(this);
  root.addView(host,landscape?new LinearLayout.LayoutParams(0,-1,1):new LinearLayout.LayoutParams(-1,0,1));
  buildRecorder(page(host,0,null));
  if(saved!=null)presentReceipt(saved.getString("receipt_file",""));
  LinearLayout settingsPage=page(host,SETTINGS_PAGE,"Настройки");
  LinearLayout mac=card(settingsPage);
  mac.addView(heading("Синхронизация",18));
  macStatus=note("");
  macStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  mac.addView(macStatus);
  connectMac=button("Подключить Mac",this::pairPhone,true);
  mac.addView(connectMac);
  LinearLayout profile=card(settingsPage);
  profile.addView(heading("Расписание",18));
  mireaProfileStatus=note(lessonFlow.profileLabel());
  profile.addView(mireaProfileStatus);
  Button editProfile=button("Группа и курс",()->lessonFlow.profile(true));
  editProfile.setEnabled(!CaptureService.recording);
  profile.addView(editProfile);
  profileAction=editProfile;
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
  githubCheck=button("Получать обновления без Mac",()->GitHubUpdates.start(this,true));
  updates.addView(githubCheck);
  githubDisconnect=button("Отключить GitHub на телефоне",()->GitHubUpdates.disconnect(this));
  updates.addView(githubDisconnect);
  LinearLayout connection=card(settingsPage);
  addConnectionPanel(connection);
  if(saved!=null)deviceModel.setYaw(saved.getFloat("device_rotation",-.30f));
  firmwareButton=button("Проверить версию прошивки",this::checkFirmware);
  connection.addView(firmwareButton);
  firmwareStatus=note("");
  firmwareStatus.setVisibility(View.GONE);
  firmwareStatus.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  connection.addView(firmwareStatus);
  LinearLayout materials=card(settingsPage);
  materials.addView(heading("Материалы пары",18));
  materials.addView(button("Сфотографировать доску",this::takeBoardPhoto));
  audioPage=new AudioTranscriptPage(this,saved==null?null:saved.getBundle("audio_page"),()->showPage(LIBRARY_PAGE),this::exportRecording);
  pages[AUDIO_PAGE]=audioPage;
  host.addView(audioPage,new FrameLayout.LayoutParams(-1,-1));
  libraryPage=new RecordingLibraryPage(this,this::chooseAudio,entry->{
   if(entry.pending){
    if(CaptureService.recording)Toast.makeText(this,"Выбор пары доступен после записи.",Toast.LENGTH_SHORT).show();
    else lessonFlow.openPending(entry.file);
   }else{
    openLibraryRecording(entry.file);
   }
  });
  if(saved!=null)libraryPage.restoreQuery(saved.getString("library_query",""),saved.getBoolean("library_waiting"),saved.getBoolean("library_favorites"));
  pages[LIBRARY_PAGE]=libraryPage;
  host.addView(libraryPage,new FrameLayout.LayoutParams(-1,-1));

  FrameLayout nav=new FrameLayout(this);
  navigationBar=nav;
  nav.setBackground(StudioStyle.card(this,StudioStyle.CARD_RADIUS));
  navSelection=new View(this);
  navSelection.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  navSelection.setBackground(StudioStyle.surface(this,StudioStyle.ACTIVE,16));
  nav.addView(navSelection,new FrameLayout.LayoutParams(0,0,Gravity.LEFT|Gravity.TOP));
  LinearLayout navTabs=new LinearLayout(this);
  navTabs.setOrientation(landscape?LinearLayout.VERTICAL:LinearLayout.HORIZONTAL);
  navTabs.setPadding(dp(4),dp(4),dp(4),dp(4));
  nav.addView(navTabs,new FrameLayout.LayoutParams(-1,landscape?-1:-2));
  String[] labels={"Запись","","Настройки","Библиотека"};
  for(int index:new int[]{0,LIBRARY_PAGE,SETTINGS_PAGE}){
   int pageIndex=index;
   Button tab=button(labels[index],()->showPage(pageIndex));
   if(index==LIBRARY_PAGE)tab.setContentDescription("Библиотека");
   if(index==SETTINGS_PAGE)tab.setContentDescription("Настройки");
   StudioStyle.fitLabel(tab,10,14);
   tab.setPadding(dp(2),dp(3),dp(2),dp(3));
   LinearLayout.LayoutParams lp=landscape?new LinearLayout.LayoutParams(-1,0,1):new LinearLayout.LayoutParams(0,dp(54),1);
   tab.setBackground(StudioStyle.control(this,Color.TRANSPARENT,12));
   navTabs.addView(tab,lp);
   tabs[index]=tab;
  }
  navTabs.addOnLayoutChangeListener((view,left,top,right,bottom,oldLeft,oldTop,oldRight,oldBottom)->positionNavSelection(false));
  LinearLayout.LayoutParams navigation=landscape?new LinearLayout.LayoutParams(railWidth(),-1):new LinearLayout.LayoutParams(-1,-2);
  if(landscape){
   navigation.setMargins(dp(8),dp(8),0,dp(8));
   root.addView(nav,0,navigation);
  }else{
   navigation.setMargins(dp(10),0,dp(10),dp(6));
   root.addView(nav,navigation);
  }
  if(saved!=null)pageShown=true;
  showPage(Math.max(0,Math.min(pages.length-1,selectedPage)));
  if(saved==null){
   StudioStyle.enter(nav,true);
   StudioStyle.enter(pages[selectedPage],true);
  }
  if(Build.VERSION.SDK_INT>=33){
   android.window.OnBackInvokedCallback callback=()->{
    if(!handleBack()&&(!isTaskRoot()||!moveTaskToBack(false)))finish();
   };
   getOnBackInvokedDispatcher().registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT,callback);
   systemBackCallback=callback;
  }
 }
 private int railWidth(){
  android.graphics.Paint paint=new android.graphics.Paint(tabs[LIBRARY_PAGE].getPaint());
  paint.setTextSize(android.util.TypedValue.applyDimension(android.util.TypedValue.COMPLEX_UNIT_SP,14,getResources().getDisplayMetrics()));
  int width=dp(82);
  for(Button tab:tabs)if(tab!=null)width=Math.max(width,(int)Math.ceil(paint.measureText(tab.getText().toString()))+dp(20));
  return width;
 }
 private LinearLayout.LayoutParams spaced(int gap) {
  LinearLayout.LayoutParams size=new LinearLayout.LayoutParams(-1,-2);
  size.topMargin=dp(gap);
  return size;
 }
 private void buildRecorder(LinearLayout page) {
  LinearLayout masthead=new LinearLayout(this);
  masthead.setGravity(Gravity.CENTER_VERTICAL);
  ImageView mark=new ImageView(this);
  mark.setImageResource(R.mipmap.launcher_icon);
  mark.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
  masthead.addView(mark,new LinearLayout.LayoutParams(dp(34),dp(34)));
  TextView brand=heading("На полях",20);
  LinearLayout.LayoutParams brandSize=new LinearLayout.LayoutParams(0,-2,1);
  brandSize.setMarginStart(dp(8));
  masthead.addView(brand,brandSize);
  String today=java.time.LocalDate.now().format(java.time.format.DateTimeFormatter.ofPattern("d MMMM",new Locale("ru")));
  masthead.addView(note(today));
  page.addView(masthead);
  View rule=new View(this);
  rule.setBackgroundColor(line);
  LinearLayout.LayoutParams ruleSize=new LinearLayout.LayoutParams(-1,dp(1));
  ruleSize.topMargin=dp(10);
  page.addView(rule,ruleSize);

  recordTitle=StudioStyle.title(this,"Новая запись");
  recordTitle.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  page.addView(recordTitle,spaced(landscape?8:20));
  receiptDetails=note("");
  receiptDetails.setVisibility(View.GONE);
  page.addView(receiptDetails);

  LinearLayout recorderArea=page,controls=page;
  boolean split=landscape&&getResources().getConfiguration().screenWidthDp>=640;
  if(split){
   LinearLayout columns=new LinearLayout(this);
   page.addView(columns,spaced(8));
   recorderArea=column();
   controls=column();
   columns.addView(recorderArea,new LinearLayout.LayoutParams(0,-2,1.12f));
   LinearLayout.LayoutParams side=new LinearLayout.LayoutParams(0,-2,1);
   side.setMarginStart(dp(14));
   columns.addView(controls,side);
  }
  LinearLayout hero=column();
  hero.setPadding(dp(20),dp(16),dp(20),dp(16));
  hero.setBackground(StudioStyle.surface(this,StudioStyle.RECORDER,18));
  recorderArea.addView(hero,spaced(split?0:12));
  recordState=text("Длительность",14);
  recordState.setTextColor(StudioStyle.MINT);
  recordState.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
  hero.addView(recordState);
  duration=text("00:00",62);
  duration.setTypeface(Typeface.create("sans-serif-light",Typeface.NORMAL));
  duration.setTextColor(StudioStyle.RECORDER_TEXT);
  duration.setFontFeatureSettings("tnum");
  duration.setLetterSpacing(-.025f);
  duration.setIncludeFontPadding(false);
  duration.setSingleLine(true);
  duration.setAutoSizeTextTypeUniformWithConfiguration(30,66,2,android.util.TypedValue.COMPLEX_UNIT_SP);
  duration.setPadding(0,0,0,0);
  duration.setContentDescription("Длительность записи 00:00");
  hero.addView(duration,new LinearLayout.LayoutParams(-1,dp(landscape?68:80)));
  meter=new RecordingMeter(this);
  hero.addView(meter,new LinearLayout.LayoutParams(-1,dp(26)));
  recordAction=button("Начать запись",this::recorderAction,true);
  recordAction.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);
  recordAction.setPadding(dp(18),dp(8),dp(18),dp(8));
  recordAction.setMinHeight(dp(54));
  recordAction.setMinimumHeight(dp(54));
  recordAction.setTextSize(17);
  hero.addView(recordAction,spaced(12));

  TextView sourceLabel=heading("Источник звука",16);
  controls.addView(sourceLabel,spaced(split?0:14));
  SharedPreferences settings=getSharedPreferences("settings",0);
  if("wifi".equals(settings.getString("transport",""))||"wifi".equals(settings.getString(SOURCE_MODE,""))
      ||(!settings.getString("ip","").isEmpty()&&!settings.getString("token","").isEmpty())){
   sources.add(new ChoiceDropdown.Option("wifi","ClipMic по Wi-Fi","Сохранённое подключение"));
  }
  transport=new ChoiceDropdown(this,"Источник звука","Нет доступных источников",()->sources,option->{
   SharedPreferences.Editor editor=settings.edit().putString(SOURCE_MODE,option.value);
   if("ble".equals(option.value)||"wifi".equals(option.value))editor.putString("transport",option.value);
   editor.apply();
   stopPresenceCheck();
   presenceSource="";
   captureProblem="";
   refreshConnection();
   renderRecorder(CaptureService.recording);
  });
  transport.setSelected(selectedSource());
  controls.addView(transport.button,spaced(2));
  controls.addView(transport.list,spaced(4));
  addSourceStatus(controls);
  recordImport=button("Импортировать аудио",()->{
   if(CaptureService.recording){takeBoardPhoto();return;}
   if(startPendingUntil!=0||lessonFlow.savingDirect())return;
   if(!receiptFile.isEmpty()){
    String file=receiptFile;
    if(receiptPending&&!lessonFlow.hasLessonChoice(file))lessonFlow.keepWithoutLesson(file,()->{
     if(resumed&&selectedPage==0&&file.equals(receiptFile))prepareNextRecording();
    });
    else prepareNextRecording();
   }else if(!AudioImport.busy)chooseAudio();
  });
  recordImport.setGravity(Gravity.START|Gravity.CENTER_VERTICAL);
  recordImport.setPadding(dp(10),dp(6),dp(10),dp(6));
  recordImport.setCompoundDrawablePadding(dp(12));
  StudioStyle.actionTone(recordImport,Color.TRANSPARENT,accent);
  controls.addView(recordImport,spaced(10));
  pendingLesson=button("Указать предмет",()->{
   if(!receiptFile.isEmpty()&&receiptPending)lessonFlow.openPending(receiptFile);
   else lessonFlow.openPending();
  });
  pendingLesson.setVisibility(View.GONE);
  controls.addView(pendingLesson,spaced(6));
  recentRecording=button("Последняя запись",()->openRecording(lastSavedRecording));
  recentRecording.setVisibility(View.GONE);
  controls.addView(recentRecording,spaced(6));
  updateRecent();
 }
 private void prepareNextRecording(){
  receiptFile="";
  captureProblem="";
  refreshConnection();
  renderRecorder(false);
 }
 private void updateRecent() {
  boolean exists=LectureNotes.valid(lastSavedRecording)&&(Store.audio(this,lastSavedRecording).isFile()
      ||LectureNotes.file(this,lastSavedRecording,true).isFile()||LectureNotes.file(this,lastSavedRecording,false).isFile());
  recentRecording.setTag(exists);
  if(exists)recentRecording.setText("Последняя запись · "+Store.recordingTitle(this,lastSavedRecording));
 }
 private void recorderAction() {
  long now=SystemClock.elapsedRealtime();
  if(now<captureTapUntil||startPendingUntil!=0||stoppingRecording||lessonFlow.savingDirect()
      ||recordingActionShown!=CaptureService.recording)return;
  captureTapUntil=now+ViewConfiguration.getDoubleTapTimeout();
  if(!recordingActionShown&&!receiptFile.isEmpty()){
   String file=receiptFile;
   if(!receiptPending)openRecording(file);
   else if(lessonFlow.hasLessonChoice(file))lessonFlow.openPending(file);
   else lessonFlow.keepWithoutLesson(file,()->{if(resumed&&selectedPage==0&&file.equals(receiptFile))openRecording(file);});
   renderRecorder(false);
   return;
  }
  if(!recordingActionShown){begin();return;}
  try {
   startForegroundService(CaptureService.command(this,"STOP"));
   stoppingRecording=true;
   renderRecorder(true);
   requestCaptureRefresh();
  }catch(RuntimeException error){
   captureProblem="Не удалось остановить запись. Повтори попытку.";
   renderRecorder(true);
  }
 }
 private void renderRecorder(boolean active) {
  CaptureMode mode=active?(stoppingRecording?CaptureMode.STOPPING:CaptureMode.LIVE)
      :startPendingUntil!=0?CaptureMode.STARTING:receiptFile.isEmpty()?CaptureMode.READY:CaptureMode.SAVED;
  boolean saved=mode==CaptureMode.SAVED;
  boolean ready=mode==CaptureMode.READY;
  boolean live=mode==CaptureMode.LIVE;
  boolean choosing=saved&&receiptPending&&lessonFlow.hasLessonChoice(receiptFile);
  boolean saving=lessonFlow.savingDirect();
  ChoiceDropdown.Option source=selectedSource();
  boolean local="auto".equals(source.value)||"phone".equals(source.value);
  boolean permission=ready&&local&&microphonePermissionDenied();
  String title=saved?"Запись сохранена":active?"Идёт запись":"Новая запись";
  if(!title.contentEquals(recordTitle.getText()))recordTitle.setText(title);
  String label="Длительность";
  int tone=StudioStyle.MINT;
  if(!captureProblem.isEmpty()){label=captureProblem;tone=StudioStyle.ON_AIR;}
  else if(permission){label="Для записи нужен доступ к микрофону";tone=StudioStyle.ON_AIR;}
  else if(mode==CaptureMode.STARTING)label="Включаю микрофон…";
  else if(mode==CaptureMode.STOPPING||saving)label="Сохраняю…";
  else if(saved)label="На телефоне";
  else if(live&&CaptureService.link==CaptureService.Link.ERROR){label="Связь прервалась. Подключаюсь снова…";tone=StudioStyle.ON_AIR;}
  setRecordState(label,tone);
  String time=saved?receiptTime:active?LectureReaderActivity.clock(CaptureService.samples/16000.0):"00:00";
  if(!time.contentEquals(duration.getText())){
   duration.setText(time);
   duration.setContentDescription("Длительность записи "+time);
  }
  receiptDetails.setVisibility(saved?View.VISIBLE:View.GONE);
  String action=permission?(microphoneNeedsSettings()?"Открыть настройки":"Разрешить микрофон")
      :saved?(choosing?"Выбрать пару":"Открыть запись"):live?"Завершить запись"
      :mode==CaptureMode.STOPPING?"Сохраняю…":"Начать запись";
  if(!action.contentEquals(recordAction.getText()))recordAction.setText(action);
  recordAction.setEnabled(!saving&&(live||saved||ready&&firmwareQuery==null));
  if(paintedMode!=mode){
   StudioStyle.actionTone(recordAction,active?StudioStyle.ON_AIR:StudioStyle.MINT,StudioStyle.RECORDER);
   int secondaryIcon=saved?R.drawable.action_new:active?R.drawable.action_photo:R.drawable.action_import;
   recordImport.setCompoundDrawablesRelativeWithIntrinsicBounds(secondaryIcon,0,R.drawable.action_next,0);
   if(saved)recordAction.setCompoundDrawablesRelative(null,null,null,null);
   else StudioStyle.recordIcon(recordAction,active,paintedMode!=null&&resumed&&selectedPage==0);
   if(paintedMode!=null&&selectedPage==0&&resumed)StudioStyle.changeAction(recordAction);
   paintedMode=mode;
  }
  meter.setRecording(active&&selectedPage==0);
  transport.setEnabled(ready);
  transport.button.setVisibility(ready||mode==CaptureMode.STARTING?View.VISIBLE:View.GONE);
  String autoInput=getSharedPreferences("settings",0).getString("ble_address","").isEmpty()
      ?"Авто · телефон или гарнитура":"Авто · ClipMic или телефон";
  transport.setCollapsedTitle("auto".equals(source.value)?autoInput:null);
  if(saved)showConnection(CaptureService.Link.CONNECTED,receiptSource);
  signal.setVisibility(active||saved||!local?View.VISIBLE:View.GONE);
  String other=saved?"Новая запись":active?"Сфотографировать доску":"Импортировать аудио";
  if(!other.contentEquals(recordImport.getText()))recordImport.setText(other);
  recordImport.setEnabled(!saving&&(live||saved||ready&&!AudioImport.busy));
  String pending=saved?"Указать предмет":"Выбрать пару для отложенной записи";
  if(!pending.contentEquals(pendingLesson.getText()))pendingLesson.setText(pending);
  pendingLesson.setVisibility(!saving&&(saved&&receiptPending&&!choosing||ready&&lessonFlow.hasPending())?View.VISIBLE:View.GONE);
  recentRecording.setVisibility(ready&&Boolean.TRUE.equals(recentRecording.getTag())?View.VISIBLE:View.GONE);
 }
 private TextView firmwareStatus,macStatus,updateStatus;
 private Button firmwareButton,connectMac,installUpdate,profileAction,githubCheck,githubDisconnect;
 private Thread firmwareQuery;
 private String pendingPhoto;
 private String exportFile;
 private RecordingExport.Kind exportKind;
 private static final int EXPORT_DOCUMENT=11;
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
  String source=selectedSource().value;
  if("auto".equals(source)||"phone".equals(source)){
   if(checkSelfPermission(MICROPHONE_PERMISSION)!=0){
    if(microphoneNeedsSettings()){
     Intent settings=new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
       android.net.Uri.fromParts("package",getPackageName(),null));
     startActivity(settings);
    }else requestPermissions(new String[]{MICROPHONE_PERMISSION},8);
    return;
   }
   startCapture("auto".equals(source)?"START_AUTO":"START_PHONE");
   return;
  }
  android.content.SharedPreferences settings=getSharedPreferences("settings",0);
  boolean bonded=EspDeviceConnection.BONDED.equals(settings.getString(EspDeviceConnection.PAIRING_MODE,""));
  if(!bonded&&settings.getString("token","").isEmpty()){
   setDeviceExpanded(true);openDevicePairing();return;
  }
  if("ble".equals(source)){
   String[] permissions=Build.VERSION.SDK_INT>=31?new String[]{"android.permission.BLUETOOTH_SCAN","android.permission.BLUETOOTH_CONNECT"}:new String[]{"android.permission.ACCESS_FINE_LOCATION"};
   for(String p:permissions)if(checkSelfPermission(p)!=0){requestPermissions(permissions,3);return;}
   BluetoothAdapter a=getSystemService(BluetoothManager.class).getAdapter();if(a==null){Toast.makeText(this,"На телефоне нет Bluetooth",1).show();return;}if(!a.isEnabled()){startActivityForResult(new Intent(BluetoothAdapter.ACTION_REQUEST_ENABLE),4);return;}
   String address=settings.getString("ble_address","");
   if(bonded&&(!BluetoothAdapter.checkBluetoothAddress(address)||a.getRemoteDevice(address).getBondState()!=BluetoothDevice.BOND_BONDED)){
    setDeviceExpanded(true);openDevicePairing();return;
   }
  }
  startCapture("START");
 }
 private void startCapture(String command){
  if(startPendingUntil!=0||CaptureService.recording)return;
  long now=SystemClock.elapsedRealtime();
  try{
   startForegroundService(CaptureService.command(this,command));
   startPendingUntil=now+2500;
   captureTapUntil=now+ViewConfiguration.getDoubleTapTimeout();
   recordAction.setEnabled(false);
   captureProblem="";
   renderRecorder(false);
   requestCaptureRefresh();
  }catch(RuntimeException error){
   captureProblem="Не удалось начать запись. Повтори попытку.";
   renderRecorder(false);
  }
 }
 @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] grant){super.onRequestPermissionsResult(code,permissions,grant);if(code==EspPairing.BLUETOOTH_PERMISSION){if(devicePairing!=null)devicePairing.permissionResult(grant);return;}if(code==9){for(int result:grant)if(result!=0)return;if(grant.length>0)checkFirmware();return;}if(code==8){
  if(grant.length==0)return;
  getPreferences(MODE_PRIVATE).edit().putBoolean(MICROPHONE_ASKED,true).apply();
  if(grant[0]==android.content.pm.PackageManager.PERMISSION_GRANTED)begin();
  else requestCaptureRefresh();
  return;
 }if(code==5&&grant.length>0){for(int g:grant)if(g!=0){startForegroundService(CaptureService.command(this,"SYNC"));return;}transfer();}if(code==3&&grant.length>0){for(int g:grant)if(g!=0)return;begin();}}
 private void exportRecording(String file,RecordingExport.Kind kind){
  if(exportKind!=null||!LectureNotes.valid(file))return;
  exportFile=file;
  exportKind=kind;
  try{
   startActivityForResult(RecordingExport.picker(this,file,kind),EXPORT_DOCUMENT);
  }catch(RuntimeException error){
   exportFile=null;
   exportKind=null;
   Toast.makeText(this,"Не удалось открыть системный выбор файла",Toast.LENGTH_LONG).show();
  }
 }
 private void finishExport(int result,Intent data){
  String file=exportFile;
  RecordingExport.Kind kind=exportKind;
  exportFile=null;
  exportKind=null;
  if(result!=RESULT_OK||data==null||data.getData()==null||kind==null||!LectureNotes.valid(file))return;
  android.net.Uri destination=data.getData();
  Context application=getApplicationContext();
  new Thread(()->{
   String resultMessage;
   try{
    RecordingExport.write(application,file,kind,destination);
    resultMessage="Файл сохранён";
   }catch(Exception error){
    resultMessage="Не удалось сохранить файл. Можно повторить экспорт.";
   }
   String message=resultMessage;
   runOnUiThread(()->Toast.makeText(application,message,Toast.LENGTH_LONG).show());
  },"Lecture export").start();
 }
 @Override protected void onActivityResult(int code,int result,Intent data){super.onActivityResult(code,result,data);if(code==READ_FROM_LIBRARY){
  if(result==RESULT_OK&&data!=null&&LectureNotes.valid(data.getStringExtra("audio")))openRecording(data.getStringExtra("audio"));
  return;
 }if(code==EXPORT_DOCUMENT){finishExport(result,data);return;}if(code==EspPairing.ENABLE_BLUETOOTH){if(devicePairing!=null)devicePairing.bluetoothEnableResult(result);return;}if(code==7&&result==RESULT_OK&&data!=null&&data.getData()!=null){android.net.Uri uri=data.getData();try{getContentResolver().takePersistableUriPermission(uri,data.getFlags()&Intent.FLAG_GRANT_READ_URI_PERMISSION);}catch(Exception ignored){}AudioImport.start(this,uri);showPage(LIBRARY_PAGE);return;}if(code==4&&result==RESULT_OK)begin();if(code==6&&result==RESULT_OK){final String id=pendingPhoto;pendingPhoto=null;new Thread(()->{try{BoardPhotos.markReady(this,id);BoardPhotos.finish(this,id);runOnUiThread(()->{Toast.makeText(this,"Фото сохранено · будет перенесено и разобрано на Mac",1).show();transfer();});}catch(Exception e){runOnUiThread(()->Toast.makeText(this,e.getMessage(),1).show());}},"Save board photo").start();}else if(code==6){BoardPhotos.cancel(this,pendingPhoto);pendingPhoto=null;}}
 @Override protected void onSaveInstanceState(Bundle out){super.onSaveInstanceState(out);out.putString("pending_photo",pendingPhoto);out.putInt("page",selectedPage);out.putBundle("audio_page",audioPage.snapshot());out.putBoolean("device_expanded",deviceExpanded);out.putInt("device_charge",deviceCharge);out.putFloat("device_rotation",deviceModel.rotation());out.putBoolean("stopping_recording",stoppingRecording);out.putBoolean("capture_observed",recordingActionShown);out.putString("receipt_file",receiptFile);out.putString("library_query",libraryPage.queryText());out.putBoolean("library_waiting",libraryPage.waitingOnly());out.putBoolean("library_favorites",libraryPage.favoritesOnly());if(exportKind!=null){out.putString("export_file",exportFile);out.putString("export_kind",exportKind.name());}}
 private void showSavedRecording(String file){
  lastSavedRecording=file;
  updateRecent();
  getPreferences(MODE_PRIVATE).edit().putString("last_saved_recording",file).apply();
  presentReceipt(file);
  renderRecorder(CaptureService.recording);
  if(selectedPage==LIBRARY_PAGE){
   libraryPage.showOutcome("Запись сохранена",()->openRecording(file));
   refreshLibrary();
  }
 }
 private void presentReceipt(String name){
  if(!LectureNotes.valid(name))return;
  java.io.File audio=Store.audio(this,name);
  if(!audio.isFile())return;
  receiptFile=name;
  receiptTime=LectureReaderActivity.clock(Math.max(0L,audio.length()-44)/32000.0);
  receiptDetails.setText(Store.recordingTitle(this,name));
  receiptPending=false;
  receiptSource="";
  try{
   org.json.JSONObject metadata=Store.readObject(new java.io.File(audio.getPath()+".json"));
   receiptPending=metadata.optBoolean("awaiting_lesson");
   org.json.JSONArray routes=metadata.optJSONArray("input_routes");
   if(routes!=null&&routes.length()>0)receiptSource=routes.getJSONObject(routes.length()-1).optString("label");
   if(receiptSource.isEmpty()&&metadata.optBoolean("imported"))receiptSource="Импортированный файл";
  }catch(Exception ignored){}
  if(receiptPending&&!lessonFlow.hasLessonChoice(name))receiptDetails.append(" · Без пары");
  if(receiptSource.isEmpty()&&name.equals(CaptureService.current))receiptSource=CaptureService.inputLabel;
  if(receiptSource.isEmpty())receiptSource="Не указан";
 }
 private static final int READ_FROM_LIBRARY=12;
 private void openLibraryRecording(String file){
  boolean local=LectureNotes.file(this,file,true).isFile();
  if(!local&&!LectureNotes.file(this,file,false).isFile()){openRecording(file);return;}
  Intent reader=new Intent(this,LectureReaderActivity.class).putExtra("file",file+".json")
      .putExtra("local",local).putExtra("from_library",true).putExtra("tab","read");
  startActivityForResult(reader,READ_FROM_LIBRARY);
 }
 private void openRecording(String file){
  audioPage.openRecording(file);
  showPage(AUDIO_PAGE);
 }
 private void showDiscardedRecording(){
  if(!receiptFile.isEmpty()&&!Store.audio(this,receiptFile).isFile())receiptFile="";
  captureProblem="Запись удалена";
  renderRecorder(CaptureService.recording);
  if(selectedPage==LIBRARY_PAGE){
   libraryPage.showOutcome("Запись отменена",null);
   refreshLibrary();
  }
 }
 private void takeBoardPhoto(){try{pendingPhoto=BoardPhotos.prepare(this);android.net.Uri uri=android.net.Uri.parse("content://"+getPackageName()+".photos/"+pendingPhoto+".jpg");Intent camera=new Intent(android.provider.MediaStore.ACTION_IMAGE_CAPTURE);camera.putExtra(android.provider.MediaStore.EXTRA_OUTPUT,uri);camera.setClipData(ClipData.newRawUri("Фото доски",uri));camera.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_READ_URI_PERMISSION);startActivityForResult(camera,6);}catch(Exception e){Toast.makeText(this,"Не удалось открыть камеру: "+e.getMessage(),1).show();}}
 private void chooseAudio(){
  Intent pick=new Intent(Intent.ACTION_OPEN_DOCUMENT).setType("audio/*").addCategory(Intent.CATEGORY_OPENABLE)
   .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
  startActivityForResult(pick,7);
 }
 private void addSourceStatus(LinearLayout panel){
  signal=new LinearLayout(this);
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

 }
 private void addConnectionPanel(LinearLayout panel){
  LinearLayout row=new LinearLayout(this);
  deviceToggle=row;
  row.setGravity(Gravity.CENTER_VERTICAL);
  row.setMinimumHeight(dp(48));
  row.setFocusable(true);
  row.setBackground(new android.graphics.drawable.RippleDrawable(
   android.content.res.ColorStateList.valueOf(0x22ffffff),null,surface(Color.WHITE,12)));
  row.setOnClickListener(view->toggleDevicePanel());
  row.addView(heading("Диктофон ClipMic",14),new LinearLayout.LayoutParams(0,-2,1));
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
   android.content.res.ColorStateList.valueOf(0x2680e2ce),tile,null));
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
  return (deviceExpanded?"Свернуть":"Раскрыть")+" настройки диктофона ClipMic";
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
  if(StudioStyle.motion(deviceChevron))deviceChevron.animate().rotation(rotation).setDuration(180).start();
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
  if(width<=0||!StudioStyle.motion(deviceReveal)){
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
   SharedPreferences settings=getSharedPreferences("settings",0);
   if(!"ble".equals(selectedSource().value))settings.edit().putString(SOURCE_MODE,"auto").apply();
   transport.setSelected(selectedSource());
   presenceSource=selectedSource().value;
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
  String source=selectedSource().value;
  boolean local=source.equals("phone")||source.equals("auto");
  if(CaptureService.recording){
   lastRecording=true;
   stopPresenceCheck();
   CaptureService.Link link=CaptureService.link;
   AudioManager audio=getSystemService(AudioManager.class);
   if("phone".equals(CaptureService.linkSource)&&audio!=null&&audio.isMicrophoneMute()){
    showConnection(CaptureService.Link.ERROR,"Микрофон выключен в Android");
   }else if(link==CaptureService.Link.CONNECTED&&!CaptureService.inputLabel.isEmpty()){
    showConnection(link,CaptureService.inputLabel);
   }else{
    showConnection(link,CaptureService.status);
   }
   return;
  }
  if(lastRecording||!source.equals(presenceSource)){
   lastRecording=false;
   stopPresenceCheck();
   presenceSource=source;
   idleLink=CaptureService.Link.OFF;
   presenceError="";
  }
  if(local){
   if(microphonePermissionDenied()){
    paintConnection(CaptureService.Link.ERROR,true,"Нет доступа к микрофону");
   }else if(CaptureService.link==CaptureService.Link.ERROR&&("phone".equals(CaptureService.linkSource)||"auto".equals(CaptureService.linkSource))){
    paintConnection(CaptureService.Link.ERROR,true,CaptureService.status);
   }else{
    boolean clipMic="auto".equals(source)&&!getSharedPreferences("settings",0).getString("ble_address","").isEmpty();
    showConnection(CaptureService.Link.OFF,clipMic?"Сначала ClipMic рядом, затем гарнитура или телефон":"Гарнитура с микрофоном или сам телефон");
   }
   return;
  }
  if("wifi".equals(source)){
   showConnection(CaptureService.Link.OFF,"Сохранённое подключение по Wi-Fi");
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
   default:message=phone?"Микрофон выключен":"ESP не на связи";break;
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
 private ChoiceDropdown.Option selectedSource(){
  String saved=getSharedPreferences("settings",0).getString(SOURCE_MODE,"auto");
  for(ChoiceDropdown.Option source:sources)if(source.value.equals(saved))return source;
  return sources.get(0);
 }
 private boolean microphonePermissionDenied(){
  return checkSelfPermission(MICROPHONE_PERMISSION)!=android.content.pm.PackageManager.PERMISSION_GRANTED
    &&getPreferences(MODE_PRIVATE).getBoolean(MICROPHONE_ASKED,false);
 }
 private boolean microphoneNeedsSettings(){
  return microphonePermissionDenied()&&!shouldShowRequestPermissionRationale(MICROPHONE_PERMISSION);
 }
 private void setRecordState(String value,int color){
  if(!value.contentEquals(recordState.getText()))recordState.setText(value);
  if(recordState.getCurrentTextColor()!=color)recordState.setTextColor(color);
 }
 private void refreshLibrary(){
  libraryPage.refresh();
  nextLibraryRefresh=SystemClock.elapsedRealtime()+1500;
 }
 private void requestCaptureRefresh(){
  timer.removeCallbacks(refreshTask);
  timer.postDelayed(refreshTask,80);
 }
 private void refresh(){
  boolean active=CaptureService.recording;
  if(active)startPendingUntil=0;
  else if(startPendingUntil!=0&&SystemClock.elapsedRealtime()>=startPendingUntil){
   startPendingUntil=0;
   String error=CaptureService.link==CaptureService.Link.ERROR?CaptureService.status:"";
   captureProblem=error.isEmpty()?"Не удалось начать запись. Повтори попытку.":error;
  }
  if(!active)stoppingRecording=false;
  else if("Сохраняю запись…".equals(CaptureService.status))stoppingRecording=true;
  if(selectedPage==0&&(active||receiptFile.isEmpty()))refreshConnection();
  boolean pairingAvailable=!active&&firmwareQuery==null&&devicePairing==null;
  addDevice.setEnabled(pairingAvailable);
  reconnectDevice.setEnabled(pairingAvailable);
  firmwareButton.setEnabled(!active&&firmwareQuery==null);
  if(!active&&recordingActionShown){
   presentReceipt(CaptureService.current.isEmpty()?Store.pendingLesson(this):CaptureService.current);
   if(CaptureService.link==CaptureService.Link.ERROR||receiptFile.isEmpty())captureProblem=CaptureService.status;
  }
  if(active&&!recordingActionShown){receiptFile="";captureProblem="";}
  recordingActionShown=active;
  lessonFlow.refresh(active);
  renderRecorder(active);
  GitHubUpdates.whenOpen(this);
  if(selectedPage==SETTINGS_PAGE)refreshSyncSettings(active);
  String profile=lessonFlow.profileLabel();
  if(!profile.contentEquals(mireaProfileStatus.getText()))mireaProfileStatus.setText(profile);
  profileAction.setEnabled(!active);
  if(selectedPage==LIBRARY_PAGE&&SystemClock.elapsedRealtime()>=nextLibraryRefresh)refreshLibrary();
  timer.postDelayed(refreshTask,startPendingUntil!=0||stoppingRecording?100:500);
 }
 private void refreshSyncSettings(boolean recording){
  boolean paired=CaptureService.paired(this);
  String macName=getSharedPreferences("settings",0).getString("paired_mac","").trim();
  String connection="Mac не подключён. Записи остаются на телефоне.";
  String action="Подключить Mac";
  if(paired){
   connection=macName.isEmpty()?"Mac сопряжён":"Сопряжён с «"+macName+"»";
   action="Сменить Mac";
  }
  if(!connection.contentEquals(macStatus.getText()))macStatus.setText(connection);
  if(!action.contentEquals(connectMac.getText()))connectMac.setText(action);
  connectMac.setEnabled(!recording);
  boolean available=AppUpdates.ready(this);
  boolean signedIn=GitHubUpdates.signedIn(this);
  boolean authorizing=GitHubUpdates.authorizing();
  String label=authorizing?"Показать код GitHub":signedIn?"Проверить GitHub":"Получать обновления без Mac";
  if(!label.contentEquals(githubCheck.getText()))githubCheck.setText(label);
  boolean idle=!recording&&!PhoneAnalysisService.busy();
  githubCheck.setEnabled(idle&&(!GitHubUpdates.busy()||authorizing));
  githubDisconnect.setVisibility(signedIn?View.VISIBLE:View.GONE);
  githubDisconnect.setEnabled(idle&&!GitHubUpdates.busy());
  String direct=GitHubUpdates.status();
  String message=available||direct.isEmpty()?AppUpdates.message(this,available):direct;
  if(available&&GitHubUpdates.busy()&&!direct.isEmpty())message+=" "+direct;
  if(!message.contentEquals(updateStatus.getText()))updateStatus.setText(message);
  installUpdate.setVisibility(available?View.VISIBLE:View.GONE);
  installUpdate.setEnabled(idle);
 }
 @Override protected void onStart(){super.onStart();CaptureService.screenStarted();}
 @Override public void onResume(){super.onResume();resumed=true;lessonFlow.onResume();audioPage.setActive(selectedPage==AUDIO_PAGE);timer.removeCallbacksAndMessages(null);CaptureService.resumeSync(this);refresh();}
 @Override public void onPause(){resumed=false;stopPresenceCheck();transport.close();audioPage.setActive(false);timer.removeCallbacksAndMessages(null);super.onPause();}
 @Override protected void onStop(){CaptureService.screenStopped();super.onStop();}
 private boolean handleBack(){
  if(selectedPage==AUDIO_PAGE){
   if(!audioPage.exitReview())showPage(LIBRARY_PAGE);
   return true;
  }
  if(selectedPage==SETTINGS_PAGE&&deviceExpanded){setDeviceExpanded(false);return true;}
  if(selectedPage!=0){
   showPage(0);
   return true;
  }
  if(transport.close())return true;
  return false;
 }
 @Override public void onBackPressed(){
  if(!handleBack())super.onBackPressed();
 }
 @Override public void onDestroy(){
  if(Build.VERSION.SDK_INT>=33&&systemBackCallback!=null)
   getOnBackInvokedDispatcher().unregisterOnBackInvokedCallback((android.window.OnBackInvokedCallback)systemBackCallback);
  lessonFlow.dispose();
  audioPage.dispose();
  libraryPage.dispose();
  if(deviceExpansion!=null)deviceExpansion.cancel();
  if(devicePairing!=null)devicePairing.close();
  if(firmwareQuery!=null)firmwareQuery.interrupt();
  if(pairing!=null)pairing.cancel();
  super.onDestroy();
 }
}
