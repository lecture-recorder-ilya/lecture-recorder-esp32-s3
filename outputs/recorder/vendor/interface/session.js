(() => {
 const profileDialog=$('#mirea-profile-dialog');
 const selectionDialog=$('#recording-selection-dialog');
 const profileForm=$('#mirea-profile-form');
 const selectionForm=$('#selection-form');
 const groupField=$('#mirea-group');
 const courseField=$('#mirea-course');
 const choices=$('#selection-choices');
 const manual=$('#selection-manual');
 const confirm=$('#selection-confirm');
 const saveSelection=$('#selection-save');
 const note=$('#selection-note');
 const settings=$('#view-settings');
 const record=$('#view-record');
 const card=el('section',undefined,'card settings-card session-profile-card');
 const title=el('h2','Профиль МИРЭА');
 const details=el('p','Проверяю профиль…','muted');
 const edit=el('button','Изменить профиль','secondary');
 edit.type='button';
 edit.disabled=true;
 card.append(title,details,edit);
 settings.insertBefore(card,settings.children[1]);
 const continueSelection=el('button','Выбрать пару для записи','secondary session-pending');
 continueSelection.type='button';
 continueSelection.hidden=true;
 record.querySelector('.recorder-hero').after(continueSelection);

 let profile=null;
 let status=null;
 let active='';
 let ignored='';
 let selected=null;
 let slots=[];
 let selecting=false;
 let savingProfile=false;

 function updateProfile(value){
  profile=value;
  edit.disabled=false;
  details.textContent=value.group?value.group+' · '+value.course+' курс':'Группа и курс не указаны';
 }
 function openProfile(){
  if(!profile||profileDialog.open||selectionDialog.open)return;
  groupField.value=profile.group||'';
  courseField.value=profile.course||'';
  $('#mirea-profile-error').textContent='';
  profileDialog.showModal();
 }
 async function storeProfile(value){
  if(savingProfile)return;
  savingProfile=true;
  for(const button of profileForm.querySelectorAll('button'))button.disabled=true;
  try{
   updateProfile(await post('/mirea-profile',value));
   profileDialog.close();
   window.refreshScheduleData?.();
  }catch(error){
   $('#mirea-profile-error').textContent=error.message;
  }finally{
   savingProfile=false;
   for(const button of profileForm.querySelectorAll('button'))button.disabled=false;
  }
 }
 profileForm.onsubmit=event=>{
  event.preventDefault();
  storeProfile({group:groupField.value,course:Number(courseField.value)});
 };
 $('#mirea-skip').onclick=()=>storeProfile({skip:true});
 profileDialog.addEventListener('cancel',event=>{if(!profile?.configured||savingProfile)event.preventDefault()});
 profileDialog.addEventListener('close',()=>{if(status)reconcile()});
 edit.onclick=openProfile;
 fetch('/mirea-profile',{cache:'no-store'}).then(response=>{
  if(!response.ok)throw Error('Профиль недоступен');
  return response.json();
 }).then(value=>{updateProfile(value);reconcile()}).catch(error=>{details.textContent=error.message});

 function updateSave(){
  saveSelection.disabled=selecting||(selected==='manual'?!manual.value.trim():selected===null);
 }
 function showOptions(rows,suggested){
  slots=rows;
  const shown=rows.map((lesson,index)=>{
   const radio=el('input');
   radio.type='radio';
   radio.name='lecture-choice';
   radio.value=index;
   radio.checked=selected===index;
   radio.onchange=()=>{
    selected=index;
    $('#selection-manual-label').hidden=true;
    updateSave();
   };
   const label=el('label',undefined,'session-choice');
   const text=el('span');
   const description=[lesson.start+'–'+lesson.end,lesson.type,lesson.room||lesson.variants?.map(row=>row.room).filter(Boolean).join(' / ')].filter(Boolean);
   if(index===suggested)description.push('По времени записи');
   text.append(el('strong',lesson.subject),el('small',description.join(' · ')));
   label.append(radio,text);
   return label;
  });
  for(const element of Array.from(choices.children).slice(1))element.remove();
  choices.append(...shown);
  choices.hidden=!rows.length;
 }
 function showConfirm(show){
  selectionForm.hidden=show;
  confirm.hidden=!show;
  $('#selection-error').textContent='';
  if(show)$('#selection-back').focus();
  else $('#selection-delete').focus();
 }
 function openSelection(name){
  active=name;
  selected=null;
  slots=[];
  manual.value='';
  $('#selection-manual-label').hidden=true;
  $('#selection-details').textContent='';
  selectionForm.hidden=false;
  confirm.hidden=true;
  $('#selection-error').textContent='';
  note.textContent=profile?.group?'Загружаю расписание…':'Проверяю доступное расписание…';
  showOptions([],null);
  updateSave();
  selectionDialog.showModal();
  fetch('/recording-selection?file='+encodeURIComponent(name),{cache:'no-store'}).then(async response=>{
   const value=await response.json();
   if(!response.ok)throw Error(value.error||'Расписание недоступно');
   if(active!==name||!selectionDialog.open)return;
   const date=new Date(value.date+'T12:00:00Z');
   const day=new Intl.DateTimeFormat('ru',{day:'numeric',month:'long',timeZone:'UTC'}).format(date);
   $('#selection-details').textContent=day+' · начало в '+value.start+' · '+timeLabel(value.seconds);
   if(selected===null)selected=value.suggested;
   showOptions(value.choices,value.suggested);
   note.textContent=value.note||(value.choices.length?'Проверь предложение или выбери другую пару.':'В расписании на этот день нет занятий. Можно указать название вручную.');
   updateSave();
  }).catch(error=>{if(active===name&&selectionDialog.open)note.textContent=error.message});
 }
 function reconcile(){
  const pending=status?.pending_lessons||[];
  continueSelection.hidden=!pending.length;
  if(profileDialog.open||selectionDialog.open||status?.recording||status?.busy)return;
  if(profile&&!profile.configured){openProfile();return;}
  if(pending.length&&pending[0]!==ignored)openSelection(pending[0]);
 }
 window.updateRecordingSelection=value=>{status=value;reconcile()};
 continueSelection.onclick=()=>{
  ignored='';
  reconcile();
 };
 selectionDialog.addEventListener('cancel',event=>{
  if(selecting){event.preventDefault();return;}
  ignored=active;
 });
 selectionDialog.addEventListener('close',()=>{
  active='';
  if(status)setTimeout(reconcile,0);
 });
 $('#selection-name').onclick=()=>{
  selected='manual';
  for(const radio of choices.querySelectorAll('input'))radio.checked=false;
  $('#selection-manual-label').hidden=false;
  manual.focus();
  updateSave();
 };
 manual.oninput=updateSave;
 $('#selection-delete').onclick=()=>showConfirm(true);
 $('#selection-back').onclick=()=>showConfirm(false);

 async function decide(action,lesson){
  if(selecting||!active)return;
  const file=active;
  selecting=true;
  $('#selection-error').textContent='';
  for(const button of selectionDialog.querySelectorAll('button'))button.disabled=true;
  try{
   await post('/recording-selection',{file,action,lesson});
   ignored=file;
   selectionDialog.close();
   await update();
  }catch(error){
   $('#selection-error').textContent=error.message;
  }finally{
   selecting=false;
   for(const button of selectionDialog.querySelectorAll('button'))button.disabled=false;
   updateSave();
  }
 }
 selectionForm.onsubmit=event=>{
  event.preventDefault();
  if(selected==='manual'&&manual.value.trim())decide('save',{subject:manual.value.trim()});
  else if(Number.isInteger(selected)&&slots[selected])decide('save',slots[selected]);
 };
 $('#selection-outside').onclick=()=>decide('save',null);
 $('#selection-discard').onclick=()=>decide('discard');
})();
