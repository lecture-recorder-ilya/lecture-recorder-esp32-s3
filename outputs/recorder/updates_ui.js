(() => {
 const box=document.createElement('section');box.className='card settings-card';
 const title=document.createElement('h2');title.textContent='Обновления';
 const message=document.createElement('p');message.className='muted';message.setAttribute('role','status');
 const authMessage=document.createElement('p');authMessage.className='muted';
 const code=document.createElement('p');code.style.cssText='font-size:24px;font-weight:700;letter-spacing:3px;user-select:all';
 const verification=document.createElement('a');verification.textContent='Открыть GitHub и ввести код';verification.href='https://github.com/login/device';verification.target='_blank';verification.rel='noopener noreferrer';verification.style.display='block';
 const installation=document.createElement('a');installation.textContent='Разрешить чтение репозитория в GitHub';installation.target='_blank';installation.rel='noopener noreferrer';installation.style.cssText='display:block;margin:10px 0';
 const controls=document.createElement('div');controls.className='actions';
 const login=document.createElement('button');login.textContent='Войти в GitHub';
 const cancel=document.createElement('button');cancel.textContent='Отменить вход';
 const logout=document.createElement('button');logout.textContent='Выйти из GitHub';
 const button=document.createElement('button');button.textContent='Проверить новую версию';
 let generation=null;
 async function action(route){try{await post(route);await poll(false)}catch(error){authMessage.textContent=error.message}}
 login.onclick=()=>action('/update-auth/start');cancel.onclick=()=>action('/update-auth/cancel');logout.onclick=()=>action('/update-auth/disconnect');
 button.onclick=async()=>{button.disabled=true;try{await post('/check-updates');message.textContent='Проверяю…'}catch(error){message.textContent='Не удалось проверить: '+error.message}finally{button.disabled=false}};
 controls.append(login,cancel,logout,button);box.append(title,message,authMessage,code,verification,installation,controls);document.querySelector('#view-settings').append(box);
 async function poll(repeat=true){try{
  const r=await fetch('/app-info',{cache:'no-store',signal:AbortSignal.timeout(5000)});if(!r.ok)return;
  const value=await r.json(),auth=value.update_auth||{},status=value.updates?.message||'';
  message.textContent=/HTTP|SSL|Errno|urlopen|timed out|Offline|certificate/i.test(status)?'Не удалось проверить обновления. Попробуй позже.':status;
  authMessage.textContent=auth.message||'Вход в GitHub доступен после установки новой версии Mac.';
  login.hidden=!!auth.pending||!!auth.authorized;login.disabled=!auth.configured;
  cancel.hidden=!auth.pending;logout.hidden=!auth.authorized;
  code.hidden=verification.hidden=!auth.pending;code.textContent=auth.user_code||'';
  const safe=/^https:\/\/github\.com\/apps\/[a-z0-9-]+\/installations\/new$/.test(auth.installation_url||'');
  installation.hidden=!safe;if(safe)installation.href=auth.installation_url;
  if(generation&&generation!==value.generation){if(!document.querySelector('input:focus,textarea:focus'))location.reload();return}generation=value.generation;
 }catch{}finally{if(repeat)setTimeout(poll,5000)}}
 poll();document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll(false)});
})();
