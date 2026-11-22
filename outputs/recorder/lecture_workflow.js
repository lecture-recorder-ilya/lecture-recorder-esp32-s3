(() => {
 'use strict';
 const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
 const clock=value=>{let s=Math.max(0,Math.floor(Number(value)||0));const h=Math.floor(s/3600),m=Math.floor(s/60)%60;s%=60;return(h?String(h).padStart(2,'0')+':':'')+String(m).padStart(2,'0')+':'+String(s).padStart(2,'0')};
 const motion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth';
 function seek(card,seconds){
  if(!Number.isFinite(Number(seconds))||Number(seconds)<0)return;
  bindAudio(card);
  const audio=card.audio;card.pendingSeek=Number(seconds);
  if(!card.readerRoot?.isConnected&&card.audioTools?.contains(audio))card.audioTools.open=true;
  if(audio.readyState){audio.currentTime=Math.min(card.pendingSeek,Number.isFinite(audio.duration)?audio.duration:card.pendingSeek);card.pendingSeek=null;}
  audio.play().then(()=>{if(card.readerNotice)card.readerNotice.textContent=''}).catch(()=>{if(card.readerNotice)card.readerNotice.textContent='Не удалось включить звук. Нажми воспроизведение в плеере или проверь аудиофайл.'});
 }
 function bindAudio(card){
  if(card.workflowAudioBound)return;card.workflowAudioBound=true;
  const audio=card.audio;if(audio.preload==='none')audio.preload='metadata';
  audio.addEventListener('loadedmetadata',()=>{if(card.pendingSeek!==null&&card.pendingSeek!==undefined){audio.currentTime=Math.min(card.pendingSeek,audio.duration);card.pendingSeek=null}});
  audio.addEventListener('play',()=>{for(const other of document.querySelectorAll('audio'))if(other!==audio)other.pause()});
 }
 function renderReader(parent,card,report,name){
  bindAudio(card);
  const state=card.readerState||(card.readerState={tab:'text',query:'',follow:false,scroll:0});
  if(card.readerTimeline)state.scroll=card.readerTimeline.scrollTop;
  card.readerAbort?.abort();const controller=new AbortController();card.readerAbort=controller;
  const signal=controller.signal;
  const root=node('section',undefined,'lecture-reader');root.setAttribute('aria-label','Расшифровка и конспект');
  const top=node('div',undefined,'reader-top');
  const tabs=node('div',undefined,'reader-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Материалы записи');
  const panel=node('div',undefined,'reader-panel');panel.setAttribute('role','tabpanel');
  const notice=node('p','','reader-notice');notice.setAttribute('role','status');card.readerNotice=notice;
  const rows=report.segments||[];const timedRows=rows.filter(r=>Number.isFinite(r.start)&&Number.isFinite(r.end));
  const pending=()=>rows.filter(r=>r.needs_review&&!r.reviewed).length;
  const buttons={};
  for(const [key,title] of [['text','Текст'],['summary','Конспект'],['review','Проверить']]){
   const b=node('button',title);b.type='button';b.setAttribute('role','tab');b.id='reader-'+name.replace(/\W/g,'')+'-'+key;b.onclick=()=>show(key);buttons[key]=b;tabs.append(b);
   b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const keys=Object.keys(buttons),i=keys.indexOf(key);const next=e.key==='Home'?0:e.key==='End'?keys.length-1:(i+(e.key==='ArrowRight'?1:-1)+keys.length)%keys.length;show(keys[next]);buttons[keys[next]].focus()};
  }
  const badge=node('span',report.draft?'Текст появляется по мере обработки':'Разбор готов','reader-badge');
  const playback=node('div',undefined,'reader-playback');
  if(card.playerDock?.isConnected&&card.audioTools){
   card.audioTools.append(card.audio);
   card.playerDock.remove();
  }
  const play=node('button','Слушать','secondary reader-play');
  play.type='button';
  const steps=node('div',undefined,'reader-transport');
  const step=(label,description,seconds)=>{
   const button=node('button',label,'secondary reader-skip');
   button.type='button';
   button.title=description;
   button.setAttribute('aria-label',description);
   button.onclick=()=>{
    if(!button.disabled)card.audio.currentTime=Math.max(0,Math.min(card.audio.duration,card.audio.currentTime+seconds));
   };
   return button;
  };
  const back=step('−10','На 10 секунд назад',-10);
  const ahead=step('+10','На 10 секунд вперёд',10);
  steps.append(back,play,ahead);
  const timecode=node('span','','reader-position');
  const seekRange=node('input',undefined,'reader-seek');
  seekRange.type='range';seekRange.min='0';seekRange.step='0.25';seekRange.value='0';
  seekRange.setAttribute('aria-label','Позиция воспроизведения');
  const updatePlayback=()=>{
   const label=card.audio.paused?'Слушать':'Пауза';
   if(play.textContent!==label)play.textContent=label;
   playback.classList.toggle('is-playing',!card.audio.paused);
   const duration=card.audio.duration,available=Number.isFinite(duration)&&duration>0;
   seekRange.disabled=!available;
   back.disabled=ahead.disabled=!available;
   if(available&&Number(seekRange.max)!==duration)seekRange.max=duration;
   seekRange.value=card.audio.currentTime;
   const position=clock(card.audio.currentTime);
   const total=available?' / '+clock(duration):'';
   const time=position+total;
   if(timecode.textContent!==time){
    timecode.textContent=time;
    seekRange.setAttribute('aria-valuetext',time);
   }
  };
  play.onclick=()=>{if(card.audio.paused)seek(card,card.audio.currentTime||0);else card.audio.pause()};
  seekRange.oninput=()=>{if(!seekRange.disabled)card.audio.currentTime=Number(seekRange.value)};
  for(const event of ['play','pause','ended','loadedmetadata','durationchange','timeupdate','seeked'])card.audio.addEventListener(event,updatePlayback,{signal});
  updatePlayback();
  playback.append(steps,seekRange,timecode);
  top.append(tabs,badge);root.append(top,playback,notice,panel);parent.append(root);
  card.readerRoot=root;card.workflowBadge=badge;
  const caption=node('p','Нажми на фразу, чтобы услышать её в записи.','reader-caption');
  const toolbar=node('div',undefined,'reader-toolbar');
  const search=node('input');search.type='search';search.placeholder='Найти в расшифровке';search.setAttribute('aria-label','Поиск в тексте этой пары');search.value=state.query;
  const follow=node('input');follow.type='checkbox';follow.checked=state.follow;const followLabel=node('label','Следовать за аудио');followLabel.prepend(follow);follow.onchange=()=>{state.follow=follow.checked};
  const speed=node('select');speed.setAttribute('aria-label','Скорость воспроизведения');for(const value of [.75,1,1.25,1.5,2]){const option=node('option',value+'×');option.value=value;speed.append(option)}speed.value=String(card.audio.playbackRate||1);speed.onchange=()=>card.audio.playbackRate=Number(speed.value);
  toolbar.append(search,followLabel,speed);
  const timeline=node('div',undefined,'reader-timeline full-lecture');timeline.tabIndex=0;timeline.setAttribute('aria-label','Текст с таймкодами');card.readerTimeline=timeline;
  const empty=node('p','','reader-empty');
  const footer=node('div',undefined,'reader-footer');
  const download=node('a','Скачать текст с таймкодами');download.href='/transcript-export/'+encodeURIComponent(name);download.download=name.replace(/\.wav$/,'.txt');footer.append(download);
  const itemNodes=new Map();
  let activeItem=null;
  let reviewIndex=-1;
  const reviewNavigation=node('div',undefined,'reader-review-navigation');
  const reviewPosition=node('span','','reader-review-position');
  reviewPosition.setAttribute('role','status');
  const reviewPrevious=node('button','Назад','secondary reader-step-prev');
  const reviewNext=node('button','Дальше','secondary reader-step-next');
  const reviewInText=node('button','Весь текст','secondary reader-step-text');
  reviewPrevious.setAttribute('aria-label','Предыдущий фрагмент');
  reviewNext.setAttribute('aria-label','Следующий фрагмент');
  reviewInText.type='button';
  reviewInText.onclick=()=>{
   const item=Array.from(itemNodes.values())[reviewIndex];
   show('text');
   if(item)focusFragment(itemNodes.get(item.segment.id));
   else buttons.text.focus();
  };
  reviewPrevious.type=reviewNext.type='button';
  reviewPrevious.onclick=()=>jumpReview(reviewIndex-1);
  reviewNext.onclick=()=>jumpReview(reviewIndex+1);
  reviewNavigation.append(reviewPosition,reviewPrevious,reviewNext,reviewInText);
  function counts(){buttons.review.textContent='Проверить'+(pending()?' · '+pending():'');}
  function updateReviewNavigation(){
   const count=itemNodes.size;
   reviewPosition.textContent=count?(reviewIndex<0?count+' фрагм.':String(reviewIndex+1)+' из '+count):'';
   reviewPosition.hidden=!count;
   reviewPrevious.hidden=reviewNext.hidden=!count;
   reviewInText.textContent=reviewIndex<0?'Весь текст':'К тексту';
   reviewInText.setAttribute('aria-label',reviewIndex<0?'Весь текст':'К фрагменту в тексте');
   reviewPrevious.disabled=reviewIndex<=0;
   reviewNext.disabled=reviewIndex>=count-1;
   if(state.tab==='review'){
    let index=0;
    for(const item of itemNodes.values())item.row.classList.toggle('is-review-target',index++===reviewIndex);
   }
  }
  function jumpReview(index){
   const item=Array.from(itemNodes.values())[index];
   if(!item)return;
   reviewIndex=index;
   updateReviewNavigation();
   focusFragment(item);
  }
  function focusFragment(item){
   if(!item)return;
   if(item.line.disabled){item.row.tabIndex=-1;item.row.focus({preventScroll:true});}
   else item.line.focus({preventScroll:true});
   item.row.scrollIntoView({block:'nearest',behavior:motion()});
  }
  function renderRows(){
   const previous=timeline.scrollTop;timeline.replaceChildren();itemNodes.clear();
   activeItem=null;
   const query=state.query.trim().toLocaleLowerCase('ru');
   const visible=rows.filter(r=>(state.tab!=='review'||r.needs_review&&!r.reviewed)&&(!query||r.text.toLocaleLowerCase('ru').includes(query)));
   for(const [index,segment] of visible.entries()){
    const row=node('article',undefined,'segment transcript-row'+(segment.needs_review?' needs-review':'')+(segment.reviewed?' is-reviewed':''));
    row.dataset.start=segment.start;row.dataset.end=segment.end;row.dataset.segment=segment.id;
    const line=node('button',undefined,'transcript-line');line.type='button';const timed=Number.isFinite(segment.start);line.setAttribute('aria-label',(timed?clock(segment.start):'Без таймкода')+'. '+segment.text);if(!timed)line.disabled=true;
    const time=node('span',timed?clock(segment.start):'—','transcript-time');time.title=segment.timing==='audio_excerpt'?'Начало аудиофрагмента; время отдельных слов может отличаться':'Слушать с этого момента';
    const copy=node('span',segment.text,'transcript-copy');line.append(time,copy);
    line.onfocus=()=>{if(state.tab==='review'){reviewIndex=index;updateReviewNavigation()}};
    line.onclick=()=>{
     const selected=window.getSelection();
     if(selected?.toString()&&selected.containsNode(line,true))return;
     if(state.tab==='review'){reviewIndex=index;updateReviewNavigation()}
     seek(card,segment.start);
    };
    row.append(line);
    if(segment.needs_review||segment.reviewed){
     const reviewBar=node('div',undefined,'transcript-review');
     const label=node('span',segment.reviewed?'Проверено по записи':'Проверь по записи','review-label');
     const reasons=(segment.quality?.reasons||[]).filter(reason=>reason!=='Распознавание требует проверки по записи').join(' · ');
     reviewBar.append(label);
     if(reasons&&!segment.reviewed)reviewBar.append(node('span',reasons,'review-reasons'));
     if(state.tab==='review'){
      for(const span of segment.quality?.unrecognized_audio||[]){
       if(!Number.isFinite(span?.start)||!Number.isFinite(span.end)||span.start<0||span.end<=span.start)continue;
       const listen=node('button','Слушать участок · '+clock(span.start),'review-action review-audio-gap');
       listen.type='button';listen.onclick=()=>seek(card,span.start);
       reviewBar.append(listen);
      }
     }
     const acknowledge=node('button',segment.reviewed?'Отменить проверку':'Подтвердить по записи','review-action');acknowledge.type='button';
     acknowledge.onclick=async()=>{
      acknowledge.disabled=true;
      try{
       const value=await post('/transcript-review',{file:name,key:segment.review_key,reviewed:!segment.reviewed});
       segment.reviewed=value.reviewed;
       counts();renderRows();
       if(state.tab==='review'&&itemNodes.size)jumpReview(Math.min(index,itemNodes.size-1));
       else if(state.tab==='review')buttons.review.focus();
       else itemNodes.get(segment.id)?.row.querySelector('.review-action')?.focus();
       notice.textContent=value.reviewed?'Отметка сохранена.':'Отметка снята.';
      }catch(e){notice.textContent=e.message;acknowledge.disabled=false}
     };
     if(segment.review_key)reviewBar.append(acknowledge);row.append(reviewBar);
    }
    if(segment.original_text&&segment.original_text!==segment.text){const details=node('details',undefined,'transcript-original');details.append(node('summary','Исходное распознавание'),node('p',segment.original_text));row.append(details)}
    timeline.append(row);itemNodes.set(segment.id,{row,line,segment});
   }
   empty.hidden=visible.length>0;
   empty.textContent=query?'Совпадений не найдено.':state.tab==='review'?'Фраз для проверки пока нет.':report.draft?'Распознавание началось. Первые фразы появятся здесь.':'Разборчивой речи не обнаружено. Можно прослушать исходную запись.';
   if(!visible.length)timeline.append(empty);
   reviewIndex=Math.min(reviewIndex,visible.length-1);
   updateReviewNavigation();
   timeline.scrollTop=previous;highlight();
  }
  function highlight(){
   const position=card.audio.currentTime;
   let lo=0,hi=timedRows.length-1,index=-1;
   while(lo<=hi){const mid=(lo+hi)>>1;if(timedRows[mid].start<=position){index=mid;lo=mid+1}else hi=mid-1}
   const next=index>=0&&position<timedRows[index].end?itemNodes.get(timedRows[index].id):null;
   if(next===activeItem)return;
   if(activeItem){
    activeItem.row.classList.remove('is-playing');
    activeItem.line.removeAttribute('aria-current');
   }
   activeItem=next||null;
   if(!next)return;
   next.row.classList.add('is-playing');
   next.line.setAttribute('aria-current','true');
   if(state.follow&&timeline.isConnected){
    timeline.scrollTo({top:Math.max(0,next.row.offsetTop-timeline.clientHeight*.3),behavior:motion()});
   }
  }
  card.audio.addEventListener('timeupdate',highlight,{signal});card.audio.addEventListener('seeked',highlight,{signal});
  function summary(){
   const summary=node('section',undefined,'reader-summary');
   if(report.draft){summary.append(node('h4','Готовим конспект'),node('p','Сначала распознаём запись целиком. Уже готовый текст доступен на вкладке «Текст».','muted'));return summary}
   if(report.overview)summary.append(node('h4','Главное за пару'),node('p',report.overview));
   if(report.summary?.length){
    summary.append(node('h4','Ключевые мысли'));
    const list=node('ul'),evidence=new Map((report.summary_evidence||[]).map(item=>[item.quote,item]));
    for(const point of report.summary){
     const item=node('li',point),source=evidence.get(point);
     if(Number.isFinite(source?.start)){
      const playQuote=node('button','Слушать · '+clock(source.start),'reader-chapter summary-listen');
      playQuote.type='button';
      playQuote.onclick=()=>seek(card,source.start);
      item.append(playQuote);
     }
     list.append(item);
    }
    summary.append(list);
   }
   if(!report.overview&&!report.summary?.length)summary.append(node('p','Недостаточно разборчивой речи для содержательного конспекта.','muted'));
   if(report.sections?.length){summary.append(node('h4','Темы по времени'));const chapters=node('div',undefined,'reader-chapters');for(const section of report.sections){const b=node('button',clock(section.start)+' · '+section.title,'reader-chapter');b.onclick=()=>{show('text');seek(card,section.start)};chapters.append(b)}summary.append(chapters)}
   if(report.homework?.length){summary.append(node('h4','Что задано'));for(const task of report.homework){const p=node('article');p.append(node('p',task.task));if(task.quote){const quote=node('blockquote',task.quote);p.append(quote)}const b=node('button','Проверить по записи · '+clock(task.start),'reader-chapter');b.onclick=()=>{show('text');seek(card,task.start)};p.append(b);summary.append(p)}}
   if(report.formulas?.length&&typeof formulaRows==='function'){summary.append(node('h4','Формулы из объяснения'));formulaRows(summary,report,card)}
   if(pending())summary.append(node('p','В расшифровке осталось мест для проверки: '+pending()+'. Сверь их со звуком перед подготовкой к занятию.','summary-caution'));
   if(report.overview||report.summary?.length){const exportLink=node('a','Скачать конспект .md','summary-download');exportLink.href='/export/'+encodeURIComponent(name);exportLink.download=name.replace(/\.wav$/,'.md');summary.append(exportLink)}
   return summary;
  }
  function show(tab){
   if(card.readerTimeline?.isConnected)state.scroll=timeline.scrollTop;
   state.tab=tab;counts();
   for(const [key,b]of Object.entries(buttons)){b.setAttribute('aria-selected',key===tab?'true':'false');b.tabIndex=key===tab?0:-1}
   panel.setAttribute('aria-labelledby',buttons[tab].id);panel.replaceChildren();
   panel.classList.remove('is-entering');
   requestAnimationFrame(()=>panel.classList.add('is-entering'));
   if(tab==='summary')panel.append(summary());
   else{caption.textContent=tab==='review'?'Прослушай отмеченные фразы и подтверди те, что проверил.':'Нажми на фразу, чтобы услышать её в записи.';panel.append(caption,toolbar);if(tab==='review'){reviewIndex=-1;panel.append(reviewNavigation)}panel.append(timeline,footer);renderRows();timeline.scrollTop=state.scroll;
    if(report.quality?.unassessed)panel.append(node('p','Для '+report.quality.unassessed+' фрагм. оценка качества распознавания недоступна.','reader-caption'));
   }
  }
  search.oninput=()=>{state.query=search.value;reviewIndex=-1;renderRows()};
  show(state.tab);
 }
 function refreshCard(card,job){
  if(!card.workflowBadge)return;
  const busy=['queued','processing'].includes(job?.status);
  card.workflowBadge.textContent=busy?(job.message||'Обрабатываю запись'):job?.status==='error'?'Разбор прерван · можно повторить':card.workflowBadge.textContent==='Разбор готов'?'Разбор готов':'Текст готов';
 }
 async function openRecording(name){
  window.showLectureView?.('library',false);
  let card=cards.get(name);
  if(!card){await update();card=cards.get(name)}
  if(!card)return;
  window.revealCalendarFile?.(name);
  card.details.open=true;
  card.li.closest('#files>li>details')?.setAttribute('open','');
  card.details.querySelector('summary')?.focus({preventScroll:true});
  card.li.scrollIntoView({block:'start',behavior:motion()});
  update();
 }
 function initImport(){
  const library=document.querySelector('#view-library');if(!library)return;
  const importPanel=node('details',undefined,'lecture-import-panel card');
  importPanel.append(node('summary','Импорт аудио'));
  const form=node('form',undefined,'lecture-import');form.id='lecture-import';
  const headline=node('div',undefined,'import-heading');headline.append(node('p','Выбери аудиозапись. Расшифровка и конспект готовятся на этом Mac.','muted'));form.append(headline);
  importPanel.append(form);
  const picker=node('input');picker.type='file';picker.id='lecture-audio-file';picker.accept='audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm,.mp4,.caf,.aif,.aiff';picker.className='import-file-input';
  const choose=node('button','Выбрать аудиозапись','import-choose');choose.type='button';choose.onclick=()=>picker.click();
  const drop=node('div',undefined,'import-drop');const filename=node('span','WAV, MP3, M4A и другие форматы · до 2 ГБ','import-filename');drop.append(choose,filename,picker);form.append(drop);
  let selected=null,upload=null;
  function select(file){selected=file||null;filename.textContent=selected?selected.name+' · '+(selected.size/1024/1024).toFixed(1)+' МБ':'WAV, MP3, M4A и другие форматы · до 2 ГБ';submit.disabled=!selected;message.textContent='';if(selected&&!title.value)title.value=selected.name.replace(/\.[^.]+$/,'')}
  picker.onchange=()=>select(picker.files[0]);
  drop.ondragover=e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();drop.classList.add('drag-over')}};drop.ondragleave=()=>drop.classList.remove('drag-over');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('drag-over');if(!upload)select(e.dataTransfer.files[0])};
  const fields=node('div',undefined,'import-fields');
  const input=(caption,type,id)=>{const label=node('label',caption),i=node('input');i.type=type;i.id=id;i.maxLength=160;label.append(i);fields.append(label);return i};
  const title=input('Название пары','text','import-title');title.placeholder='Например: Производная и её смысл';
  const subject=input('Предмет · необязательно','text','import-subject');subject.placeholder='Математический анализ';
  const date=input('Дата занятия','date','import-date');const now=new Date();date.value=[now.getFullYear(),String(now.getMonth()+1).padStart(2,'0'),String(now.getDate()).padStart(2,'0')].join('-');form.append(fields);
  const actions=node('div',undefined,'import-actions');const submit=node('button','Загрузить и подготовить конспект');submit.type='submit';submit.disabled=true;
  const cancel=node('button','Отменить загрузку','secondary');cancel.type='button';cancel.hidden=true;cancel.onclick=()=>upload?.abort();actions.append(submit,cancel);form.append(actions);
  const progress=node('progress');progress.max=100;progress.hidden=true;progress.setAttribute('aria-label','Загрузка записи');const message=node('p','','import-message');message.setAttribute('role','status');const jobs=node('div',undefined,'import-jobs');form.append(progress,message,jobs);
  library.querySelector('.view-intro').after(importPanel);
  const openImport=()=>{
   window.showLectureView?.('library');
   importPanel.open=true;
   choose.focus({preventScroll:true});
   importPanel.scrollIntoView({block:'start',behavior:motion()});
  };
  const recent=node('section',undefined,'card library-recent');
  recent.hidden=true;
  const recentList=node('ul');
  recent.append(node('h3','Последние записи'),recentList);
  importPanel.before(recent);
  let recentStamp;
  refreshLibrary=status=>{
   const names=(status.files||[]).filter(name=>name!==status.file||!status.recording&&!status.busy).slice(0,3);
   const entries=names.map(name=>[name,status.lessons?.[name]?.title||status.lessons?.[name]?.subject||status.lessons?.[name]?.label||name]);
   const stamp=JSON.stringify(entries);
   if(stamp===recentStamp)return;
   recentStamp=stamp;
   recent.hidden=false;
   recentList.replaceChildren(...entries.map(([name,title])=>{
    const item=node('li');
    const label=node('span',title);
    const open=node('button','Открыть','secondary');
    open.type='button';
    open.setAttribute('aria-label','Открыть запись · '+title);
    open.onclick=()=>openRecording(name);
    item.append(label,open);
    return item;
   }));
   if(!entries.length){
    const empty=node('li');
    const importAudio=node('button','Импортировать аудио','secondary');
    importAudio.type='button';
    importAudio.onclick=openImport;
    empty.append(node('span','Записей пока нет. Запиши пару или импортируй аудиофайл.'),importAudio);
    recentList.append(empty);
   }
  };
  const shortcuts=document.querySelector('#view-record .record-shortcuts');
  if(shortcuts){
   const shortcut=node('button','Импорт аудио','secondary');
   shortcut.type='button';
   shortcut.onclick=openImport;
   shortcuts.prepend(shortcut);
  }
  const pendingOpen=new Set();let stamp='',polling=false;
  async function poll(){
   if(polling)return;polling=true;
   try{const response=await fetch('/imports',{cache:'no-store'});if(!response.ok)throw Error();const value=await response.json();const current=JSON.stringify([value.jobs,(typeof studyStatus==='object'?studyStatus?.ai?.jobs:{})]);
    if(current!==stamp){stamp=current;jobs.replaceChildren();for(const job of (value.jobs||[]).slice(0,5)){
     const row=node('article',undefined,'import-job');const copy=node('div');copy.append(node('strong',job.title||job.name));const ai=typeof studyStatus==='object'?studyStatus?.ai?.jobs?.[job.file]:null;const status=job.status==='ready'&&ai?.message?ai.message:job.message;copy.append(node('p',status,'muted'));row.append(copy);
     if(job.status==='error'){const retry=node('button','Повторить','secondary');retry.type='button';retry.onclick=async()=>{retry.disabled=true;try{await post('/imports/retry',{id:job.id});stamp='';await poll()}catch(e){message.textContent=e.message}finally{retry.disabled=false}};row.append(retry)}
     if(job.status==='ready'){const b=node('button','Открыть пару','secondary');b.type='button';b.onclick=()=>openRecording(job.file);row.append(b)}jobs.append(row);
    }}
    for(const job of value.jobs||[])if(job.status==='ready'&&pendingOpen.has(job.id)&&typeof cards!=='undefined'&&cards.has(job.file)){pendingOpen.delete(job.id);if(!library.hidden&&importPanel.open)openRecording(job.file)}
   }catch{}finally{polling=false}
  }
  form.onsubmit=e=>{e.preventDefault();if(!selected||upload)return;if(selected.size===0||selected.size>2*1024**3){message.textContent='Выбери непустую запись размером до 2 ГБ.';return}
   const params=new URLSearchParams({name:selected.name,title:title.value,subject:subject.value,date:date.value,analyze:'1'});
   const xhr=new XMLHttpRequest();upload=xhr;submit.disabled=true;choose.disabled=true;cancel.hidden=false;progress.hidden=false;progress.value=0;message.textContent='Загружаю запись…';
   xhr.open('POST','/import-audio?'+params.toString());xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.timeout=30*60*1000;
   xhr.upload.onprogress=event=>{if(event.lengthComputable){progress.value=event.loaded/event.total*100;message.textContent='Загружаю запись · '+Math.round(progress.value)+'%'}};
   xhr.onload=()=>{let value={};try{value=JSON.parse(xhr.responseText)}catch{}if(xhr.status>=200&&xhr.status<300){message.textContent=value.duplicate?'Эта запись уже загружена. Открываю её в библиотеке.':'Аудио сохранено. Подготавливаю текст и конспект…';pendingOpen.add(value.id);picker.value='';selected=null;filename.textContent='Можно загрузить следующую запись';stamp='';update().then(poll)}else message.textContent=value.error||'Не удалось загрузить запись. Исходный файл остался у тебя.'};
   xhr.onerror=()=>message.textContent='Связь прервалась. Исходная запись осталась у тебя; повтори загрузку.';xhr.ontimeout=xhr.onerror;xhr.onabort=()=>message.textContent='Загрузка отменена. Исходная запись осталась у тебя.';
   xhr.onloadend=()=>{upload=null;submit.disabled=!selected;choose.disabled=false;cancel.hidden=true;progress.hidden=true};xhr.send(selected);
  };
  const loop=async()=>{if(!document.hidden)await poll();setTimeout(loop,2000)};loop();
 }
 let refreshLibrary=()=>{};
 window.LectureWorkflow={renderReader,refreshCard,seek,clock,openRecording,refreshLibrary:status=>refreshLibrary(status)};
 initImport();
})();
