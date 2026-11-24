(async()=>{
 const result=document.createElement('output');
 result.id='library-test';document.body.append(result);
 const assert=(condition,note)=>{if(!condition)throw Error(note)};
 const until=async(check,note)=>{
  for(let i=0;i<90;i++){if(check())return;await new Promise(done=>setTimeout(done,30))}
  throw Error(note);
 };
 try{
  if(location.search.includes('entry')){
   const fileTab=document.querySelector('#capture-tab-file'),micTab=document.querySelector('#capture-tab-mic');
   await until(()=>studyStatus&&document.querySelector('.library-catalog')?.hidden===false,'Первый статус');
   assert(!document.querySelector('dialog[open]')&&document.title==='Диктофон','Вход без профиля');
   const choose=document.querySelector('.import-choose'),form=document.querySelector('#lecture-import');
   assert(choose.getBoundingClientRect().bottom<innerHeight&&choose.getClientRects().length>0,'Импорт на первом экране без ESP');
   fileTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
   assert(document.activeElement===micTab&&!document.querySelector('#capture-mic').hidden&&document.querySelector('#start').disabled,'Запись без подключённого микрофона');
   micTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
   assert(document.activeElement===fileTab&&!document.querySelector('#capture-file').hidden,'Клавиатура источника');
   const drop=name=>{
    const data=new DataTransfer();data.items.add(new File(['test-audio'],name,{type:'audio/mp4'}));
    const event=new Event('drop',{bubbles:true,cancelable:true});
    Object.defineProperty(event,'dataTransfer',{value:data});form.querySelector('.import-drop').dispatchEvent(event);
   };
   drop('Первая.m4a');drop('Свет.m4a');
   assert(form.querySelector('#import-title').value==='Свет','Новое имя при замене файла');
   const submit=form.querySelector('[type=submit]');submit.focus();submit.click();
   const current=form.querySelector('.current-import'),open=current.querySelector('button');
   await until(()=>!current.hidden&&!open.hidden,'Сохранение и открытие в библиотеке');
   assert(current.textContent.includes('Файл сохранён на Mac'),'Подтверждение сохранения');
   const uploaded='lecture-2026-11-24-14-00-00.wav';
   await until(()=>cards.has(uploaded),'Запись в каталоге');
   const newCard=cards.get(uploaded);
   assert(!newCard.details.open&&!newCard.workflowAudioBound&&!newCard.readerRoot,'Свернутый календарь открыл запись в фоне');
   open.click();
   await until(()=>cards.get(uploaded)?.readerRoot?.isConnected,'Читалка импортированной лекции');
   const reader=cards.get(uploaded);
   document.dispatchEvent(new KeyboardEvent('keydown',{key:'f',metaKey:true,bubbles:true,cancelable:true}));
   const search=reader.readerRoot.querySelector('input[type=search]');
   assert(document.activeElement===search,'Поиск в открытой лекции');
   search.value='БАЗИС';search.dispatchEvent(new Event('input'));
   assert(reader.readerRoot.querySelectorAll('.transcript-line').length===1&&reader.readerRoot.querySelector('mark').textContent==='базис','Выделение найденной фразы');
   reader.readerRoot.querySelector('.transcript-line').click();
   await until(()=>!reader.audio.paused&&reader.audio.currentTime>=4&&reader.audio.currentTime<7,'Прослушивание с отметки фразы');
   search.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
   assert(!search.value&&reader.readerRoot.querySelectorAll('.transcript-line').length===2,'Очистка запроса с клавиатуры');
   document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
   assert(!document.querySelector('.is-reading')&&!reader.details.open&&reader.audio.paused,'Возврат из читалки и остановка звука');
   const calendar=document.querySelector('.library-calendar');calendar.open=true;
   await until(()=>reader.details.open,'Выбор единственной записи в открытом календаре');
   assert(document.documentElement.scrollWidth<=innerWidth,'Ширина окна');
   result.textContent='ok';return;
  }
  window.showLectureView('library',false);
  const panel=document.querySelector('.library-catalog');
  const search=panel.querySelector('input'),pinned=panel.querySelector('.library-filter');
  const rows=()=>Array.from(panel.querySelectorAll('.library-entry'));
  const query=text=>{search.value=text;search.dispatchEvent(new Event('input'))};
  const back=()=>document.querySelector('.reader-back').click();
  const open=async(name)=>{
   if(document.querySelector('.is-reading'))back();
   query(name);assert(rows().length===1,'Результат открытия '+name);
   const button=rows()[0].querySelector('.library-open');button.focus();button.click();
   const card=cards.get(name);
   assert(card.details.open&&!card.li.closest('[hidden]'),'Карточка оказалась скрыта');
   await until(()=>card.audio.readyState>0,'Метаданные плеера');
   return card;
  };
  await until(()=>rows().length===6,'Начальная библиотека · '+document.querySelector('#error').textContent);
  assert(panel.scrollWidth<=panel.clientWidth+1,'Ширина библиотеки');
  assert(rows()[0].querySelector('.library-star').getBoundingClientRect().width>=44,'Размер кнопки избранного');
  const first='lecture-2026-11-01-10-00-00.wav',target='lecture-2026-11-09-10-00-00.wav';
  if(location.search.includes('initial')){
   const more=panel.querySelector('.library-more');more.click();
   assert(rows().length===9&&!rows().some(row=>row.dataset.file.includes('-11-10-')),'Пагинация или активная запись');
   document.dispatchEvent(new KeyboardEvent('keydown',{key:'k',metaKey:true,bubbles:true}));
   assert(document.activeElement===search,'Клавиатурный фокус');
   query('петр 01.11.2026');assert(rows().length===1&&rows()[0].dataset.file===target,'Поиск по преподавателю и дате');
   query('семинар-8');assert(rows().length===1&&rows()[0].dataset.file===target,'Исходное имя');
   const star=rows()[0].querySelector('.library-star');star.focus();star.click();
   assert(document.activeElement===star&&star.getAttribute('aria-pressed')==='true','Фокус или добавление в избранное');
   query('');pinned.click();assert(rows().length===1&&rows()[0].dataset.file===target,'Фильтр избранного');
   pinned.click();
   const card=await open(target);
   await until(()=>card.readerRoot?.isConnected,'Карточка с готовой расшифровкой');
   card.readerRoot.querySelector('[data-reader-control="summary"]').click();
   assert(card.readerRoot.querySelector('.reader-playback select')===card.rateSelect,'Скорость доступна из конспекта');
   card.rateSelect.value='1.5';card.rateSelect.dispatchEvent(new Event('change'));
   card.audio.currentTime=3.25;
   await until(()=>Number(localStorage.getItem('lecture-playback:'+target))===3.3&&Number(localStorage.getItem('lecture-rate:'+target))===1.5,'Сохранение плеера');
   const orphan=await open(first);orphan.audio.currentTime=6.5;
   await until(()=>Number(localStorage.getItem('lecture-playback:'+first))===6.5,'Отдельная позиция без папки');
  }else{
   pinned.click();assert(rows().length===1&&rows()[0].dataset.file===target,'Избранное после перезапуска');
   const card=await open(target);
   assert(Math.abs(card.audio.currentTime-3.3)<.06&&card.audio.playbackRate===1.5,'Позиция и скорость после перезапуска');
   back();assert(document.activeElement===rows()[0].querySelector('.library-open'),'Возврат фокуса к записи');
   const star=rows()[0].querySelector('.library-star');star.focus();star.click();
   assert(rows().length===0&&document.activeElement===pinned&&!panel.querySelector('.library-catalog-empty').hidden,'Удаление последнего избранного');
   panel.querySelector('.library-catalog-empty button').click();
   const orphan=await open(first);
   assert(Math.abs(orphan.audio.currentTime-6.5)<.06&&orphan.audio.playbackRate===1,'Независимость записей');
   window.LectureWorkflow.seek(orphan,1.5);
   assert(Math.abs(orphan.audio.currentTime-1.5)<.2,'Явный таймкод');
   orphan.audio.currentTime=orphan.audio.duration-.12;
   await orphan.audio.play();
   await until(()=>orphan.audio.ended&&localStorage.getItem('lecture-playback:'+first)===null,'Дослушанная запись начинается сначала');
  }
  result.textContent='ok';
 }catch(error){result.textContent=String(error)}
})();
