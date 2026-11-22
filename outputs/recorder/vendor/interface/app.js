/* Organize existing controls without changing recording or analysis state. */
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
 header.className='app-header';
 intro.hidden=true;
 const nav=create('nav','app-nav');nav.setAttribute('aria-label','Разделы приложения');
 const brand=create('div','brand','Пары');nav.append(brand);
 const views={};const buttons={};
 const navIcons={record:'<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>',library:'<path d="M5 4h14v16H5zM8 8h8M8 12h8M8 16h5"/>',settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>'};
 const options=[['record','Запись','Микрофон и контроль звука'],['library','Библиотека','Темы и краткие конспекты'],['settings','Настройки','Подключение и разбор']];
 for(const [id,title,hint] of options){
  const button=create('button','nav-button');button.type='button';const icon=document.createElementNS('http://www.w3.org/2000/svg','svg');icon.setAttribute('viewBox','0 0 24 24');icon.setAttribute('class','nav-icon');icon.setAttribute('aria-hidden','true');icon.innerHTML=navIcons[id];button.append(icon,create('span','',title),create('small','',hint));button.setAttribute('aria-controls','view-'+id);
  const view=create('section','app-view');view.id='view-'+id;view.setAttribute('aria-label',title);views[id]=view;buttons[id]=button;nav.append(button);main.append(view);
  button.onclick=()=>show(id);
 }
 const navFoot=create('div','nav-foot','Аудио остаётся на этом Mac');nav.append(navFoot);document.body.prepend(nav);
 function show(id,refresh=true){
  for(const key of Object.keys(views)){views[key].hidden=key!==id;buttons[key].setAttribute('aria-current',key===id?'page':'false')}
  document.body.dataset.view=id;
  try{localStorage.setItem('lecture-view',id)}catch{}
  main.scrollIntoView({block:'start'});if(refresh)update();
 }
 window.showLectureView=show;
 const heading=(view,title,description)=>{const box=create('div','view-intro');box.append(create('h2','',title),create('p','muted',description));view.append(box)};
 heading(views.record,'Новая запись','Выбери источник звука и начни запись.');
 views.record.append(recording);
 recording.classList.add('recorder-hero');livePanel.classList.remove('card');livePanel.classList.add('monitor-card');
 const previewPanel=create('details','card preview-panel');previewPanel.append(create('summary','','Расшифровка и контроль звука'),livePanel);views.record.append(previewPanel);let previousActive=null;window.syncRecordingPreview=s=>{const active=Boolean(s.recording);if(active!==previousActive){if(active)previewPanel.open=true;else if(previousActive===true)previewPanel.open=false;previousActive=active;}};
 liveLabel.lastChild.textContent='Показывать, что слышит микрофон';
 livePanel.querySelector('p').id='live-preview-caption';
 livePanel.querySelector('p').textContent='Предварительная расшифровка появится после начала записи.';
 const scheduleDetails=create('details','card schedule-card');scheduleDetails.append(create('summary','','Расписание занятий'));
 schedule.classList.remove('card');scheduleDetails.append(schedule);views.record.append(scheduleDetails);
 footnote.textContent='Можно закрыть приложение — запись продолжится. Перед отключением микрофона нажми «Завершить запись».';
 views.record.append(footnote);
 document.querySelector('#start').textContent='Начать запись';document.querySelector('#stop').textContent='Завершить запись';
 const timerCaption=create('div','timer-caption','Длительность записи');document.querySelector('#timer').before(timerCaption);
 const heroHelp=create('p','hero-help','Запись ещё не началась');recording.append(heroHelp);
 function state(){
  const text=document.querySelector('#status').textContent;
  const active=recording.dataset.recording==='true';recording.classList.toggle('is-recording',active);
  heroHelp.textContent=text.includes('Связь потеряна')?'Восстанавливаю соединение. Запись продолжается в том же файле; пропущенный звук заменяется тишиной.':active?'Аудио сохраняется. Добавляй метки и фото ниже.':text.includes('Подключаю')?'Устанавливаю соединение с микрофоном…':'Подключи ESP по USB или выбери Wi-Fi. Записи с телефона появятся в библиотеке после переноса.';
 }
 new MutationObserver(state).observe(document.querySelector('#status'),{childList:true});state();
 heading(views.library,'Конспекты занятий','Выбери пару: главные темы, выводы и то, что важно запомнить.');
 studyPanel.classList.add('search-card');studyPanel.querySelector('h2').textContent='Найти тему';
 searchInput.placeholder='Например: как найти объём по трём векторам';searchInput.setAttribute('aria-label','Поиск по содержанию лекций');searchButton.textContent='Найти';
 const searchRow=create('div','search-row');searchRow.append(searchInput,searchButton);studyPanel.querySelector('h2').after(searchRow);
 const mergeDetails=create('details','merge-tools');mergeDetails.append(create('summary','','Объединить отрывки'));
 const mergeHeading=studyPanel.querySelector('h3');
 while(mergeHeading.nextSibling)mergeDetails.append(mergeHeading.nextSibling);mergeHeading.remove();studyPanel.append(mergeDetails);
 mergeDetails.ontoggle=()=>document.body.classList.toggle('merge-mode',mergeDetails.open);
 views.library.append(studyPanel,archiveTitle,files);archiveTitle.textContent='Папки занятий';archiveTitle.className='section-title';
 heading(views.settings,'Настройки','Подключение микрофона и обработка записей.');
 connection.classList.add('settings-card');document.querySelector('#wifi-details').open=false;document.querySelector('#wifi-details>summary').textContent='Подключить микрофон по Wi-Fi';
 analysis.classList.add('settings-card');analysis.querySelector('h2').textContent='Автоматический разбор';
 for(const id of ['auto-ai','pause-ai','eco-ai']){
  const label=document.querySelector('#'+id).parentElement;label.className='setting-switch';
 }
 pauseLabel.lastChild.textContent=' Приостановить разбор';ecoLabel.lastChild.textContent=' Экономный режим';
 const help=create('p','muted','Экономный режим делает паузы между вычислениями: меньше нагрев, дольше обработка. «Приостановить» останавливает очередь, сохраняя результаты.');analysis.append(help);
 const advanced=create('details','advanced-model');advanced.append(create('summary','','Модель распознавания'));advanced.append(document.querySelector('#speech-model').parentElement);analysis.append(advanced);
 const vocabularyDetails=create('details','advanced-model');vocabularyDetails.append(create('summary','','Термины и фамилии'));vocabularyDetails.append(vocabularyBox);analysis.append(vocabularyDetails);vocabularyBox.querySelector('label').textContent='Подсказки для текущей или последней записи';document.querySelector('#save-asr-terms').classList.add('secondary');
 const refreshButton=document.querySelector('#reload-app');refreshButton.textContent='↻ Обновить';refreshButton.title='Обновить приложение без остановки записи';navFoot.replaceChildren(refreshButton);
 const refreshMessage=document.querySelector('#reload-message');intro.after(refreshMessage);
 views.settings.append(analysis,connection);
 const error=document.querySelector('#error');error.setAttribute('role','alert');error.className='global-error';intro.after(error);
 let initial='record';try{initial=localStorage.getItem('lecture-view')||initial}catch{};show(views[initial]?initial:'record',false);
})();
