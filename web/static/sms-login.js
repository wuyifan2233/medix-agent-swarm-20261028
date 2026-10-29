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
      if(authenticated) body.current_password=el('settingsPhonePassword').value;
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
    el('smsLoginSwitch').textContent=value?'使用账号密码登录':'手机号验证码登录';
    el('formIntro').textContent=value?'使用已绑定手机号，验证码登录。':'登录后，开始你的健康对话。';
    if(!value) resetLogin();
  }
  el('smsLoginSwitch').onclick=()=>mode(!smsMode);
  window.addEventListener('medix-auth-mode',event=>{
    registering=event.detail; mode(false); el('smsLoginSwitch').hidden=registering;
    if(registering) el('formIntro').textContent='创建账号，开启你的健康对话。';
  });
  el('authDialog').addEventListener('close',()=>{ resetLogin(); mode(false); });
  function renderPhone(user) {
    el('settingsPhoneMasked').textContent=user?.phone_masked || '未绑定';
    el('settingsPhoneOpen').hidden=Boolean(user?.phone_masked);
    if(user?.phone_masked) el('settingsPhoneForm').hidden=true;
  }
  el('settingsPhoneOpen').onclick=()=>{el('settingsPhoneForm').hidden=false;el('settingsPhonePassword').focus();};
  el('settingsPhoneCancel').onclick=()=>{resetBinding();el('settingsPhoneForm').hidden=true;};
  el('settingsDialog').addEventListener('close',()=>{resetBinding();el('settingsPhoneForm').hidden=true;});
  window.addEventListener('medix-auth-change',event=>renderPhone(event.detail));
  window.addEventListener('medix-signout',()=>{resetBinding();resetLogin();});
  MedixAuth.ready.then(renderPhone).catch(()=>{});
})();
