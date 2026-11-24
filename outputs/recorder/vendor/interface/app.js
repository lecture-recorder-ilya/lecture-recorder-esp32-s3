(() => {
 const main=document.querySelector('main');
 const recording=document.querySelector('#timer').closest('section');
 const connection=document.querySelector('#wifi-details').closest('section');
 const schedule=document.querySelector('#current-lesson').closest('section');
 const analysis=document.querySelector('#auto-ai').closest('section');
 const files=document.querySelector('#files');
 const archiveTitle=files.previousElementSibling;
 const header=main.firstElementChild;
 const intro=header.nextElementSibling;
 const footnote=analysis.nextElementSibling;
 const create=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls;if(text)e.textContent=text;return e};
 document.body.classList.add('organized');
 header.className='app-header';header.hidden=true;
 intro.hidden=true;
 const nav=create('nav','app-nav');nav.setAttribute('aria-label','Разделы приложения');
 const brand=create('div','brand');
 const logo=document.createElement('img');logo.src='/vendor/interface/fieldnotes.svg';logo.alt='';logo.width=40;logo.height=40;
 brand.append(logo,create('span','','На полях'));nav.append(brand);
 const views={};const buttons={};
 const navIcons={record:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',library:'<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>',settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>'};
 const options=[['record','Запись'],['library','Библиотека'],['settings','Настройки']];
 for(const [id,title] of options){
  const button=create('button','nav-button');button.type='button';
  const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('class','nav-icon');icon.setAttribute('aria-hidden','true');icon.innerHTML=navIcons[id];
  button.append(icon,create('span','',title));button.setAttribute('aria-controls','view-'+id);
  const view=create('section','app-view');view.id='view-'+id;view.setAttribute('aria-label',title);views[id]=view;buttons[id]=button;nav.append(button);main.append(view);
  button.onclick=()=>show(id);
 }
 document.body.prepend(nav);
 function show(id,refresh=true){
  if(refresh||id!=='library')window.LectureWorkflow?.closeReader(false);
  if(id!=='library'&&!views.library.hidden)window.LectureWorkflow?.pauseLibrary();
  for(const key of Object.keys(views)){views[key].hidden=key!==id;buttons[key].setAttribute('aria-current',key===id?'page':'false')}
  document.body.dataset.view=id;
  try{localStorage.setItem('lecture-view',id)}catch{}
  window.scrollTo({top:0,behavior:'instant'});if(refresh)update();
 }
 window.showLectureView=show;
 const heading=(view,title,description)=>{const box=create('div','view-intro');const h=create('h1','',title);h.tabIndex=-1;box.append(h);if(description)box.append(create('p','muted',description));view.append(box)};
 heading(views.record,'Новая лекция');
 const workbench=create('section','capture-desk');
 const tabs=create('div','capture-tabs');
 tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Как добавить лекцию');
 const modes={};
 for(const [id,label] of [['file','Из файла'],['mic','С микрофона']]){
  const button=create('button','capture-tab',label);
  button.type='button';button.id='capture-tab-'+id;button.setAttribute('role','tab');
  const panel=create('div','capture-mode');panel.id='capture-'+id;panel.setAttribute('role','tabpanel');
  panel.setAttribute('aria-labelledby',button.id);button.setAttribute('aria-controls',panel.id);
  button.onclick=()=>selectMode(id);
  button.onkeydown=event=>{
   if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
   event.preventDefault();
   const next=event.key==='Home'?'file':event.key==='End'?'mic':id==='file'?'mic':'file';
   selectMode(next);modes[next].button.focus();
  };
  tabs.append(button);workbench.append(panel);modes[id]={button,panel};
 }
 function selectMode(id){
  for(const [key,{button,panel}] of Object.entries(modes)){
   button.setAttribute('aria-selected',String(key===id));button.tabIndex=key===id?0:-1;panel.hidden=key!==id;
  }
 }
 window.selectCaptureMode=selectMode;
 workbench.prepend(tabs);views.record.append(workbench);modes.mic.panel.append(recording);selectMode('file');
 recording.classList.add('recorder-hero');
 const status=document.querySelector('#status');
 status.setAttribute('role','status');
 const originalRow=status.parentElement;
 const transport=document.querySelector('#transport');
 const transportLabel=transport.closest('label');
 transportLabel.firstChild.textContent='Источник звука ';
 const timer=document.querySelector('#timer');
 const primary=document.querySelector('#start'),stop=document.querySelector('#stop');
 stop.textContent='Завершить запись';
 stop.hidden=true;
 const core=create('div','capture-core'),clock=create('div','capture-clock'),actions=create('div','capture-actions');
 clock.append(status,create('div','timer-caption','Длительность записи'),timer);
 actions.append(primary,stop);
 core.append(clock,actions);
 const meter=document.querySelector('#level'),meterLabel=meter.nextElementSibling;
 meterLabel.id='capture-level-title';
 meter.setAttribute('aria-labelledby',meterLabel.id);
 const levels=create('div','capture-level'),meterTrack=create('div','capture-meter-track');
 meterTrack.setAttribute('aria-hidden','true');
 meterTrack.append(create('span','capture-meter-fill'));
 meter.classList.add('capture-meter-native');
 levels.append(meterLabel,meterTrack,meter);
 const inputs=create('div','capture-inputs');
 const sourceStatus=create('p','muted');
 sourceStatus.id='phone-sync-status';
 sourceStatus.hidden=true;
 const wifiSettings=create('button','secondary','Настроить Wi-Fi');
 wifiSettings.type='button';
 wifiSettings.hidden=transport.value!=='wifi';
 wifiSettings.onclick=()=>{
  show('settings');
  const details=document.querySelector('#wifi-details');
  details.open=true;
  details.querySelector('summary').focus({preventScroll:true});
  details.scrollIntoView({block:'nearest'});
 };
 const usbStatus=document.querySelector('#usbstatus');
 inputs.append(transportLabel,usbStatus,wifiSettings,sourceStatus);
 const recovery=create('p','hero-help');
 recovery.hidden=true;
 originalRow.remove();
 recording.prepend(core,levels,inputs,recovery);
 const shortcuts=create('div','record-shortcuts');
 shortcuts.setAttribute('role','group');shortcuts.setAttribute('aria-label','Материалы занятия');
 modes.mic.panel.append(shortcuts);
 let wasRunning=false;
 window.syncRecordingControls=(s,focus)=>{
  const running=Boolean(s.recording||s.busy);
  if(running&&!wasRunning)selectMode('mic');
  modes.mic.button.classList.toggle('is-recording',Boolean(s.recording));wasRunning=running;
  primary.hidden=running;stop.hidden=!running;
  if((running&&focus===primary)||(!running&&focus===stop)) (running?stop:primary).focus({preventScroll:true});
  recording.classList.toggle('is-recording',Boolean(s.recording));
  const wifi=transport.value==='wifi';
  usbStatus.hidden=wifi;
  wifiSettings.hidden=!wifi||running;
  sourceStatus.hidden=!sourceStatus.textContent;
  meterTrack.style.setProperty('--signal-scale',String(Math.min(1,Math.max(0,meter.value/100))));
  const hint=s.reconnecting?'Запись продолжится в том же файле. Пропущенный звук заменяется тишиной.'
   :!running&&!wifi&&!s.usb_present?'Подключи микрофон по USB или выбери Wi‑Fi.':'';
  recovery.hidden=!hint;
  if(recovery.textContent!==hint)recovery.textContent=hint;
 };
 livePanel.classList.remove('card');livePanel.classList.add('monitor-card');
 const utilities=create('div','record-utilities');
 const previewPanel=create('details','card preview-panel');previewPanel.append(create('summary','','Расшифровка и контроль звука'),livePanel);utilities.append(previewPanel);let previousActive=null;window.syncRecordingPreview=s=>{const active=Boolean(s.recording);if(active!==previousActive){if(active)previewPanel.open=true;else if(previousActive===true)previewPanel.open=false;previousActive=active;}};
 liveLabel.lastChild.textContent='Показывать, что слышит микрофон';
 livePanel.querySelector('p').id='live-preview-caption';
 livePanel.querySelector('p').textContent='Предварительная расшифровка появится после начала записи.';
 const scheduleDetails=create('details','card schedule-card');scheduleDetails.append(create('summary','','Расписание занятий'));
 schedule.classList.remove('card');scheduleDetails.append(schedule);modes.mic.panel.append(utilities);
 footnote.textContent='Можно закрыть приложение — запись продолжится. Перед отключением микрофона нажми «Завершить запись».';
 modes.mic.panel.append(footnote);
 heading(views.library,'Библиотека');
 studyPanel.classList.add('search-card');studyPanel.querySelector('h2').textContent='Найти тему';
 searchInput.placeholder='Например: как найти объём по трём векторам';searchInput.setAttribute('aria-label','Поиск по содержанию лекций');searchButton.textContent='Найти';
 const searchRow=create('div','search-row');searchRow.append(searchInput,searchButton);studyPanel.querySelector('h2').after(searchRow);
 const mergeDetails=create('details','merge-tools');mergeDetails.append(create('summary','','Объединить отрывки'));
 const mergeHeading=studyPanel.querySelector('h3');
 while(mergeHeading.nextSibling)mergeDetails.append(mergeHeading.nextSibling);mergeHeading.remove();studyPanel.append(mergeDetails);
 mergeDetails.ontoggle=()=>document.body.classList.toggle('merge-mode',mergeDetails.open);
 const searchDetails=create('details','card library-search-tools');searchDetails.append(create('summary','','Найти фрагмент во всех лекциях'),studyPanel);
 views.library.append(searchDetails,archiveTitle,files);archiveTitle.textContent='Папки занятий';archiveTitle.className='section-title';
 heading(views.settings,'Настройки');
 connection.classList.add('settings-card');document.querySelector('#wifi-details').open=false;document.querySelector('#wifi-details>summary').textContent='Подключить микрофон по Wi-Fi';
 analysis.classList.add('settings-card');analysis.querySelector('h2').textContent='Автоматический разбор';
 for(const id of ['auto-ai','pause-ai','eco-ai']){
  const label=document.querySelector('#'+id).parentElement;label.className='setting-switch';
 }
 pauseLabel.lastChild.textContent=' Приостановить разбор';ecoLabel.lastChild.textContent=' Экономный режим';
 const help=create('p','muted','Экономный режим делает паузы между вычислениями: меньше нагрев, дольше обработка. «Приостановить» останавливает очередь, сохраняя результаты.');analysis.append(help);
 const advanced=create('details','advanced-model');advanced.append(create('summary','','Модель распознавания'));advanced.append(document.querySelector('#speech-model').parentElement);analysis.append(advanced);
 const vocabularyDetails=create('details','advanced-model');vocabularyDetails.append(create('summary','','Термины и фамилии'));vocabularyDetails.append(vocabularyBox);analysis.append(vocabularyDetails);vocabularyBox.querySelector('label').textContent='Подсказки для текущей или последней записи';document.querySelector('#save-asr-terms').classList.add('secondary');
 const refreshButton=document.querySelector('#reload-app');refreshButton.textContent='Перезагрузить интерфейс';refreshButton.title='Перезагрузить интерфейс без остановки записи';
 const refreshMessage=document.querySelector('#reload-message');intro.after(refreshMessage);
 views.settings.append(analysis,connection,scheduleDetails,refreshButton);
 const error=document.querySelector('#error');error.setAttribute('role','alert');error.className='global-error';intro.after(error);
 let initial='record';try{initial=localStorage.getItem('lecture-view')||initial}catch{};show(views[initial]?initial:'record',false);
})();
