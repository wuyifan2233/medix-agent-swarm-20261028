(() => {
const link=document.createElement('button');link.type='button';link.className='sms-login-switch';link.textContent='立即注册';
document.getElementById('registerLinkSlot').append(link);
const dialog=document.createElement('dialog');dialog.className='settings-dialog phone-dialog';
dialog.innerHTML='<div class="phone-dialog-heading"><h2>注册账号</h2><button type="button" aria-label="关闭注册账号">×</button></div><form><p class="sms-help">验证手机号并设置密码，创建你的账号。</p><label>手机号</label><input type="tel" autocomplete="tel-national" pattern="1[3-9][0-9]{9}" maxlength="11" required><label>验证码</label><div class="sms-code-row"><input inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required><button type="button">获取验证码</button></div><label>密码</label><input type="password" autocomplete="new-password" minlength="8" maxlength="20" required><p class="sms-help">8–20 位，大小写字母、数字、符号至少三类。</p><label>确认密码</label><input type="password" autocomplete="new-password" required><div class="avatar-crop-actions"><button class="settings-primary" type="submit">创建账号</button><button class="settings-secondary" type="button">取消</button></div><p class="settings-feedback" role="status"></p></form>';
document.body.append(dialog);
const form=dialog.querySelector('form'), fields=form.querySelectorAll('input'), buttons=form.querySelectorAll('button'), feedback=form.querySelector('[role=status]');
const basics=document.createElement('fieldset');basics.id='registerBasics';
basics.innerHTML='<legend>基本信息</legend><p>仅在注册时保存，之后不可修改。各项均可选择不提供。</p><div class="register-basics-grid"><label class="register-name">姓名（选填）<input name="basicName" maxlength="50" autocomplete="name"></label><label>出生年月（选填）<input name="birthMonth" type="month"></label><label>性别<select name="basicSex"><option value="undisclosed">不愿提供</option><option value="female">女</option><option value="male">男</option></select></label></div>';
form.querySelector('.avatar-crop-actions').before(basics);
let challenge='',until=0,sending=false,busy=false,version=0;
link.onclick=()=>{document.getElementById('authDialog').close();dialog.showModal();};dialog.querySelector('button').onclick=()=>dialog.close();buttons[2].textContent='返回登录';buttons[2].onclick=()=>{dialog.close();if(!MedixAuth.user)MedixAuth.open();};
dialog.addEventListener('close',()=>{version++;challenge='';form.reset();feedback.textContent='';});
fields[0].oninput=()=>{version++;challenge='';};
const tick=()=>{const n=Math.max(0,Math.ceil((until-Date.now())/1000));buttons[0].disabled=sending||n>0;buttons[0].textContent=sending?'发送中…':n?`${n} 秒后重发`:'获取验证码';};
const timer=setInterval(tick,250);window.addEventListener('pagehide',()=>clearInterval(timer),{once:true});
buttons[0].onclick=async()=>{
 if(sending||Date.now()<until)return;if(!fields[0].reportValidity())return;
 const mine=version;sending=true;tick();
 try{const r=await MedixAuth.raw('/api/auth/phone/register/send',{method:'POST',body:JSON.stringify({phone_number:fields[0].value})});if(r.status===429)until=Date.now()+(Number(r.headers.get('Retry-After'))||60)*1000;if(!r.ok)throw new Error(await MedixAuth.detail(r));const d=await r.json();until=Date.now()+d.retry_after*1000;if(mine===version){challenge=d.challenge_id;feedback.textContent='验证码已发送，5 分钟内有效。';}}
 catch(e){if(mine===version)feedback.textContent=e.message;}finally{sending=false;tick();}
};
form.onsubmit=async e=>{e.preventDefault();if(busy)return;if(!challenge){feedback.textContent='请先获取验证码。';return;}const error=MedixPasswordPolicy.error(fields[2].value);if(error){feedback.textContent=error;return;}if(fields[2].value!==fields[3].value){feedback.textContent='两次密码不一致。';return;}const mine=version;busy=true;buttons[1].disabled=true;
 try{const r=await MedixAuth.raw('/api/auth/phone/register',{method:'POST',body:JSON.stringify({challenge_id:challenge,code:fields[1].value,new_password:fields[2].value,basic_profile:{name:form.elements.basicName.value.trim()||null,birth_month:form.elements.birthMonth.value||null,sex:form.elements.basicSex.value}})});if(!r.ok)throw new Error(await MedixAuth.detail(r));if(mine===version){const data=await r.json();challenge='';form.reset();dialog.close();MedixAuth.completeLogin(data);}}
 catch(e){if(mine===version)feedback.textContent=e.message;}finally{busy=false;buttons[1].disabled=false;}
};
fields.forEach(input=>{
 if(input.type!=='password')return;
 const wrap=document.createElement('div');wrap.className='settings-password-wrap';input.before(wrap);wrap.append(input);
 const eye=document.createElement('button');eye.type='button';eye.className='settings-password-eye';eye.setAttribute('aria-label','显示密码');eye.setAttribute('aria-pressed','false');eye.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/><path class="password-eye-slash" d="m3 3 18 18"/></svg>';wrap.append(eye);
 eye.onclick=()=>{const show=input.type==='password';input.type=show?'text':'password';eye.setAttribute('aria-label',show?'隐藏密码':'显示密码');eye.setAttribute('aria-pressed',String(show));};
 form.addEventListener('reset',()=>{input.type='password';eye.setAttribute('aria-label','显示密码');eye.setAttribute('aria-pressed','false');});
});
})();
