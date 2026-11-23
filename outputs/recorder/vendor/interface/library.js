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

 function readFavorites(){
  try{
   const saved=JSON.parse(localStorage.getItem(favoriteKey));
   if(Array.isArray(saved))return new Set(saved.filter(name=>typeof name==='string'));
  }catch{}
  return new Set();
 }

 function entry(name,meta){
  const title=meta.title||meta.topic||meta.subject||meta.label||name;
  const date=String(meta.date||name.match(/^lecture-(\d{4}-\d{2}-\d{2})/)?.[1]||'');
  const dateLabel=date.replace(/^(\d{4})-(\d{2})-(\d{2})$/,'$3.$2.$1');
  const teachers=[meta.teacher,...(Array.isArray(meta.teachers)?meta.teachers:[])].filter(Boolean);
  const detail=[meta.subject!==title&&meta.subject,dateLabel].filter(Boolean).join(' · ');
  const text=normalized([name,title,meta.original_name,meta.topic,meta.subject,meta.label,meta.folder,date,dateLabel,...teachers].filter(Boolean).join(' '));
  return {name,title,detail,text};
 }

 window.mountRecordingLibrary=(anchor,openRecording,openImport)=>{
  const panel=element('section','card library-catalog');
  panel.hidden=true;panel.setAttribute('aria-labelledby','library-catalog-title');
  const header=element('header','library-catalog-head');
  const title=element('h3',null,'Аудиозаписи');title.id='library-catalog-title';
  const count=element('span','library-catalog-count');count.setAttribute('role','status');
  header.append(title,count);
  const filters=element('div','library-filters');filters.setAttribute('role','search');filters.setAttribute('aria-label','Поиск записей');
  const search=element('input');search.type='search';search.placeholder='Название, предмет, преподаватель или дата';
  search.setAttribute('aria-label','Найти запись в библиотеке');search.setAttribute('aria-keyshortcuts','Meta+K Control+K');search.id='library-recording-search';
  const favorites=element('button','secondary library-filter','Избранное');favorites.type='button';favorites.setAttribute('aria-pressed','false');
  filters.append(search,favorites);
  const list=element('ul','library-results');list.setAttribute('aria-label','Записи библиотеки');
  const empty=element('div','library-catalog-empty'),hint=element('span'),reset=element('button','secondary');
  reset.type='button';empty.append(hint,reset);
  const more=element('button','secondary library-more','Показать ещё');more.type='button';
  panel.append(header,filters,list,empty,more);anchor.before(panel);
  let pinned=readFavorites(),onlyPinned=false,limit=pageSize,entries=[],stamp;
  const rowByName=new Map();

  function createRow(name){
   const li=element('li','library-entry');li.dataset.file=name;
   const open=element('button','library-open');open.type='button';
   const heading=element('strong'),detail=element('small');open.append(heading,detail);
   open.onclick=()=>openRecording(name);
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
   li.append(open,favorite);
   return {li,open,heading,detail,favorite,icon};
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
    row.heading.textContent=item.title;row.detail.textContent=item.detail;row.detail.hidden=!item.detail;
    const selected=pinned.has(item.name);
    row.favorite.setAttribute('aria-pressed',String(selected));
    row.favorite.title=(selected?'Убрать из избранного':'В избранное')+' · '+item.title;
    row.favorite.setAttribute('aria-label',row.favorite.title);
    row.icon.textContent=selected?'★':'☆';
    if(list.children[index]!==row.li)list.insertBefore(row.li,list.children[index]||null);
   }
   favorites.setAttribute('aria-pressed',String(onlyPinned));
   const tally=terms.length||onlyPinned?'Найдено '+matches.length+' из '+entries.length:'Всего '+entries.length;
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
   if((e.metaKey||e.ctrlKey)&&!e.altKey&&!e.shiftKey&&e.key.toLowerCase()==='k'&&!panel.closest('[hidden]')&&!document.querySelector('dialog[open]')){
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
    .map(name=>entry(name,status.lessons?.[name]||{}));
   const key=JSON.stringify(next);
   if(key===stamp)return;
   stamp=key;entries=next;panel.hidden=false;render();
  };
 };
})();
