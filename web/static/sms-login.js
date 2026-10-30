(() => {
  const el = id => document.getElementById(id);
  function flow(prefix, authenticated) {
    const phone = el(prefix + (authenticated ? 'Number' : 'Phone')), code = el(prefix+'Code');
    const send = el(prefix+'Send'), submit = el(prefix + 'Submit'), feedback = el(prefix+'Feedback');
    const form = el(prefix+'Form');
    let challenge = '', generation = 0, until = 0, sending = false, submitting = false;
    function tick() {
      const seconds = Math.max(0, Math.ceil((until-Date.now())/1000));
      send.disabled = sending || seconds > 0;
      send.textContent = sending ? '发送中…' : seconds ? `${seconds} 秒后重发` : '获取验证码';
    }
    const timer = setInterval(tick, 1000);
    window.addEventListener('pagehide', () => clearInterval(timer), {once:true});
    const request = (url, options) => authenticated ? MedixAuth.fetch(url, options) : MedixAuth.raw(url, options);
    function reset() { generation++; challenge=''; form.reset(); feedback.textContent=''; }
    phone.oninput = () => { generation++; challenge=''; code.value=''; feedback.textContent=''; };
    send.onclick = async () => {
      if (sending || until > Date.now()) return;
      if (!/^1[3-9][0-9]{9}$/.test(phone.value)) { feedback.textContent='请输入正确的中国大陆手机号。'; phone.focus(); return; }
      const mine=generation, value=phone.value;
      sending=true; tick(); feedback.textContent='';
      try {
        const response=await request(authenticated ? '/api/auth/phone/send' : '/api/auth/sms/send', {method:'POST',body:JSON.stringify({phone_number:value})});
        if (response.status===429) until=Date.now()+Math.min(900,Number(response.headers.get('Retry-After'))||60)*1000;
        if (!response.ok) throw new Error(await MedixAuth.detail(response));
        const data=await response.json(); until=Date.now()+data.retry_after*1000;
        if(mine!==generation) return;
        challenge=data.challenge_id; feedback.textContent='验证码已发送，5 分钟内有效。'; code.focus();
      } catch(error) { if(mine===generation) feedback.textContent=error.message; }
      finally { sending=false; tick(); }
    };
    form.onsubmit = async event => {
      event.preventDefault(); if(submitting) return;
      if(!challenge) { feedback.textContent='请先获取验证码。'; return; }
      const mine=generation;
      const body={challenge_id:challenge,code:code.value};
      submitting=true; submit.disabled=true; feedback.textContent='';
      try {
        const response=await request(authenticated?'/api/auth/phone/bind':'/api/auth/sms/login',{method:'POST',body:JSON.stringify(body)});
        if(mine!==generation) return;
        if(!response.ok) throw new Error(await MedixAuth.detail(response));
        const data=await response.json();
        if(mine!==generation) return;
        if(authenticated) { await MedixAuth.refresh(); if(mine===generation) {reset(); form.hidden=true;} }
        else { MedixAuth.completeLogin(data); }
      } catch(error) { if(mine===generation) feedback.textContent=error.message; }
      finally { submitting=false; submit.disabled=false; }
    };
    return reset;
  }
  const resetLogin=flow('smsLogin',false), resetBinding=flow('settingsPhone',true);
  let smsMode=false, registering=false;
  function mode(value) {
    smsMode=value; el('authForm').hidden=value; el('smsLoginForm').hidden=!value;
    el('passwordMethodTab').setAttribute('aria-selected',String(!value));el('smsMethodTab').setAttribute('aria-selected',String(value));
    el('formTitle').textContent='登录 MediX';
    el('smsLoginSwitch').textContent=value?'密码登录':'验证码登录';
    el('formIntro').textContent=value?'使用已注册手机号获取验证码登录。':'登录后，开始你的健康对话。';
    if(!value) resetLogin();
  }
  el('smsLoginSwitch').onclick=()=>mode(!smsMode);
  el('passwordMethodTab').onclick=()=>mode(false);
  el('smsMethodTab').onclick=()=>mode(true);
  window.addEventListener('medix-auth-mode',event=>{
    registering=false; mode(false); el('smsLoginSwitch').hidden=true;
    if(registering) el('formIntro').textContent='创建账号，开启你的健康对话。';
  });
  el('authDialog').addEventListener('close',()=>{ resetLogin(); mode(false); });
  function renderPhone(user) {
    el('settingsPhoneMasked').textContent=user?.phone_masked || '未绑定';
    el('settingsPhoneOpen').hidden=Boolean(user?.phone_masked);
    if(user?.phone_masked) el('settingsPhoneForm').hidden=true;
  }
  el('settingsPhoneOpen').onclick=()=>{el('settingsPhoneForm').hidden=false;el('settingsPhoneNumber').focus();};
  el('settingsPhoneCancel').onclick=()=>{resetBinding();el('settingsPhoneForm').hidden=true;};
  el('settingsDialog').addEventListener('close',()=>{resetBinding();el('settingsPhoneForm').hidden=true;});
  window.addEventListener('medix-auth-change',event=>renderPhone(event.detail));
  window.addEventListener('medix-signout',()=>{resetBinding();resetLogin();});
  const unbind = document.createElement('button');
  unbind.type='button'; unbind.className='settings-phone-link'; unbind.textContent='解绑手机号';
  el('settingsPhoneOpen').parentElement.append(unbind);
  const panel=document.createElement('form'); panel.hidden=true;
  panel.innerHTML='<p class="sms-help">解绑不会删除资料或记忆。请验证当前手机号，并设置解绑后使用的账号密码（8–20 位，大小写字母、数字、符号至少三类）。</p><p id="unbindUsername"></p><label>新的账号密码</label><input type="password" autocomplete="new-password" minlength="8" maxlength="20" required><label>当前手机号验证码</label><div class="sms-code-row"><input inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" required><button type="button">获取验证码</button></div><div class="avatar-crop-actions"><button type="submit" class="settings-primary">确认解绑并退出</button><button type="button" class="settings-secondary">取消</button></div><p role="status" class="settings-feedback"></p>';
  const unbindDialog=document.createElement('dialog');
  unbindDialog.className='settings-dialog phone-dialog';
  unbindDialog.setAttribute('aria-labelledby','unbindTitle');
  unbindDialog.innerHTML='<div class="phone-dialog-heading"><h2 id="unbindTitle">解绑手机号</h2><button type="button" aria-label="关闭解绑">×</button></div>';
  document.body.append(unbindDialog);
  unbindDialog.append(panel);
  unbindDialog.querySelector('button').onclick=()=>unbindDialog.close();
  unbindDialog.addEventListener('close',()=>{panel.reset();unbindChallenge='';status.textContent='';});
  const inputs=panel.querySelectorAll('input'), buttons=panel.querySelectorAll('button'), status=panel.querySelector('[role=status]');
  let unbindChallenge='', resendUntil=0;
  function updateUnbind(user){ unbind.hidden=true; if(unbindDialog.open) unbindDialog.close(); unbindChallenge=''; el('unbindUsername').textContent=''; }
  MedixAuth.ready.then(updateUnbind).catch(()=>{});
  window.addEventListener('medix-auth-change',e=>updateUnbind(e.detail));
  unbind.onclick=()=>{panel.hidden=false;unbindDialog.showModal();}; buttons[2].onclick=()=>unbindDialog.close();
  let unbindSending=false;
function tickUnbind(){const remaining=Math.max(0,Math.ceil((resendUntil-Date.now())/1000));buttons[0].disabled=unbindSending||remaining>0;buttons[0].textContent=unbindSending?'发送中…':remaining?`${remaining} 秒后重发`:'获取验证码';}
const tickUnbindTimer=setInterval(tickUnbind,250);
window.addEventListener('pagehide',()=>clearInterval(tickUnbindTimer),{once:true});
buttons[0].onclick=async()=>{
    if(Date.now()<resendUntil)return;
    unbindSending=true;tickUnbind();
    try{const r=await MedixAuth.fetch('/api/auth/phone/unbind/send',{method:'POST',body:'{}'});if(r.status===429) resendUntil=Date.now()+Math.min(900,Number(r.headers.get('Retry-After'))||60)*1000;if(!r.ok)throw new Error(await MedixAuth.detail(r));const d=await r.json();unbindChallenge=d.challenge_id;resendUntil=Date.now()+d.retry_after*1000;status.textContent='验证码已发送，5 分钟内有效。';}
    catch(e){status.textContent=e.message;}finally{unbindSending=false;tickUnbind();}
  };
  panel.onsubmit=async e=>{e.preventDefault();if(!unbindChallenge){status.textContent='请先获取验证码。';return;}buttons[1].disabled=true;
    try{const r=await MedixAuth.fetch('/api/auth/phone/unbind',{method:'POST',body:JSON.stringify({challenge_id:unbindChallenge,code:inputs[1].value,new_password:inputs[0].value})});if(!r.ok)throw new Error(await MedixAuth.detail(r));location.reload();}
    catch(e){status.textContent=e.message;}finally{buttons[1].disabled=false;}
  };
  const eyeMarkup='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="password-eye-slash" d="m3 3 18 18"/></svg>';
  document.querySelectorAll('#settingsDialog input[type="password"],.phone-dialog input[type="password"]').forEach(input=>{
    const wrap=document.createElement('div');wrap.className='settings-password-wrap';
    input.before(wrap);wrap.append(input);
    const toggle=document.createElement('button');toggle.type='button';toggle.className='settings-password-eye';toggle.innerHTML=eyeMarkup;
    toggle.setAttribute('aria-label','显示密码');toggle.setAttribute('aria-pressed','false');
    wrap.append(toggle);
    toggle.onclick=()=>{const show=input.type==='password';input.type=show?'text':'password';toggle.classList.toggle('revealed',show);toggle.setAttribute('aria-label',show?'隐藏密码':'显示密码');toggle.setAttribute('aria-pressed',String(show));};
    const reset=()=>{input.type='password';toggle.classList.remove('revealed');toggle.setAttribute('aria-label','显示密码');toggle.setAttribute('aria-pressed','false');};
    input.form?.addEventListener('reset',reset);
    input.closest('dialog')?.addEventListener('close',reset);
  });
  MedixAuth.ready.then(renderPhone).catch(()=>{});
})();
