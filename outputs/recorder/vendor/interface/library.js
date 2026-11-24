(() => {
 'use strict';

 const element=(tag,classname,text)=>{
  const item=document.createElement(tag);
  if(classname)item.className=classname;
  if(text!==undefined)item.textContent=text;
  return item;
 };
 const normalized=value=>String(value??'').toLocaleLowerCase('ru').replaceAll('ё','е').trim();
 const favoriteKey='lecture-library-favorites';
 const pageSize=6;
 const dateFormat=new Intl.DateTimeFormat('ru',{day:'numeric',month:'long',year:'numeric'});

 function readFavorites(){
  try{
   const saved=JSON.parse(localStorage.getItem(favoriteKey));
   if(Array.isArray(saved))return new Set(saved.filter(name=>typeof name==='string'));
  }catch{}
  return new Set();
 }

 function recordTitle(name,meta={}){
  meta=meta||{};
  const generated=meta.topic==='Тема пока не определена'?'':meta.topic;
  const time=name.match(/^lecture-\d{4}-\d{2}-\d{2}-(\d{2})-(\d{2})/);
  return meta.title||generated||meta.original_name?.replace(/\.[^.]+$/,'')||meta.subject||meta.label||(time?'Запись в '+time[1]+':'+time[2]:name);
 }

 function recordDetail(name,meta={}){
  const date=String(meta.date||name.match(/^lecture-(\d{4}-\d{2}-\d{2})/)?.[1]||'');
  const moment=new Date(date+'T12:00:00');
  const dateLabel=Number.isNaN(moment.getTime())?date:dateFormat.format(moment).replace(/ г\.$/,'');
  const title=recordTitle(name,meta);
  const subject=meta.subject!=='Загруженная запись'&&meta.subject!==title&&meta.subject;
  return [subject,dateLabel].filter(Boolean).join(' · ');
 }

 function recordStatus(meta={},job={}){
  if(job.status==='error')return ['error','Разбор прерван'];
  if(job.status==='processing')return ['active',job.message||'Распознаём запись'];
  if(job.status==='queued')return ['active',job.message||'В очереди на разбор'];
  if(job.status==='done'||meta.has_summary)return ['ready','Разбор готов'];
  if(job.status==='transcribed'||meta.has_draft)return ['ready','Текст доступен'];
  return ['saved','Аудио сохранено'];
 }

 function entry(name,meta,job){
  const title=recordTitle(name,meta),detail=recordDetail(name,meta);
  const date=String(meta.date||name.match(/^lecture-(\d{4}-\d{2}-\d{2})/)?.[1]||'');
  const dateLabel=date.replace(/^(\d{4})-(\d{2})-(\d{2})$/,'$3.$2.$1');
  const teachers=[meta.teacher,...(Array.isArray(meta.teachers)?meta.teachers:[])].filter(Boolean);
  const text=normalized([name,title,detail,meta.original_name,meta.topic,meta.subject,meta.label,meta.folder,date,dateLabel,...teachers].filter(Boolean).join(' '));
  return {name,title,detail,text,state:recordStatus(meta,job)};
 }
 window.RecordingLibrary={title:recordTitle,detail:recordDetail,status:recordStatus};
 window.mountRecordingLibrary=(anchor,openRecording,openImport)=>{
  const panel=element('section','card library-catalog');
  panel.hidden=true;panel.setAttribute('aria-label','Аудиозаписи');
  const header=element('header','library-catalog-head');
  const count=element('span','library-catalog-count');count.setAttribute('role','status');
  const add=element('button','secondary library-add','Добавить аудио');add.type='button';add.onclick=openImport;
  anchor.append(add);
  header.append(count);
  const filters=element('div','library-filters');filters.setAttribute('role','search');filters.setAttribute('aria-label','Поиск записей');
  const search=element('input');search.type='search';search.placeholder='Название, предмет, преподаватель…';
  search.setAttribute('aria-label','Найти запись в библиотеке');search.setAttribute('aria-keyshortcuts','Meta+K Control+K');search.id='library-recording-search';
  const favorites=element('button','secondary library-filter','Избранное');favorites.type='button';favorites.setAttribute('aria-pressed','false');
  filters.append(search,favorites);
  const list=element('ul','library-results');list.setAttribute('aria-label','Записи библиотеки');
  const empty=element('div','library-catalog-empty'),hint=element('span'),reset=element('button','secondary');
  reset.type='button';empty.append(hint,reset);
  const more=element('button','secondary library-more','Показать ещё');more.type='button';
  panel.append(filters,header,list,empty,more);anchor.after(panel);
  panel.after(document.querySelector('.library-search-tools'));
  let pinned=readFavorites(),onlyPinned=false,limit=pageSize,entries=[],stamp;
  const rowByName=new Map(),recentRows=new Map();
  const recent=element('section','recent-lectures');recent.hidden=true;
  const recentHead=element('header','recent-head'),recentTitle=element('h2',null,'Недавние лекции');
  const viewAll=element('button','text-button','Вся библиотека →');viewAll.type='button';viewAll.onclick=()=>{window.showLectureView('library');search.focus({preventScroll:true})};
  const recentList=element('ul','library-results'),recentEmpty=element('p','recent-empty','Здесь появится первая сохранённая лекция.');
  recentHead.append(recentTitle,viewAll);recent.append(recentHead,recentList,recentEmpty);
  document.querySelector('#view-record').append(recent);

  function makeOpen(name){
   const open=element('button','library-open');open.type='button';open.onclick=()=>openRecording(name);
   const heading=element('strong'),detail=element('small'),copy=element('span','entry-copy');
   const state=element('span','entry-state');
   copy.append(heading,detail);open.append(copy,state);
   return {open,heading,detail,state};
  }
  function populate(row,item){
   row.heading.textContent=item.title;row.detail.textContent=item.detail;row.detail.hidden=!item.detail;
   row.state.dataset.state=item.state[0];row.state.textContent=item.state[1];
  }
  function renderRecent(){
   const visible=entries.slice(0,3),names=new Set(visible.map(item=>item.name));
   for(const [name,row] of recentRows)if(!names.has(name)){row.li.remove();recentRows.delete(name)}
   for(const [i,item] of visible.entries()){
    let row=recentRows.get(item.name);
    if(!row){const li=element('li','library-entry');row={li,...makeOpen(item.name)};li.append(row.open);recentRows.set(item.name,row)}
    populate(row,item);
    if(recentList.children[i]!==row.li)recentList.insertBefore(row.li,recentList.children[i]||null);
   }
   recent.hidden=false;recentEmpty.hidden=visible.length>0;recentList.hidden=!visible.length;
  }

  function createRow(name){
   const li=element('li','library-entry');li.dataset.file=name;
   const row=makeOpen(name);
   const favorite=element('button','secondary library-star');favorite.type='button';
   const icon=element('span');icon.setAttribute('aria-hidden','true');favorite.append(icon);
   favorite.onclick=()=>{
    const moveFocus=onlyPinned&&document.activeElement===favorite;
    const next=li.nextElementSibling||li.previousElementSibling;
    if(pinned.has(name))pinned.delete(name);else pinned.add(name);
    try{localStorage.setItem(favoriteKey,JSON.stringify([...pinned]));}catch{}
    render();
    if(moveFocus)(next?.isConnected&&next.querySelector('.library-star')||favorites).focus({preventScroll:true});
   };
   li.append(row.open,favorite);
   return {li,...row,favorite,icon};
  }

  function render(){
   const terms=normalized(search.value).split(/\s+/).filter(Boolean);
   const matches=entries.filter(item=>(!onlyPinned||pinned.has(item.name))&&terms.every(term=>item.text.includes(term)));
   const visible=matches.slice(0,limit);
   const names=new Set(visible.map(item=>item.name));
   for(const [name,row] of rowByName)if(!names.has(name)){row.li.remove();rowByName.delete(name)}
   for(const [index,item] of visible.entries()){
    let row=rowByName.get(item.name);
    if(!row){row=createRow(item.name);rowByName.set(item.name,row)}
    populate(row,item);
    const selected=pinned.has(item.name);
    row.favorite.setAttribute('aria-pressed',String(selected));
    row.favorite.title=(selected?'Убрать из избранного':'В избранное')+' · '+item.title;
    row.favorite.setAttribute('aria-label',row.favorite.title);
    row.icon.textContent=selected?'★':'☆';
    if(list.children[index]!==row.li)list.insertBefore(row.li,list.children[index]||null);
   }
   favorites.setAttribute('aria-pressed',String(onlyPinned));
   const tally=terms.length||onlyPinned?'Найдено '+matches.length+' из '+entries.length:'Всего записей · '+entries.length;
   if(count.textContent!==tally)count.textContent=tally;
   more.hidden=matches.length<=limit;
   empty.hidden=matches.length>0;
   if(!matches.length){
    hint.textContent=!entries.length?'Аудиозаписей пока нет.':onlyPinned&&!terms.length?'В избранном пока пусто.':'По этому запросу записей нет.';
    reset.textContent=entries.length?'Сбросить фильтры':'Импортировать аудио';
   }
  }
  search.addEventListener('input',()=>{limit=pageSize;render()});
  search.addEventListener('keydown',e=>{
   if(e.key==='Escape'&&search.value){e.preventDefault();e.stopPropagation();search.value='';limit=pageSize;render()}
  });
  document.addEventListener('keydown',e=>{
   if((e.metaKey||e.ctrlKey)&&!e.altKey&&!e.shiftKey&&e.key.toLowerCase()==='k'&&panel.getClientRects().length>0&&!panel.closest('[hidden]')&&!document.querySelector('dialog[open]')){
    e.preventDefault();search.focus();search.select();
   }
  });
  favorites.onclick=()=>{onlyPinned=!onlyPinned;limit=pageSize;render()};
  reset.onclick=()=>{
   if(!entries.length){openImport();return}
   onlyPinned=false;search.value='';limit=pageSize;render();search.focus();
  };
  more.onclick=()=>{
   const previous=list.children.length;
   limit+=pageSize;render();
   list.children[previous]?.querySelector('.library-open')?.focus({preventScroll:true});
  };
  window.addEventListener('storage',event=>{
   if(event.key===favoriteKey||event.key===null){pinned=readFavorites();render()}
  });
  return status=>{
   const next=(status.files||[]).filter(name=>name!==status.file||(!status.recording&&!status.busy))
    .map(name=>entry(name,status.lessons?.[name]||{},status.ai?.jobs?.[name]||{}));
   const key=JSON.stringify(next);
   if(key===stamp)return;
   stamp=key;entries=next;panel.hidden=false;render();renderRecent();
  };
 };
})();
