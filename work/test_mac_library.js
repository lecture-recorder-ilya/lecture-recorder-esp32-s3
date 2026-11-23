(async()=>{
 const result=document.createElement('output');
 result.id='library-test';document.body.append(result);
 const assert=(condition,note)=>{if(!condition)throw Error(note)};
 const until=async(check,note)=>{
  for(let i=0;i<90;i++){if(check())return;await new Promise(done=>setTimeout(done,30))}
  throw Error(note);
 };
 try{
  window.showLectureView('library',false);
  const panel=document.querySelector('.library-catalog');
  const search=panel.querySelector('input'),pinned=panel.querySelector('.library-filter');
  const rows=()=>Array.from(panel.querySelectorAll('.library-entry'));
  const query=text=>{search.value=text;search.dispatchEvent(new Event('input'))};
  const open=async(name)=>{
   query(name);assert(rows().length===1,'Результат открытия '+name);
   rows()[0].querySelector('.library-open').click();
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
