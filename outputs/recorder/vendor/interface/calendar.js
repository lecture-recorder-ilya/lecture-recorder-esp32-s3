/* Date arithmetic is independent of the browser's local timezone. */
function calendarShift(day, amount){const value=new Date(day+'T12:00:00Z');value.setUTCDate(value.getUTCDate()+amount);return value.toISOString().slice(0,10)}
function calendarMonday(day){const value=new Date(day+'T12:00:00Z');return calendarShift(day,-((value.getUTCDay()+6)%7))}
function calendarFolder(entry){return entry.folder||`${entry.date} ${entry.start.replace(':','-')} — ${entry.subject} — ${entry.type}`.replace(/[/\\\0]/g,'-')}
function calendarTopFiles(status){const covered=new Set();for(const name of status.files||[]){const meta=status.lessons?.[name];for(const source of meta?.source_records||[])covered.add(source)}return (status.files||[]).filter(name=>!covered.has(name))}
function calendarFiles(status,entry,originals=false){const folder=calendarFolder(entry);return (originals?status.files||[]:calendarTopFiles(status)).filter(name=>status.lessons?.[name]?.folder===folder)}
if(typeof module!=='undefined')module.exports={calendarShift,calendarMonday,calendarFolder,calendarFiles};
if(typeof document!=='undefined')(() => {
 const library=document.querySelector('#view-library'), files=document.querySelector('#files'), title=files.previousElementSibling;
 const node=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls;if(text!==undefined)e.textContent=text;return e};
 const button=(text,action,cls='secondary')=>{const e=node('button',cls,text);e.type='button';e.onclick=action;return e};
 const calendar=node('section','card calendar-card');library.insertBefore(calendar,title);
 const head=node('div','calendar-head'), label=node('h2','','Пары'), group=node('span','muted');head.append(label,group);
 const modes=node('div','calendar-modes');for(const [key,text] of [['day','День'],['week','Неделя'],['month','Месяц']]){
  const b=button(text,()=>{mode=key;render()},'secondary');b.dataset.mode=key;modes.append(b);
 }
 const navigation=node('div','calendar-navigation');const dateLabel=node('strong','');
 navigation.append(button('←',()=>navigate(-1)),dateLabel,button('Сегодня',()=>chooseDay(today())),button('→',()=>navigate(1)));
 navigation.firstChild.setAttribute('aria-label','Предыдущая неделя или месяц');navigation.lastChild.setAttribute('aria-label','Следующая неделя или месяц');
 const dates=node('div','calendar-dates'), pairs=node('div','calendar-pairs'), hint=node('p','muted','Выбери пару — ниже появятся её темы и конспекты.');
 calendar.append(head,modes,navigation,dates,pairs,hint);
 const selectedInfo=node('div','selected-lesson');library.insertBefore(selectedInfo,title);
 const empty=node('p','card calendar-empty');library.insertBefore(empty,files);
 const archiveActions=node('div','archive-actions');const originalsButton=button('Показать исходные отрывки',()=>{showOriginals=!showOriginals;render()});archiveActions.append(button('Все занятия',()=>{selected='all';render()}),originalsButton);title.after(archiveActions);
 let schedule=null,status=null,mode='day',day='',selected=null,stamp='',showOriginals=false,autoOpenedSelection='';
 const format=(iso,options)=>new Intl.DateTimeFormat('ru',{timeZone:'UTC',...options}).format(new Date(iso+'T12:00:00Z'));
 function today(){return new Intl.DateTimeFormat('sv-SE',{timeZone:schedule?.timezone||'Europe/Moscow',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date())}
 const entriesOn=value=>(schedule?.entries||[]).filter(e=>e.date===value).sort((a,b)=>a.start.localeCompare(b.start));
 const scheduledFolders=()=>new Set((schedule?.entries||[]).map(calendarFolder));
 function othersOn(value,originals=false){const known=scheduledFolders();return (originals?status?.files||[]:calendarTopFiles(status||{})).filter(name=>status.lessons?.[name]?.date===value&&!known.has(status.lessons[name].folder))}
 function chooseDay(value){day=value;const entries=entriesOn(day);const entry=entries.find(e=>calendarFiles(status||{},e).length)||entries[0];selected=entry?calendarFolder(entry):'other';render()}
 function navigate(direction){
  if(mode==='month'){const value=new Date(day+'T12:00:00Z');value.setUTCDate(1);value.setUTCMonth(value.getUTCMonth()+direction);chooseDay(value.toISOString().slice(0,10))}
  else chooseDay(calendarShift(day,direction*7));
 }
 function dateButton(value,month=false){
  const b=button('' ,()=>chooseDay(value),'calendar-date');b.setAttribute('aria-label',format(value,{weekday:'long',day:'numeric',month:'long',year:'numeric'}));b.setAttribute('aria-pressed',String(value===day));
  b.append(node('small','',format(value,{weekday:'short'})),node('strong','',format(value,{day:'numeric'})));
  const count=entriesOn(value).reduce((sum,entry)=>sum+calendarFiles(status||{},entry).length,0)+othersOn(value).length;
  if(count){b.classList.add('has-recordings');b.append(node('span','calendar-dot',String(count)+' зап.'))}
  if(value===today())b.classList.add('is-today');if(month&&value.slice(0,7)!==day.slice(0,7))b.classList.add('outside-month');return b;
 }
 function pairButton(entry,compact=false){
  const folder=calendarFolder(entry), names=calendarFiles(status||{},entry), active=!!status?.recording&&names.includes(status.file);
  const b=button('',()=>{day=entry.date;selected=folder;render()},'pair-button');b.setAttribute('aria-pressed',String(selected===folder));
  const time=node('span','pair-time',entry.start+'–'+entry.end), text=node('span','pair-copy');text.append(node('strong','',entry.subject),node('small','',entry.type));
  if(!compact){const details=(entry.variants||[]).map(v=>[v.room,v.building,v.teacher].filter(Boolean).join(' · '));text.append(node('small','', [...new Set(details)].join(' / ')))}
  b.append(time,text,node('span','pair-badge',active?'Идёт запись':names.length?names.length+' зап.':'Нет записей'));if(names.length)b.classList.add('has-recordings');return b;
 }
 function render(){
  if(!schedule||!day)return;
  group.textContent=schedule.group;dateLabel.textContent=format(day,{month:'long',year:'numeric'});
  modes.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.mode===mode)));
  dates.replaceChildren();pairs.replaceChildren();dates.className='calendar-dates '+(mode==='month'?'month-grid':'week-strip');
  if(mode==='month'){
   const start=calendarMonday(day.slice(0,8)+'01');for(let i=0;i<42;i++)dates.append(dateButton(calendarShift(start,i),true));
  }else{const start=calendarMonday(day);for(let i=0;i<7;i++)dates.append(dateButton(calendarShift(start,i)))}
  if(mode==='week'){
   pairs.className='calendar-pairs week-pairs';const start=calendarMonday(day);
   for(let i=0;i<7;i++){const value=calendarShift(start,i), column=node('div','week-column');column.append(node('h3','',format(value,{weekday:'short',day:'numeric'})));for(const e of entriesOn(value))column.append(pairButton(e,true));if(!entriesOn(value).length)column.append(node('small','muted','Нет пар'));pairs.append(column)}
  }else{
   pairs.className='calendar-pairs';pairs.append(node('h3','',format(day,{weekday:'long',day:'numeric',month:'long'})));
   const entries=entriesOn(day);for(const entry of entries)pairs.append(pairButton(entry));if(!entries.length)pairs.append(node('p','muted','В этот день пар в загруженном расписании нет.'));
  }
  const other=othersOn(day);if(other.length){const b=button('Другие записи за день · '+other.length,()=>{selected='other';render()},'secondary');b.setAttribute('aria-pressed',String(selected==='other'));pairs.append(b)}
  filterRecords();
 }
 function filterRecords(){
  const entry=(schedule.entries||[]).find(e=>calendarFolder(e)===selected);
  const names=selected==='all'?(showOriginals?status?.files||[]:calendarTopFiles(status||{})):selected==='other'?othersOn(day,showOriginals):entry?calendarFiles(status||{},entry,showOriginals):[];
  const finished=names, allowedFolders=new Set(finished.map(name=>status.lessons?.[name]?.folder));
  for(const [key,value] of lessonGroups){value.li.hidden=!allowedFolders.has(key);if(selected!=='all'&&!value.li.hidden)value.li.firstElementChild.open=true}
  for(const [name,card] of cards)card.li.hidden=!finished.includes(name);
  const autoKey=selected+'|'+finished.join(',');if(autoOpenedSelection!==autoKey){autoOpenedSelection=autoKey;if(selected!=='all'&&finished.length===1)cards.get(finished[0]).details.open=true}
  originalsButton.textContent=showOriginals?'Скрыть исходные отрывки':'Показать исходные отрывки';originalsButton.setAttribute('aria-pressed',String(showOriginals));originalsButton.hidden=!(status?.files||[]).some(name=>status.lessons?.[name]?.merged_parts);
  title.textContent=selected==='all'?'Все конспекты':entry?'Содержание пары':'Конспекты за день';
  selectedInfo.replaceChildren();
  if(entry){selectedInfo.append(node('h3','',entry.subject),node('p','muted',format(entry.date,{day:'numeric',month:'long'})+' · '+entry.start+'–'+entry.end+' · '+entry.type))}
  empty.hidden=finished.length>0;
  if(!empty.hidden){
   empty.textContent=status?.recording&&names.includes(status.file)?'Пара сейчас записывается. После завершения здесь появится её конспект.':'Материалов этой пары пока нет. Запиши занятие, чтобы получить конспект.';
   if(!entry&&selected!=='all')empty.textContent='За этот день пока нет записей.';
  }
 }
 window.refreshLectureCalendar=value=>{
  status=value;if(!schedule)return;
  const next=JSON.stringify([value.files,value.lessons,value.recording,value.file]);if(stamp===next)return;stamp=next;
  if(!day)chooseDay(today());else render();
 };
 window.revealCalendarFile=name=>{
  const meta=status?.lessons?.[name];if(!meta)return;day=meta.date;selected=meta.folder;const matching=(schedule?.entries||[]).some(e=>calendarFolder(e)===selected);if(!matching)selected='other';render();
 };
 let requestNumber=0;
 window.refreshScheduleData=async()=>{
  const request=++requestNumber;
  try{
   const response=await fetch('/calendar',{cache:'no-store'});
   if(!response.ok)throw Error('Расписание недоступно');
   const value=await response.json();
   if(request!==requestNumber)return;
   schedule=value;
   status=studyStatus||status;
   chooseDay(day||today());
   hint.textContent=value.error||'Выбери пару — ниже появятся её темы и конспекты.';
  }catch(error){
   if(request!==requestNumber)return;
   hint.textContent=error.message;
   if(!schedule){schedule={entries:[],group:''};chooseDay(today());}
  }
 };
 window.refreshScheduleData();
})();
