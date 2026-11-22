(() => {
 const box=document.createElement('section');box.className='card settings-card';box.id='phone-pairing-card';
 const heading=el('h2','Телефон и Mac');
 const state=el('p','Проверяю подключение…','muted');state.setAttribute('role','status');
 const help=el('p','Подключи телефон и Mac к одной Wi-Fi сети. ESP для сопряжения не нужна.','muted');
 const start=el('button','Подключить телефон');start.type='button';
 const session=el('div');session.hidden=true;
 const instructions=el('p','На Android открой «Подключить Mac», выбери этот компьютер и введи код.');
 const code=el('code');code.id='phone-pairing-code';code.style.cssText='display:block;font-size:clamp(20px,4vw,32px);letter-spacing:.12em;padding:16px 0;user-select:all;overflow-wrap:anywhere';
 const clock=el('p','','muted');
 const manual=el('details');manual.append(el('summary','Mac не находится на телефоне?'));
 const address=el('p');manual.append(el('p','Проверь общую Wi-Fi сеть. В сети вуза устройства могут быть изолированы; можно включить точку доступа телефона и подключить к ней Mac.'),address);
 const cancel=el('button','Закрыть сопряжение','secondary');cancel.type='button';
 const pending=el('div');pending.hidden=true;pending.setAttribute('role','status');
 const phone=el('p');const verification=el('strong');verification.style.cssText='display:block;font-size:28px;letter-spacing:.18em';
 const confirmation=el('p','Сравни эти 6 цифр с экраном телефона. Подтверди, только если они совпадают.');
 const approve=el('button','Цифры совпадают · подключить');approve.type='button';
 const reject=el('button','Отклонить','secondary');reject.type='button';
 pending.append(phone,verification,confirmation,approve,reject);
 session.append(instructions,code,clock,manual,pending,cancel);
 const disconnect=el('button','Удалить сопряжение','secondary');disconnect.type='button';disconnect.hidden=true;
 const disconnectHelp=el('p','После удаления Mac перестанет получать записи с этого телефона. Сохранённые аудио и тексты останутся.','muted');disconnectHelp.hidden=true;
 const disconnectConfirm=el('div');disconnectConfirm.hidden=true;
 const forget=el('button','Удалить подключение телефона');forget.type='button';
 const keep=el('button','Оставить','secondary');keep.type='button';
 disconnectConfirm.append(disconnectHelp,forget,keep);
 const error=el('p','','error');error.setAttribute('role','alert');
 box.append(heading,state,help,start,session,disconnect,disconnectConfirm,error);
 document.querySelector('#view-settings').querySelector('.view-intro').after(box);
 const diagnostics=el('section',undefined,'card settings-card');diagnostics.id='phone-sync-diagnostics';
 const last=el('dd'),queue=el('dd'),reason=el('p');reason.setAttribute('role','status');
 const fields=el('dl');
 fields.append(el('dt','Последняя попытка'),last,el('dt','Очередь передачи'),queue);
 const retry=el('button','Повторить сейчас','secondary');retry.type='button';retry.disabled=true;
 const feedback=el('p','','muted');feedback.setAttribute('role','status');feedback.hidden=true;
 diagnostics.append(el('h2','Синхронизация с телефоном'),fields,reason,retry,feedback);
 box.after(diagnostics);
 let refreshing=false,retrying=false,attempt=0;
 const plurals=new Intl.PluralRules('ru');
 const dateFormat=new Intl.DateTimeFormat('ru-RU',{dateStyle:'short',timeStyle:'medium'});
 function renderDiagnostics(d){
  last.textContent=d.last_attempt?dateFormat.format(new Date(d.last_attempt*1000)):'Попыток ещё не было';
  queue.textContent=d.pending==null?'Нет сведений с телефона':(d.connected?'':'При последней связи · ')+d.pending+' '+({one:'файл',few:'файла'}[plurals.select(d.pending)]||'файлов');
  if(d.failed)queue.textContent+=' · ждут повтора: '+d.failed;
  reason.textContent=d.reason;
  retry.disabled=!d.can_retry||d.retry_requested||retrying;
  feedback.textContent=d.retry_requested?'Повтор запрошен. Mac проверит соединение.':'';
  feedback.hidden=!feedback.textContent;
 }
 async function refreshDiagnostics(){
  if(refreshing||retrying||document.hidden)return;
  refreshing=true;const previous=attempt;
  try{
   const r=await fetch('/phone-sync',{cache:'no-store',signal:AbortSignal.timeout(3000)});
   if(!r.ok)throw Error();
   const value=await r.json();
   if(!retrying&&previous===attempt)renderDiagnostics(value);
  }catch{if(!retrying&&previous===attempt)reason.textContent='Нет связи с приложением Mac.'}
  finally{refreshing=false}
 }
 retry.onclick=async()=>{
  if(retrying)return;
  retrying=true;attempt++;retry.disabled=true;
  try{
   const next=await post('/phone-sync/retry');
   retrying=false;renderDiagnostics(next);
   if(next.retry_accepted&&!next.retry_requested){feedback.textContent='Mac начал повторную попытку.';feedback.hidden=false}
   setTimeout(refreshDiagnostics,600);
  }catch{
   retrying=false;retry.disabled=false;
   feedback.textContent='Не удалось запросить повтор. Попробуй ещё раз.';feedback.hidden=false;
  }
 };
 let value=null,busy=false,polling=false;
 function render(next){
  value=next;
  state.textContent=next.paired?'Сопряжён: '+next.phone_name:'Телефон ещё не подключён';
  start.textContent=next.paired?'Подключить другой телефон':'Подключить телефон';start.hidden=next.active;
  session.hidden=!next.active;disconnect.hidden=!next.paired||next.active||!disconnectConfirm.hidden;
  code.textContent=next.code.match(/.{1,4}/g)?.join(' – ')||'';
  clock.textContent='Код действует ещё '+Math.floor(next.remaining/60)+':'+String(next.remaining%60).padStart(2,'0')+' · '+next.mac_name;
  address.textContent='Адрес Mac для ручного ввода: '+(next.addresses.join(', ')||'подключи Mac к Wi-Fi');
  const request=next.pending;pending.hidden=!request;
  const completed=request?.state==='complete';instructions.hidden=!!completed;code.hidden=!!completed;clock.hidden=!!completed;manual.hidden=!!completed;cancel.textContent=completed?'Готово':'Закрыть сопряжение';
  if(request){
   phone.textContent=request.name+' хочет подключиться';verification.textContent=request.verification;
   const waiting=request.state==='waiting';verification.hidden=!waiting;confirmation.hidden=!waiting;approve.hidden=!waiting;reject.hidden=!waiting;
   if(!waiting)phone.textContent=request.state==='complete'?'Телефон подключён. Записи и тексты будут переноситься автоматически.':'Подтверждено. Телефон сохраняет подключение…';
   approve.textContent=next.paired&&next.phone_name!==request.name?'Цифры совпадают · заменить телефон':'Цифры совпадают · подключить';
  }
 }
 async function act(path,body){
  if(busy)return;busy=true;error.textContent='';[start,cancel,approve,reject,forget].forEach(b=>b.disabled=true);
  try{render(await post(path,body))}catch(e){error.textContent=e.message}finally{busy=false;[start,cancel,approve,reject,forget].forEach(b=>b.disabled=false)}
 }
 start.onclick=()=>{disconnectConfirm.hidden=true;act('/phone-pairing/start')};
 cancel.onclick=()=>act('/phone-pairing/cancel');
 approve.onclick=()=>act('/phone-pairing/approve',{request_id:value?.pending?.id});
 reject.onclick=()=>act('/phone-pairing/reject',{request_id:value?.pending?.id});
 disconnect.onclick=()=>{disconnectConfirm.hidden=false;disconnectHelp.hidden=false;disconnect.hidden=true};
 keep.onclick=()=>{disconnectConfirm.hidden=true;disconnect.hidden=false};
 forget.onclick=async()=>{await act('/phone-pairing/forget');disconnectConfirm.hidden=true};
 async function poll(){
  if(polling)return;polling=true;refreshDiagnostics();
  try{if(!busy&&!document.hidden){const response=await fetch('/phone-pairing',{cache:'no-store',signal:AbortSignal.timeout(3000)});if(response.ok)render(await response.json());else state.textContent='Подключение временно недоступно'}}catch{state.textContent='Нет связи с приложением Mac'}finally{polling=false;setTimeout(poll,value?.active?1000:5000)}
 }
 poll();
})();
