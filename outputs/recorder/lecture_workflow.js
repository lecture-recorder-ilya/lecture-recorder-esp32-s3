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
 function rememberPosition(card){
  const time=card.audio.ended?0:card.audio.currentTime;
  if(!card.name||!card.audio.readyState||card.pendingSeek!=null||!Number.isFinite(time))return;
  const seconds=Math.round(time*10)/10;
  if(seconds===card.lastPlaybackPosition)return;
  card.lastPlaybackPosition=seconds;
  try{
   if(seconds>0)localStorage.setItem('lecture-playback:'+card.name,String(seconds));
   else localStorage.removeItem('lecture-playback:'+card.name);
  }catch{}
 }
 function pauseLibrary(){
  for(const card of cards.values())if(card.workflowAudioBound){
   card.audio.pause();
   rememberPosition(card);
  }
 }
 window.addEventListener('pagehide',pauseLibrary);
 function bindAudio(card){
  if(card.workflowAudioBound)return;card.workflowAudioBound=true;
  const audio=card.audio;
  const rates=[.5,.75,1,1.25,1.5,1.75,2];
  const speed=node('select',undefined,'record-playback-rate');
  speed.setAttribute('aria-label','Скорость воспроизведения');
  for(const rate of rates){
   const option=node('option',rate.toLocaleString('ru')+'×');option.value=String(rate);speed.append(option);
  }
  const label=node('label','Скорость','record-rate');label.append(speed);
  card.rateLabel=label;card.rateSelect=speed;
  if(card.playerDock)card.playerDock.append(label);
  try{
   const seconds=Number(localStorage.getItem('lecture-playback:'+card.name));
   if(Number.isFinite(seconds)&&seconds>0){card.pendingSeek=seconds;card.lastPlaybackPosition=seconds;}
   const rate=Number(localStorage.getItem('lecture-rate:'+card.name));
   if(rates.includes(rate))audio.defaultPlaybackRate=audio.playbackRate=rate;
  }catch{}
  speed.value=String(audio.playbackRate||1);
  speed.onchange=()=>{audio.defaultPlaybackRate=audio.playbackRate=Number(speed.value)};
  audio.addEventListener('ratechange',()=>{
   const rate=audio.playbackRate;
   if(!rates.includes(rate))return;
   speed.value=String(rate);
   if(audio.defaultPlaybackRate!==rate)audio.defaultPlaybackRate=rate;
   try{localStorage.setItem('lecture-rate:'+card.name,String(rate))}catch{}
  });
  const restore=()=>{
   if(card.pendingSeek==null)return;
   const seconds=card.pendingSeek;
   card.pendingSeek=null;
   const expired=seconds===card.lastPlaybackPosition&&Number.isFinite(audio.duration)&&seconds>=audio.duration;
   audio.currentTime=expired?0:Number.isFinite(audio.duration)?Math.min(seconds,audio.duration):seconds;
   if(expired)rememberPosition(card);
  };
  audio.addEventListener('loadedmetadata',restore);
  for(const event of ['pause','seeked','ended'])audio.addEventListener(event,()=>rememberPosition(card));
  audio.addEventListener('timeupdate',()=>{
   if(!audio.paused&&Math.abs(audio.currentTime-(card.lastPlaybackPosition||0))>=4)rememberPosition(card);
  });
  audio.addEventListener('play',()=>{for(const other of document.querySelectorAll('audio'))if(other!==audio)other.pause()});
  if(audio.readyState)restore();
  if(audio.preload==='none')audio.preload='metadata';
 }
 function renderReader(parent,card,report,name,previousFocus){
  bindAudio(card);
  const state=card.readerState||(card.readerState={tab:'text',query:'',follow:false,scroll:0});
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
  const indicator=node('span',undefined,'reader-tab-indicator');
  indicator.setAttribute('aria-hidden','true');
  const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
  let indicatorMotion,panelMotion;
  const cancelMotion=()=>{indicatorMotion?.cancel();panelMotion?.cancel()};
  reducedMotion.addEventListener('change',cancelMotion,{signal});
  for(const [key,title] of [['text','Расшифровка'],['summary','Конспект'],['review','Проверить']]){
   const b=node('button',title);b.type='button';b.setAttribute('role','tab');b.id='reader-'+encodeURIComponent(name)+'-'+key;b.onclick=()=>show(key);buttons[key]=b;tabs.append(b);
   b.onkeydown=e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const keys=Object.keys(buttons),i=keys.indexOf(key);const next=e.key==='Home'?0:e.key==='End'?keys.length-1:(i+(e.key==='ArrowRight'?1:-1)+keys.length)%keys.length;show(keys[next]);buttons[keys[next]].focus()};
  }
  const badge=node('span',report.draft_kind==='support_quotes'?'Черновик':report.draft?'Текст появляется по мере обработки':'Разбор готов','reader-badge');
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
  play.onclick=()=>{if(card.audio.paused)seek(card,card.pendingSeek??card.audio.currentTime??0);else card.audio.pause()};
  seekRange.oninput=()=>{if(!seekRange.disabled)card.audio.currentTime=Number(seekRange.value)};
  for(const event of ['play','pause','ended','loadedmetadata','durationchange','timeupdate','seeked'])card.audio.addEventListener(event,updatePlayback,{signal});
  updatePlayback();
  playback.append(steps,seekRange,timecode,card.rateLabel);
  top.append(tabs,badge);root.append(top,playback,notice,panel);parent.append(root);
  card.readerRoot=root;card.workflowBadge=badge;
  const caption=node('p','Нажми на фразу, чтобы услышать её в записи.','reader-caption');
  const toolbar=node('div',undefined,'reader-toolbar');
  const search=node('input');search.type='search';search.placeholder='Найти фразу в тексте';search.setAttribute('aria-label','Найти фразу в расшифровке');search.setAttribute('aria-keyshortcuts','Meta+F Control+F');search.value=state.query;
  const follow=node('input');follow.type='checkbox';follow.checked=state.follow;const followLabel=node('label','Следовать за аудио');followLabel.prepend(follow);follow.onchange=()=>{state.follow=follow.checked};
  const speed=card.rateSelect;
  toolbar.append(search,followLabel);
  const timeline=node('div',undefined,'reader-timeline full-lecture');timeline.tabIndex=0;timeline.setAttribute('aria-label','Текст с таймкодами');card.readerTimeline=timeline;
  const matchCount=node('p','','reader-match-count');matchCount.setAttribute('role','status');
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
  function counts(){buttons.review.firstChild.data='Проверить'+(pending()?' · '+pending():'');}
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
   matchCount.hidden=!query||!visible.length;
   const countLabel=query?'Найдено фрагментов · '+visible.length:'';
   if(matchCount.textContent!==countLabel)matchCount.textContent=countLabel;
   for(const [index,segment] of visible.entries()){
    const row=node('article',undefined,'segment transcript-row'+(segment.needs_review?' needs-review':'')+(segment.reviewed?' is-reviewed':''));
    row.dataset.start=segment.start;row.dataset.end=segment.end;row.dataset.segment=segment.id;
    const line=node('button',undefined,'transcript-line');line.type='button';const timed=Number.isFinite(segment.start);line.setAttribute('aria-label',(timed?clock(segment.start):'Без таймкода')+'. '+segment.text);if(!timed)line.disabled=true;
    const time=node('span',timed?clock(segment.start):'—','transcript-time');time.title=segment.timing==='audio_excerpt'?'Начало аудиофрагмента; время отдельных слов может отличаться':'Слушать с этого момента';
    const copy=node('span',undefined,'transcript-copy');
    if(!query)copy.textContent=segment.text;
    else {
     const text=segment.text,lower=text.toLocaleLowerCase('ru');
     let from=0;
     for(let index=lower.indexOf(query);index!==-1;index=lower.indexOf(query,from)){
      copy.append(text.slice(from,index),node('mark',text.slice(index,index+query.length)));
      from=index+query.length;
     }
     copy.append(text.slice(from));
    }
    line.append(time,copy);
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
   if(report.draft&&report.draft_kind!=='support_quotes'){summary.append(node('h4','Готовим конспект'),node('p','Сначала распознаём запись целиком. Уже готовый текст доступен на вкладке «Текст».','muted'));return summary}
   if(report.overview){if(!report.draft)summary.append(node('h4','Главное за пару'));summary.append(node('p',report.overview))}
   if(report.summary?.length){
    summary.append(node('h4',report.draft?'Опорные цитаты':'Ключевые мысли'));
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
   if(report.draft)return summary;
   if(!report.overview&&!report.summary?.length)summary.append(node('p','Недостаточно разборчивой речи для содержательного конспекта.','muted'));
   if(report.sections?.length){summary.append(node('h4','Темы по времени'));const chapters=node('div',undefined,'reader-chapters');for(const section of report.sections){const b=node('button',clock(section.start)+' · '+section.title,'reader-chapter');b.onclick=()=>{show('text');seek(card,section.start)};chapters.append(b)}summary.append(chapters)}
   if(report.homework?.length){summary.append(node('h4','Что задано'));for(const task of report.homework){const p=node('article');p.append(node('p',task.task));if(task.quote){const quote=node('blockquote',task.quote);p.append(quote)}const b=node('button','Проверить по записи · '+clock(task.start),'reader-chapter');b.onclick=()=>{show('text');seek(card,task.start)};p.append(b);summary.append(p)}}
   if(report.formulas?.length&&typeof formulaRows==='function'){summary.append(node('h4','Формулы из объяснения'));formulaRows(summary,report,card)}
   if(pending())summary.append(node('p','В расшифровке осталось мест для проверки: '+pending()+'. Сверь их со звуком перед подготовкой к занятию.','summary-caution'));
   if(report.overview||report.summary?.length){const exportLink=node('a','Скачать конспект .md','summary-download');exportLink.href='/export/'+encodeURIComponent(name);exportLink.download=name.replace(/\.wav$/,'.md');summary.append(exportLink)}
   return summary;
  }
  function show(tab){
   const previous=state.tab,changed=previous!==tab;
   if(!changed&&panel.hasChildNodes())return;
   const from=changed&&indicator.isConnected&&!reducedMotion.matches?indicator.getBoundingClientRect():null;
   cancelMotion();
   if(timeline.isConnected)state.scroll=timeline.scrollTop;
   state.tab=tab;counts();
   for(const [key,b]of Object.entries(buttons)){b.setAttribute('aria-selected',key===tab?'true':'false');b.tabIndex=key===tab?0:-1}
   panel.setAttribute('aria-labelledby',buttons[tab].id);panel.replaceChildren();
   buttons[tab].append(indicator);
   if(from){
    const to=indicator.getBoundingClientRect(),forward=buttons[previous].compareDocumentPosition(buttons[tab])&Node.DOCUMENT_POSITION_FOLLOWING;
    const easing='cubic-bezier(.2,.72,.2,1)';
    if(to.width>0)indicatorMotion=indicator.animate([
     {transform:'translate('+ (from.left-to.left) +'px,'+ (from.top-to.top) +'px) scaleX('+ (from.width/to.width) +')'},
     {transform:'none'}
    ],{duration:190,easing});
    panelMotion=panel.animate([{opacity:.82,transform:'translateX('+(forward?6:-6)+'px)'},{opacity:1,transform:'none'}],{duration:150,easing});
   }
   if(tab==='summary')panel.append(summary());
   else{caption.textContent=tab==='review'?'Прослушай отмеченные фразы и подтверди те, что проверил.':'Нажми на фразу, чтобы услышать её в записи.';panel.append(toolbar,matchCount,caption);if(tab==='review')panel.append(reviewNavigation);panel.append(timeline,footer);renderRows();timeline.scrollTop=state.scroll;
    if(report.quality?.unassessed)panel.append(node('p','Для '+report.quality.unassessed+' фрагм. оценка качества распознавания недоступна.','reader-caption'));
   }
  }
  search.oninput=()=>{state.query=search.value;reviewIndex=-1;renderRows()};
  search.onkeydown=event=>{
   if(event.key==='Escape'&&search.value){event.preventDefault();event.stopPropagation();search.value='';search.oninput()}
  };
  document.addEventListener('keydown',event=>{
   if(document.querySelector('dialog[open]')||selectedCard!==card||document.body.dataset.view!=='library')return;
   if((event.metaKey||event.ctrlKey)&&!event.shiftKey&&!event.altKey&&event.key.toLowerCase()==='f'){
    event.preventDefault();show('text');search.focus();search.select();
   }
  },{signal});
  const controls={...buttons,search,follow,speed,timeline,play,back,ahead,seek:seekRange,reviewPrevious,reviewNext,reviewInText,download};
  for(const [key,control] of Object.entries(controls))control.dataset.readerControl=key;
  show(state.tab);
  if(previousFocus){
   const anchor=previousFocus.closest('.transcript-row');
   let target=controls[previousFocus.dataset.readerControl];
   if(anchor){
    const row=timeline.querySelector('[data-segment="'+CSS.escape(anchor.dataset.segment)+'"][data-start="'+CSS.escape(anchor.dataset.start)+'"]');
    const peers='button, summary';
    const index=Array.from(anchor.querySelectorAll(peers)).indexOf(previousFocus);
    target=row?.querySelectorAll(peers)[index]||row?.querySelector('.transcript-line');
   }
   (target?.isConnected&&!target.disabled?target:buttons[state.tab]).focus({preventScroll:true});
   if(target===search)search.setSelectionRange(previousFocus.selectionStart,previousFocus.selectionEnd);
  }
 }
 function refreshCard(card,job){
  if(!card.workflowBadge)return;
  const busy=['queued','processing'].includes(job?.status);
  card.workflowBadge.textContent=busy?(job.message||'Обрабатываю запись'):job?.status==='error'?'Разбор прерван · можно повторить':card.workflowBadge.textContent==='Разбор готов'?'Разбор готов':'Текст готов';
 }
 const library=document.querySelector('#view-library');
 const returnBar=node('header',undefined,'reader-page-heading');
 const backToLibrary=node('button','← Библиотека','text-button reader-back');
 backToLibrary.type='button';
 const readingTitle=node('h1'),readingDetail=node('p','','reader-detail');
 readingTitle.tabIndex=-1;
 returnBar.append(backToLibrary,readingTitle,readingDetail);
 returnBar.hidden=true;
 library.prepend(returnBar);
 let selectedCard=null,readerOpener=null,calendarWasOpen=false,recordWasOpen=false;
 const recordTitle=window.RecordingLibrary.title;

 function closeReader(restoreFocus=true){
  if(!selectedCard)return;
  const current=selectedCard;
  selectedCard=null;
  current.audio.pause();
  current.details.open=recordWasOpen;
  current.li.classList.remove('reading-entry');
  library.classList.remove('is-reading');
  returnBar.hidden=true;
  const disclosure=library.querySelector('.library-calendar');
  if(disclosure)disclosure.open=calendarWasOpen;
  if(restoreFocus){
   const item=library.querySelector('.library-entry[data-file="'+CSS.escape(current.name)+'"] .library-open');
   const target=readerOpener?.isConnected&&library.contains(readerOpener)&&readerOpener.getClientRects().length?readerOpener:item||library.querySelector('.library-filters input');
   target?.focus({preventScroll:true});
   target?.scrollIntoView({block:'nearest',behavior:'instant'});
  }
  readerOpener=null;
 }
 backToLibrary.onclick=()=>closeReader();
 document.addEventListener('keydown',event=>{
  if(event.key==='Escape'&&!event.defaultPrevented&&!event.isComposing&&selectedCard&&!document.querySelector('dialog[open]')){
   event.preventDefault();closeReader();
  }
 });
 async function openRecording(name,seconds){
  let card=cards.get(name);
  if(!card){await update();card=cards.get(name)}
  if(!card){document.querySelector('#error').textContent='Запись пока недоступна в библиотеке.';return}
  const source=document.activeElement;
  if(selectedCard!==card){
   closeReader(false);
   readerOpener=source;recordWasOpen=card.details.open;
   calendarWasOpen=Boolean(library.querySelector('.library-calendar')?.open);
  }
  window.showLectureView?.('library',false);
  window.revealCalendarFile?.(name);
  selectedCard=card;
  bindAudio(card);
  card.li.classList.add('reading-entry');card.li.hidden=false;
  const group=card.li.closest('#files>li');
  if(group){group.hidden=false;group.firstElementChild.open=true}
  card.details.open=true;
  readingTitle.textContent=recordTitle(name,card.lesson);
  readingDetail.textContent=window.RecordingLibrary.detail(name,card.lesson||{});
  readingDetail.hidden=!readingDetail.textContent;
  returnBar.hidden=false;library.classList.add('is-reading');
  readingTitle.focus({preventScroll:true});
  window.scrollTo({top:0,behavior:'instant'});
  if(Number.isFinite(seconds))seek(card,seconds);
  update();
 }

 function initImport(){
  const host=document.querySelector('#capture-file');
  const form=node('form',undefined,'lecture-import');form.id='lecture-import';
  const drop=node('div',undefined,'import-drop');
  const dropCopy=node('div',undefined,'import-drop-copy');
  const titlePrompt=node('h2','Перетащи сюда аудиофайл');
  const filename=node('span','M4A, MP3, WAV и другие форматы · до 2 ГБ','import-filename');
  dropCopy.append(titlePrompt,filename);
  const picker=node('input');picker.type='file';picker.id='lecture-audio-file';picker.hidden=true;
  picker.accept='audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg,.opus,.webm,.mp4,.caf,.aif,.aiff';
  picker.setAttribute('aria-label','Выбрать аудиозапись');
  const choose=node('button','Выбрать файл','import-choose');choose.type='button';choose.onclick=()=>picker.click();
  const uploadIcon=document.createElementNS('http://www.w3.org/2000/svg','svg');
  uploadIcon.setAttribute('viewBox','0 0 24 24');uploadIcon.setAttribute('class','upload-icon');uploadIcon.setAttribute('aria-hidden','true');
  uploadIcon.innerHTML='<path d="M12 15V3m-4.5 4.5L12 3l4.5 4.5M4 14v4.5A2.5 2.5 0 0 0 6.5 21h11a2.5 2.5 0 0 0 2.5-2.5V14"/>';
  drop.append(uploadIcon,dropCopy,choose,picker);
  const about=node('p','Расшифровка и конспект сохранятся в библиотеке этого Mac.','import-about');
  const metadata=node('details',undefined,'import-metadata');
  metadata.append(node('summary','Название, предмет и дата'));
  const fields=node('div',undefined,'import-fields');
  function field(caption,type,id){
   const label=node('label',caption),input=node('input');input.type=type;input.id=id;input.maxLength=160;
   label.append(input);fields.append(label);return input;
  }
  const title=field('Название','text','import-title'),subject=field('Предмет','text','import-subject'),date=field('Дата занятия','date','import-date');
  subject.placeholder='Необязательно';metadata.append(fields);metadata.hidden=true;
  const localDate=()=>{const d=new Date();return [d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-')};
  date.value=localDate();
  const actions=node('div',undefined,'import-actions');
  const submit=node('button','Сохранить и распознать');submit.type='submit';submit.disabled=true;
  const cancel=node('button','Отменить загрузку','secondary');cancel.type='button';cancel.hidden=true;
  actions.append(submit,cancel);actions.hidden=true;
  const progress=node('progress');progress.max=100;progress.hidden=true;progress.setAttribute('aria-label','Загрузка записи');
  const message=node('p','','import-message');message.setAttribute('role','status');
  const current=node('section',undefined,'current-import');current.hidden=true;current.tabIndex=-1;current.setAttribute('aria-label','Состояние импорта');
  const statusText=node('div',undefined,'import-status-copy');statusText.setAttribute('role','status');
  const saved=node('strong'),stage=node('p');statusText.append(saved,stage);
  const currentAction=node('button','','secondary');currentAction.type='button';currentAction.hidden=true;
  current.append(statusText,currentAction);
  form.append(drop,metadata,actions,progress,message,about,current);host.append(form);
  const history=node('details',undefined,'card import-history');
  history.hidden=true;history.append(node('summary','История импорта'));
  const jobs=node('div',undefined,'import-jobs');history.append(jobs);
  library.querySelector('.library-calendar').before(history);
  let selected=null,xhr=null,currentId='',previousTitle='',lastStamp='',historyStamp='',polling=false;
  try{currentId=sessionStorage.getItem('lecture-current-import')||''}catch{}
  const setText=(element,value)=>{if(element.textContent!==value)element.textContent=value};
  function select(file){
   if(xhr||!file)return;
   form.classList.remove('import-complete');selected=file;
   const name=file.name.replace(/\.[^.]+$/,'');
   if(!title.value||title.value===previousTitle)title.value=name;
   previousTitle=name;
   const mb=file.size/1024**2;
   titlePrompt.textContent=file.name;filename.textContent=mb<1?Math.ceil(file.size/1024)+' КБ':mb.toLocaleString('ru',{maximumFractionDigits:1})+' МБ';
   choose.textContent='Заменить файл';choose.classList.add('secondary');
   drop.classList.add('has-file');metadata.hidden=actions.hidden=false;submit.disabled=false;
   message.textContent='';about.hidden=true;current.hidden=true;
  }
  picker.onchange=()=>select(picker.files[0]);
  drop.ondragover=event=>{if(Array.from(event.dataTransfer.types).includes('Files')){event.preventDefault();drop.classList.add('drag-over')}};
  drop.ondragleave=event=>{if(!drop.contains(event.relatedTarget))drop.classList.remove('drag-over')};
  drop.ondrop=event=>{event.preventDefault();drop.classList.remove('drag-over');select(event.dataTransfer.files[0])};
  cancel.onclick=()=>xhr?.abort();
  function clearFile(){
   selected=null;previousTitle='';picker.value='';title.value='';subject.value='';date.value=localDate();
   titlePrompt.textContent='Перетащи сюда аудиофайл';filename.textContent='M4A, MP3, WAV и другие форматы · до 2 ГБ';
   choose.textContent='Выбрать файл';choose.classList.remove('secondary');drop.classList.remove('has-file');
   metadata.open=false;metadata.hidden=actions.hidden=true;
  }
  const openImport=(pick=false)=>{
   window.showLectureView?.('record');window.selectCaptureMode?.('file');
   choose.focus({preventScroll:true});if(pick===true&&!xhr)picker.click();
  };
  refreshLibrary=window.mountRecordingLibrary(library.querySelector('.view-intro'),openRecording,openImport);
  document.addEventListener('keydown',event=>{
   if((event.metaKey||event.ctrlKey)&&!event.altKey&&!event.shiftKey&&event.key.toLowerCase()==='o'&&!document.querySelector('dialog[open]')){
    event.preventDefault();openImport(true);
   }
  });
  function presentation(job){
   const lesson=studyStatus?.lessons?.[job.file]||{},ai=studyStatus?.ai?.jobs?.[job.file];
   if(job.status==='error')return ['error',job.message||'Не удалось подготовить запись'];
   if(job.status==='ready'&&(ai||lesson.has_summary||lesson.has_draft)){
    const [state,description]=window.RecordingLibrary.status(lesson,ai||{});
    const percent=ai?.status==='processing'&&Number.isFinite(ai.percent)?' · '+Math.round(Math.max(0,Math.min(100,ai.percent)))+'%':'';
    return [state,description+percent];
   }
   if(job.status==='ready')return ['saved',job.analyze?'В очереди на разбор':'Аудио доступно для прослушивания'];
   if(job.status==='scheduling')return ['active','Добавляем запись в библиотеку'];
   return ['active','Готовим звук к распознаванию'];
  }
  const retry=async(job,button)=>{
   button.disabled=true;
   try{await post('/imports/retry',{id:job.id});lastStamp='';await poll()}
   catch(error){message.textContent=error.message}
   finally{button.disabled=false}
  };
  function renderCurrent(job){
   if(selected||!job)return;
   const [state,description]=presentation(job);
   form.classList.add('import-complete');
   choose.textContent='Добавить ещё файл';
   current.hidden=false;about.hidden=true;current.dataset.state=state;
   setText(saved,'Файл сохранён на Mac');
   setText(stage,(job.title||job.name)+' · '+description);
   const ready=job.status==='ready',failed=job.status==='error';
   currentAction.hidden=!ready&&!failed;
   setText(currentAction,failed?'Повторить подготовку':'Открыть в библиотеке');
   currentAction.onclick=failed?()=>retry(job,currentAction):()=>openRecording(job.file);
  }
  function renderHistory(list){
   history.hidden=!list.length;
   const focused=jobs.contains(document.activeElement)?document.activeElement.closest('[data-job]')?.dataset.job:null;
   jobs.replaceChildren();
   for(const job of list.slice(0,5)){
    const row=node('article',undefined,'import-job');row.dataset.job=job.id;
    const copy=node('div');copy.append(node('strong',job.title||job.name),node('p',presentation(job)[1],'muted'));row.append(copy);
    if(job.status==='error'||job.status==='ready'){
     const failed=job.status==='error',button=node('button',failed?'Повторить':'Открыть','secondary');button.type='button';
     button.onclick=failed?()=>retry(job,button):()=>openRecording(job.file);row.append(button);
    }
    jobs.append(row);
   }
   if(focused)jobs.querySelector('[data-job="'+CSS.escape(focused)+'"] button')?.focus({preventScroll:true});
  }
  async function poll(){
   if(polling)return;polling=true;
   try{
    const response=await fetch('/imports',{cache:'no-store'});if(!response.ok)return;
    const list=(await response.json()).jobs||[];
    const relevant=list.find(job=>job.id===currentId);
    if(relevant&&!selected){
     if(relevant.status==='ready'&&!cards.has(relevant.file))await update();
     const key=JSON.stringify([relevant,presentation(relevant)]);
     if(key!==lastStamp){lastStamp=key;renderCurrent(relevant)}
    }
    const historyKey=JSON.stringify(list.slice(0,5).map(job=>[job.id,job.status,presentation(job)]));
    if(historyKey!==historyStamp){historyStamp=historyKey;renderHistory(list)}
   }catch{}finally{polling=false}
  }
  form.onsubmit=event=>{
   event.preventDefault();if(!selected||xhr)return;
   if(!selected.size||selected.size>2*1024**3){message.textContent='Выбери непустую запись размером до 2 ГБ.';return}
   const params=new URLSearchParams({name:selected.name,title:title.value,subject:subject.value,date:date.value,analyze:'1'});
   const restoreFocus=form.contains(document.activeElement);
   const request=new XMLHttpRequest();xhr=request;submit.disabled=choose.disabled=true;
   for(const input of fields.querySelectorAll('input'))input.disabled=true;
   cancel.hidden=progress.hidden=false;progress.value=0;message.textContent='Сохраняем файл на Mac…';
   request.open('POST','/import-audio?'+params);request.setRequestHeader('Content-Type','application/octet-stream');request.timeout=30*60*1000;
   request.upload.onprogress=e=>{if(e.lengthComputable){progress.value=100*e.loaded/e.total;message.textContent='Сохраняем файл на Mac · '+Math.round(progress.value)+'%'}};
   request.onload=()=>{
    let value={};try{value=JSON.parse(request.responseText)}catch{}
    if(request.status<200||request.status>=300||!value.id){message.textContent=value.error||'Не удалось сохранить запись. Попробуй ещё раз.';return}
    const chosenTitle=title.value||selected.name,original=selected.name;
    currentId=value.id;
    try{sessionStorage.setItem('lecture-current-import',currentId)}catch{}
    clearFile();message.textContent=value.duplicate?'Эта запись уже есть в библиотеке.':'';
    lastStamp='';renderCurrent({id:currentId,file:value.file,title:chosenTitle,name:original,status:value.status,analyze:true});
    update().then(poll);
   };
   request.onerror=()=>{message.textContent='Связь прервалась. Повтори загрузку с этим файлом.'};
   request.ontimeout=request.onerror;
   request.onabort=()=>{message.textContent='Загрузка отменена. Можно снова сохранить этот файл.'};
   request.onloadend=()=>{
    xhr=null;choose.disabled=false;submit.disabled=!selected;cancel.hidden=progress.hidden=true;
    for(const input of fields.querySelectorAll('input'))input.disabled=false;
    if(!selected&&restoreFocus&&current.getClientRects().length&&(document.activeElement===document.body||form.contains(document.activeElement)))current.focus({preventScroll:true});
   };
   request.send(selected);
  };
  const loop=async()=>{if(!document.hidden)await poll();setTimeout(loop,2000)};loop();
 }
 let refreshLibrary=()=>{};
 window.LectureWorkflow={renderReader,refreshCard,seek,clock,recordTitle,openRecording,closeReader,bindAudio,pauseLibrary,refreshLibrary:status=>{refreshLibrary(status);if(selectedCard&&!cards.has(selectedCard.name))closeReader()}};
 initImport();
})();
